"""FastAPI app serving the dashboard and JSON API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from govee_charts.address import register_mac, resolve_device_address
from govee_charts.db import Database
from govee_charts.decode import Reading

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


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


def create_app(
    db: Database,
    *,
    labels: dict[str, str] | None = None,
    federation_token: str | None = None,
    node_id: str = "local",
    suffix_map: dict[str, str] | None = None,
) -> FastAPI:
    app = FastAPI(title="Govee Charts", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.labels = {k.upper(): v for k, v in (labels or {}).items()}
    app.state.suffix_map = suffix_map or {}
    app.state.federation_token = federation_token or None
    app.state.node_id = node_id

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        return {"ok": True, "node_id": app.state.node_id}

    @app.get("/api/devices")
    async def api_devices() -> list[dict[str, Any]]:
        return await db.list_devices()

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
