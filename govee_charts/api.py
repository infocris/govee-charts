"""FastAPI app serving the dashboard and JSON API."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from govee_charts.address import register_mac, resolve_device_address
from govee_charts.apartment import (
    ORIENTATIONS,
    compass_from_deg,
    solar_bias_c,
    save_overrides,
    ventilation_mode,
)
from govee_charts.categories import normalize_door_patch, normalize_patch, taxonomy
from govee_charts.db import Database
from govee_charts.decode import Reading
from govee_charts.hvac import hvac_active_bands, is_hvac_active
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


class DoorPatch(BaseModel):
    room: str | None = None
    kind: str | None = None
    name: str | None = None

    model_config = {"extra": "forbid"}


class FacadePatch(BaseModel):
    exterior: list[str] = Field(default_factory=list)

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

    @app.get("/api/apartment")
    async def api_apartment(
        hours: float = Query(24.0, gt=0, le=168),
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
    ) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            return {"enabled": False, "rooms": [], "orientations": []}
        layout = weather_svc.apartment
        payload = layout.summary()
        payload["hours"] = hours

        # Attach sensors grouped by room category
        devices = await db.list_devices()
        by_room: dict[str, list[dict[str, Any]]] = {
            r["id"]: [] for r in payload["rooms"]
        }
        for d in devices:
            room = (d.get("room") or "").strip().lower()
            if room not in by_room:
                continue
            by_room[room].append(
                {
                    "address": d.get("address"),
                    "name": d.get("name") or d.get("address"),
                    "zone": d.get("zone"),
                    "temperature_c": d.get("temperature_c"),
                    "humidity": d.get("humidity"),
                }
            )
        for room in payload["rooms"]:
            room["sensors"] = by_room.get(room["id"], [])

        solar: dict[str, Any] = {"available": False}
        outdoor_summary: dict[str, Any] = {"available": False}
        forecast = None
        if weather_svc.enabled:
            try:
                forecast = await weather_svc.fetch_forecast(
                    latitude=latitude, longitude=longitude
                )
            except Exception as exc:
                solar = {"available": False, "error": str(exc)}
                forecast = None

        if forecast and forecast.get("enabled") and forecast.get("outdoor"):
            now = time.time()
            since = now - hours * 3600.0
            until = now + hours * 3600.0
            window = [
                p
                for p in forecast["outdoor"]
                if since <= float(p["ts"]) <= until
            ]
            if not window:
                window = list(forecast["outdoor"])

            outdoor_now = min(
                forecast["outdoor"],
                key=lambda p: abs(float(p["ts"]) - now),
            )
            temps = [float(p["temperature_c"]) for p in window]
            outdoor_points = [
                {
                    "ts": float(p["ts"]),
                    "temperature_c": round(float(p["temperature_c"]), 2),
                    "humidity": p.get("humidity"),
                    "shortwave_radiation": p.get("shortwave_radiation"),
                    "cloud_cover": p.get("cloud_cover"),
                    "wind_speed_ms": p.get("wind_speed_ms"),
                    "wind_direction_deg": p.get("wind_direction_deg"),
                }
                for p in window
            ]
            if temps:
                ws_now = outdoor_now.get("wind_speed_ms")
                wd_now = outdoor_now.get("wind_direction_deg")
                outdoor_summary = {
                    "available": True,
                    "hours": hours,
                    "temp_now": round(float(outdoor_now["temperature_c"]), 2),
                    "temp_min": round(min(temps), 2),
                    "temp_max": round(max(temps), 2),
                    "humidity_now": outdoor_now.get("humidity"),
                    "shortwave_radiation": outdoor_now.get("shortwave_radiation"),
                    "cloud_cover": outdoor_now.get("cloud_cover"),
                    "wind_speed_ms": (
                        round(float(ws_now), 2) if ws_now is not None else None
                    ),
                    "wind_direction_deg": (
                        round(float(wd_now), 1) if wd_now is not None else None
                    ),
                    "wind_compass": (
                        (compass_from_deg(float(wd_now)) or "").upper() or None
                        if wd_now is not None
                        else None
                    ),
                    "location": forecast.get("location"),
                    "points": outdoor_points,
                }

            all_exterior: list[str] = []
            for room in payload["rooms"]:
                all_exterior.extend(room.get("exterior") or [])

            sw = outdoor_now.get("shortwave_radiation")
            cloud = outdoor_now.get("cloud_cover")
            ws_now = outdoor_now.get("wind_speed_ms")
            wd_now = outdoor_now.get("wind_direction_deg")
            gains = []
            for room in payload["rooms"]:
                orients = tuple(room["exterior"])
                bias_now = solar_bias_c(
                    orients,
                    float(outdoor_now["ts"]),
                    layout.timezone,
                    shortwave_radiation=float(sw) if sw is not None else None,
                    cloud_cover=float(cloud) if cloud is not None else None,
                )
                room["solar_bias_c"] = round(bias_now, 2)
                gains.append({"id": room["id"], "solar_bias_c": round(bias_now, 2)})

                if orients:
                    room["ventilation"] = ventilation_mode(
                        window_kind="open",  # optimistic; UI refines with temp bands
                        orientations=orients,
                        all_exterior=all_exterior,
                        wind_speed_ms=float(ws_now) if ws_now is not None else None,
                        wind_direction_deg=float(wd_now) if wd_now is not None else None,
                    )
                else:
                    room["ventilation"] = None

                # Façade-effective outdoor over past + future window
                if orients and window:
                    eff_vals: list[float] = []
                    points: list[dict[str, Any]] = []
                    for p in window:
                        p_sw = p.get("shortwave_radiation")
                        p_cloud = p.get("cloud_cover")
                        bias = solar_bias_c(
                            orients,
                            float(p["ts"]),
                            layout.timezone,
                            shortwave_radiation=(
                                float(p_sw) if p_sw is not None else None
                            ),
                            cloud_cover=(
                                float(p_cloud) if p_cloud is not None else None
                            ),
                        )
                        t_eff = float(p["temperature_c"]) + bias
                        eff_vals.append(t_eff)
                        points.append(
                            {
                                "ts": float(p["ts"]),
                                "temperature_c": round(t_eff, 2),
                                "solar_bias_c": round(bias, 2),
                            }
                        )
                    room["facade_projection"] = {
                        "temp_min": round(min(eff_vals), 2),
                        "temp_max": round(max(eff_vals), 2),
                        "temp_now": round(
                            float(outdoor_now["temperature_c"]) + bias_now, 2
                        ),
                        "hours": hours,
                        "points": points,
                    }
                else:
                    room["facade_projection"] = None

            solar = {
                "available": True,
                "ts": outdoor_now["ts"],
                "temperature_c": outdoor_now.get("temperature_c"),
                "shortwave_radiation": sw,
                "cloud_cover": cloud,
                "wind_speed_ms": (
                    round(float(ws_now), 2) if ws_now is not None else None
                ),
                "wind_direction_deg": (
                    round(float(wd_now), 1) if wd_now is not None else None
                ),
                "wind_compass": (
                    (compass_from_deg(float(wd_now)) or "").upper() or None
                    if wd_now is not None
                    else None
                ),
                "gains": gains,
            }

            # Indoor history (past) + projections (future) for rooms with sensors
            addresses: list[str] = []
            addr_by_room: dict[str, str] = {}
            for room in payload["rooms"]:
                room["room_history"] = None
                room["room_projection"] = None
                for s in room["sensors"]:
                    zone = (s.get("zone") or "").strip().lower()
                    if zone == "exterior":
                        continue
                    if s.get("address"):
                        addr = str(s["address"]).upper()
                        addresses.append(addr)
                        addr_by_room[room["id"]] = addr
                        break

            for room in payload["rooms"]:
                addr = addr_by_room.get(room["id"])
                if not addr:
                    continue
                try:
                    hist = await db.history(addr, hours)
                except Exception:
                    hist = []
                if hist:
                    room["room_history"] = {
                        "address": addr,
                        "points": [
                            {
                                "ts": float(p["ts"]),
                                "temperature_c": round(float(p["temperature_c"]), 2),
                                "humidity": p.get("humidity"),
                            }
                            for p in hist
                            if p.get("temperature_c") is not None
                        ],
                    }

            if addresses:
                try:
                    proj_resp = await weather_svc.build_response(
                        db,
                        hours=hours,
                        addresses=addresses,
                        latitude=latitude,
                        longitude=longitude,
                    )
                    projections = proj_resp.get("projections") or {}
                    for room in payload["rooms"]:
                        addr = addr_by_room.get(room["id"])
                        if not addr:
                            continue
                        proj = projections.get(addr)
                        if not proj or not proj.get("summary"):
                            continue
                        summary = proj["summary"]
                        room["room_projection"] = {
                            "address": addr,
                            "name": proj.get("name") or addr,
                            "model": proj.get("model"),
                            "temp_min": summary.get("temp_min"),
                            "temp_max": summary.get("temp_max"),
                            "bias_temp": proj.get("bias_temp"),
                            "hours": hours,
                            "points": proj.get("points") or [],
                        }
                except Exception as exc:
                    logger.warning("Apartment room projections failed: %s", exc)

        payload["solar"] = solar
        payload["outdoor"] = outdoor_summary
        return payload

    @app.patch("/api/apartment/rooms/{room_id}")
    async def api_patch_facade(room_id: str, payload: FacadePatch) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            raise HTTPException(status_code=503, detail="Apartment layout not available")
        layout = weather_svc.apartment
        if not layout.rooms:
            raise HTTPException(status_code=404, detail="No apartment rooms configured")
        unknown = [
            o
            for o in payload.exterior
            if str(o).strip().lower() not in ORIENTATIONS
        ]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid orientation(s): {', '.join(unknown)}",
            )
        try:
            updated = layout.set_exterior(room_id, payload.exterior)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            save_overrides(layout)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to persist façades: {exc}"
            ) from exc
        logger.info(
            "Façade updated for %s → %s",
            room_id,
            ",".join(updated["exterior"]) or "(none)",
        )
        return updated

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

    @app.get("/api/doors")
    async def api_doors() -> dict[str, Any]:
        """Latest open/closed state for each door/window contact sensor."""
        sensors = await db.list_door_sensors()
        return {"sensors": sensors, "count": len(sensors)}

    @app.patch("/api/doors/{sensor_id:path}")
    async def api_patch_door(
        sensor_id: str,
        payload: DoorPatch,
    ) -> dict[str, Any]:
        provided = payload.model_dump(exclude_unset=True)
        try:
            patch = normalize_door_patch(
                room=provided["room"] if "room" in provided else ...,
                kind=provided["kind"] if "kind" in provided else ...,
                name=provided["name"] if "name" in provided else ...,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        kwargs: dict[str, Any] = {}
        if "room" in patch:
            kwargs["room"] = patch["room"]
        if "kind" in patch:
            kwargs["kind"] = patch["kind"]
        if "name" in patch and patch["name"] is not None:
            kwargs["name"] = patch["name"]

        updated = await db.update_door_sensor(sensor_id, **kwargs)
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown door sensor")
        return updated

    @app.get("/api/doors/history")
    async def api_doors_history(
        hours: float = Query(168.0, gt=0, le=8760),
        sensor_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Open/close event history (usable as time-series data)."""
        events = await db.door_history(hours=hours, sensor_id=sensor_id)
        return {
            "hours": hours,
            "sensor_id": sensor_id,
            "events": events,
            "count": len(events),
        }

    @app.get("/api/hvac")
    async def api_hvac() -> dict[str, Any]:
        """Latest climate state + latest power sample."""
        climate = await db.latest_hvac()
        power = await db.latest_power()
        active = is_hvac_active(str((climate or {}).get("state") or ""))
        return {
            "climate": climate,
            "power": power,
            "active": active,
        }

    @app.get("/api/hvac/history")
    async def api_hvac_history(
        hours: float = Query(168.0, gt=0, le=8760),
        entity_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Climate / HVAC event history + derived active bands."""
        events = await db.hvac_history(hours=hours, entity_id=entity_id)
        bands = hvac_active_bands(events)
        return {
            "hours": hours,
            "entity_id": entity_id,
            "events": events,
            "bands": bands,
            "count": len(events),
        }

    @app.get("/api/power/history")
    async def api_power_history(
        hours: float = Query(168.0, gt=0, le=8760),
        entity_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Whole-home (or other) power samples in watts."""
        points = await db.power_history(hours=hours, entity_id=entity_id)
        return {
            "hours": hours,
            "entity_id": entity_id,
            "points": points,
            "count": len(points),
        }

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
