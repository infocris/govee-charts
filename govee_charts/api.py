"""FastAPI app serving the dashboard and JSON API."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from govee_charts.address import register_mac, resolve_device_address
from govee_charts.categories import normalize_patch, taxonomy
from govee_charts.db import Database
from govee_charts.decode import Reading
from govee_charts.weather import WeatherService

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
logger = logging.getLogger(__name__)


class IngestReading(BaseModel):
    address: str = Field(min_length=1)
    name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    ts: float
    temperature_c: float
    humidity: float
    battery: int
    rssi: int | None = None


class IngestPayload(BaseModel):
    node_id: str = Field(default="peer", min_length=1, max_length=64)
    readings: list[IngestReading] = Field(min_length=1, max_length=200)


class CategoryPatch(BaseModel):
    zone: str | None = None
    height: str | None = None
    room: str | None = None

    model_config = {"extra": "forbid"}


def create_app(
    db: Database,
    *,
    labels: dict[str, str] | None = None,
    federation_token: str | None = None,
    node_id: str = "local",
    peers: list[str] | None = None,
    suffix_map: dict[str, str] | None = None,
    weather: WeatherService | None = None,
    on_restart: Callable[[], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="Govee Charts", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.labels = {k.upper(): v for k, v in (labels or {}).items()}
    app.state.suffix_map = suffix_map or {}
    app.state.federation_token = federation_token or None
    app.state.node_id = node_id
    app.state.peers = [p.rstrip("/") for p in (peers or []) if p.strip()]
    app.state.weather = weather
    app.state.on_restart = on_restart
    app.state.restart_scheduled = False

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        return {
            "ok": True,
            "node_id": app.state.node_id,
            "systemd": bool(os.environ.get("INVOCATION_ID")),
        }

    @app.post("/api/restart")
    async def api_restart() -> dict[str, Any]:
        if app.state.restart_scheduled:
            return {
                "ok": True,
                "scheduled": True,
                "systemd": bool(os.environ.get("INVOCATION_ID")),
                "message": "Restart already scheduled",
            }

        callback = app.state.on_restart
        if callback is None:
            raise HTTPException(status_code=503, detail="Restart not available")

        app.state.restart_scheduled = True
        under_systemd = bool(os.environ.get("INVOCATION_ID"))

        async def _delayed() -> None:
            await asyncio.sleep(0.6)
            logger.warning("Restart requested from UI — stopping process")
            callback()

        asyncio.create_task(_delayed())
        return {
            "ok": True,
            "scheduled": True,
            "systemd": under_systemd,
            "message": (
                "Restarting via systemd…"
                if under_systemd
                else "Process exiting — restart manually if not under systemd"
            ),
        }

    @app.get("/api/federation")
    async def api_federation() -> dict[str, Any]:
        return {
            "node_id": app.state.node_id,
            "peers": [{"url": url} for url in app.state.peers],
        }

    @app.get("/api/devices")
    async def api_devices() -> list[dict[str, Any]]:
        return await db.list_devices()

    @app.get("/api/categories")
    async def api_categories() -> dict[str, Any]:
        return taxonomy()

    @app.patch("/api/devices/{address}/categories")
    async def api_patch_categories(
        address: str,
        payload: CategoryPatch,
    ) -> dict[str, Any]:
        provided = payload.model_dump(exclude_unset=True)
        if not provided:
            raise HTTPException(status_code=400, detail="Empty patch body")
        try:
            patch = normalize_patch(
                zone=provided["zone"] if "zone" in provided else ...,
                height=provided["height"] if "height" in provided else ...,
                room=provided["room"] if "room" in provided else ...,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = await db.update_device_categories(address, **patch)
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        return updated

    @app.get("/api/history")
    async def api_history(
        address: str = Query(..., min_length=1),
        hours: float = Query(24.0, gt=0, le=720),
    ) -> dict[str, Any]:
        points = await db.history(address, hours)
        if not points:
            devices = await db.list_devices()
            known = {d["address"].upper() for d in devices}
            if address.upper() not in known:
                raise HTTPException(status_code=404, detail="Unknown device")
        return {"address": address.upper(), "hours": hours, "points": points}

    @app.get("/api/forecast")
    async def api_forecast(
        hours: float = Query(24.0, gt=0, le=168),
        address: list[str] | None = Query(default=None),
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
    ) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None:
            return {
                "enabled": False,
                "hours": hours,
                "location": None,
                "outdoor": [],
                "projections": {},
            }
        if (latitude is None) ^ (longitude is None):
            raise HTTPException(
                status_code=400,
                detail="latitude and longitude must be provided together",
            )
        addresses = [a for a in (address or []) if a.strip()]
        return await weather_svc.build_response(
            db,
            hours=hours,
            addresses=addresses,
            latitude=latitude,
            longitude=longitude,
        )

    @app.post("/api/ingest")
    async def api_ingest(
        payload: IngestPayload,
        request: Request,
        x_govee_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        expected = app.state.federation_token
        if expected:
            provided = x_govee_token or request.headers.get("Authorization", "").removeprefix(
                "Bearer "
            ).strip()
            if provided != expected:
                raise HTTPException(status_code=401, detail="Invalid federation token")

        if payload.node_id == app.state.node_id:
            raise HTTPException(status_code=400, detail="Refusing ingest from self")

        labels: dict[str, str] = app.state.labels
        suffix_map: dict[str, str] = app.state.suffix_map
        inserted = 0
        for item in payload.readings:
            ble_name = item.name
            address = resolve_device_address(
                item.address,
                ble_name,
                suffix_map=suffix_map,
            )
            register_mac(suffix_map, address)
            display = labels.get(address) or ble_name
            reading = Reading(
                temperature_c=item.temperature_c,
                humidity=item.humidity,
                battery=item.battery,
                address=address,
                name=ble_name,
                model=item.model.lower(),
                rssi=item.rssi,
            )
            ok = await db.upsert_reading(
                reading,
                display,
                ts=item.ts,
                source=payload.node_id,
            )
            if ok:
                inserted += 1

        return {
            "ok": True,
            "received": len(payload.readings),
            "inserted": inserted,
            "node_id": app.state.node_id,
        }

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
