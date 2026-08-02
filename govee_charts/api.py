"""FastAPI app serving the dashboard and JSON API."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
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
from govee_charts.backfill import BackfillService
from govee_charts.categories import normalize_door_patch, normalize_patch, taxonomy
from govee_charts.csv_import import MAX_UPLOAD_BYTES, parse_upload, summarize_samples
from govee_charts.db import Database, coverage_from_minute_set
from govee_charts.decode import Reading
from govee_charts.federation import csv_source
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
    source: str | None = None


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


class BackfillDevicePatch(BaseModel):
    address: str = Field(min_length=1)
    enabled: bool

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
    backfill: BackfillService | None = None,
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
    app.state.backfill = backfill
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

    @app.get("/api/backfill")
    async def api_backfill(
        recent_limit: int = Query(100, ge=1, le=500),
        job_limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        """Live GATT history backfill queue snapshot + recent recovered readings."""
        recent = await db.recent_gatt_readings(limit=recent_limit)
        recent_jobs = await db.recent_backfill_jobs(limit=job_limit)
        service: BackfillService | None = app.state.backfill
        if service is None:
            return {
                "enabled": False,
                "paused": False,
                "worker": "disabled",
                "current": None,
                "queue": [],
                "devices": [],
                "totals": {
                    "pending": 0,
                    "running": 0,
                    "done": 0,
                    "failed": 0,
                },
                "config": None,
                "recent": recent,
                "recent_jobs": recent_jobs,
            }
        snap = await service.snapshot()
        snap["recent"] = recent
        snap["recent_jobs"] = recent_jobs
        return snap

    @app.post("/api/backfill/pause")
    async def api_backfill_pause(
        recent_limit: int = Query(100, ge=1, le=500),
        job_limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        service: BackfillService | None = app.state.backfill
        if service is None:
            raise HTTPException(status_code=503, detail="Backfill not available")
        service.pause()
        snap = await service.snapshot()
        snap["recent"] = await db.recent_gatt_readings(limit=recent_limit)
        snap["recent_jobs"] = await db.recent_backfill_jobs(limit=job_limit)
        return snap

    @app.post("/api/backfill/resume")
    async def api_backfill_resume(
        recent_limit: int = Query(100, ge=1, le=500),
        job_limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        service: BackfillService | None = app.state.backfill
        if service is None:
            raise HTTPException(status_code=503, detail="Backfill not available")
        service.resume()
        snap = await service.snapshot()
        snap["recent"] = await db.recent_gatt_readings(limit=recent_limit)
        snap["recent_jobs"] = await db.recent_backfill_jobs(limit=job_limit)
        return snap

    @app.post("/api/backfill/refresh")
    async def api_backfill_refresh(
        recent_limit: int = Query(100, ge=1, le=500),
        job_limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        service: BackfillService | None = app.state.backfill
        if service is None:
            raise HTTPException(status_code=503, detail="Backfill not available")
        enqueued = await service.refresh_gaps(force=True)
        snap = await service.snapshot()
        snap["enqueued"] = enqueued
        snap["recent"] = await db.recent_gatt_readings(limit=recent_limit)
        snap["recent_jobs"] = await db.recent_backfill_jobs(limit=job_limit)
        return snap

    @app.post("/api/backfill/devices")
    async def api_backfill_device(
        payload: BackfillDevicePatch,
        recent_limit: int = Query(100, ge=1, le=500),
        job_limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        """Enable or disable GATT backfill for one sensor (opt-in)."""
        service: BackfillService | None = app.state.backfill
        if service is None:
            raise HTTPException(status_code=503, detail="Backfill not available")
        try:
            result = await service.set_device_enabled(
                payload.address, payload.enabled
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snap = await service.snapshot()
        snap["device_update"] = result
        snap["recent"] = await db.recent_gatt_readings(limit=recent_limit)
        snap["recent_jobs"] = await db.recent_backfill_jobs(limit=job_limit)
        return snap

    async def _read_import_upload(file: UploadFile) -> tuple[str, bytes]:
        filename = file.filename or "upload.csv"
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty upload")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit",
            )
        return filename, data

    async def _resolve_import_device(address: str) -> dict[str, Any]:
        addr = address.strip().upper()
        if not addr:
            raise HTTPException(status_code=400, detail="address is required")
        device = await db.get_device(addr)
        if device is None:
            raise HTTPException(status_code=404, detail=f"Unknown device {addr}")
        return device

    @app.post("/api/backfill/import/preview")
    async def api_backfill_import_preview(
        address: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """Parse a Govee CSV/ZIP and compare against existing readings (no write)."""
        device = await _resolve_import_device(address)
        addr = str(device["address"]).upper()
        labels: dict[str, str] = app.state.labels
        name = labels.get(addr) or str(device.get("name") or addr)
        filename, data = await _read_import_upload(file)
        try:
            samples, bad_rows, files, file_stats = parse_upload(filename, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        file_summary = summarize_samples(samples)
        file_summary["bad_rows"] = bad_rows
        file_summary["file_count"] = len(files)
        empty_cov_meta = {
            "coverage_pct": 0.0,
            "counts": {"full": 0, "partial": 0, "missing": 0},
        }

        if not samples:
            return {
                "address": addr,
                "name": name,
                "files": files,
                "file_stats": file_stats,
                "file": file_summary,
                "existing": {
                    "samples_in_range": 0,
                    "range": {"start": None, "end": None},
                    "temp": {"min": None, "max": None},
                    "humidity": {"min": None, "max": None},
                    "sources": {},
                },
                "compare": {
                    "already_present": 0,
                    "would_insert": 0,
                    "file_only_minutes": 0,
                    "db_only_minutes": 0,
                    "overlap_pct": 0.0,
                },
                "file_segments": [],
                "db_segments": [],
                "coverage": {
                    "bucket": "day",
                    "file": empty_cov_meta,
                    "db": empty_cov_meta,
                },
            }

        start = float(file_summary["range"]["start"])
        end = float(file_summary["range"]["end"])
        # Inclusive end minute → exclusive window end for coverage helpers.
        end_excl = end + 60.0
        file_minutes = {int(ts // 60) for ts, _, _ in samples}
        existing_minutes = await db.reading_exact_minutes(addr, start, end_excl)
        already = len(file_minutes & existing_minutes)
        would_insert = len(file_minutes - existing_minutes)
        db_only = len(existing_minutes - file_minutes)
        overlap_pct = (
            round(100.0 * already / len(file_minutes), 1) if file_minutes else 0.0
        )
        existing = await db.reading_range_stats(addr, start, end_excl)

        file_cov = coverage_from_minute_set(file_minutes, start, end_excl)
        db_cov = coverage_from_minute_set(existing_minutes, start, end_excl)

        return {
            "address": addr,
            "name": name,
            "files": files,
            "file_stats": file_stats,
            "file": file_summary,
            "existing": existing,
            "compare": {
                "already_present": already,
                "would_insert": would_insert,
                "file_only_minutes": would_insert,
                "db_only_minutes": db_only,
                "overlap_pct": overlap_pct,
            },
            "file_segments": file_cov.get("segments") or [],
            "db_segments": db_cov.get("segments") or [],
            "coverage": {
                "bucket": file_cov.get("bucket") or "day",
                "file": {
                    "coverage_pct": file_cov.get("coverage_pct"),
                    "counts": file_cov.get("counts"),
                },
                "db": {
                    "coverage_pct": db_cov.get("coverage_pct"),
                    "counts": db_cov.get("counts"),
                },
            },
        }

    @app.post("/api/backfill/import")
    async def api_backfill_import(
        address: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """Ingest a previously previewed Govee CSV/ZIP into readings."""
        device = await _resolve_import_device(address)
        addr = str(device["address"]).upper()
        labels: dict[str, str] = app.state.labels
        name = labels.get(addr) or str(device.get("name") or addr)
        model = str(device.get("model") or "h5075")
        filename, data = await _read_import_upload(file)
        try:
            samples, bad_rows, files, _file_stats = parse_upload(filename, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not samples:
            raise HTTPException(status_code=400, detail="No valid samples in upload")

        battery = await db.last_battery(addr)
        if battery is None:
            battery = 0
        source = csv_source(str(app.state.node_id))
        inserted = await db.insert_gatt_readings(
            address=addr,
            display_name=name,
            model=model,
            samples=samples,
            battery=int(battery),
            rssi=None,
            source=source,
        )
        summary = summarize_samples(samples)
        skipped = max(0, len(samples) - inserted)
        logger.info(
            "CSV import %s → %s: inserted=%d skipped=%d bad_rows=%d files=%s",
            source,
            name,
            inserted,
            skipped,
            bad_rows,
            files,
        )
        return {
            "address": addr,
            "name": name,
            "files": files,
            "source": source,
            "parsed": len(samples),
            "bad_rows": bad_rows,
            "inserted": inserted,
            "skipped": skipped,
            "range": summary["range"],
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

    @app.get("/api/coverage")
    async def api_coverage(
        address: str = Query(..., min_length=1),
        hours: float | None = Query(default=2160.0, gt=0, le=26280),
        since: float | None = Query(default=None),
        until: float | None = Query(default=None),
        since_first: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Per-sensor full / partial / missing coverage segments."""
        addr = address.strip().upper()
        device = await db.get_device(addr)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        labels: dict[str, str] = app.state.labels
        name = labels.get(addr) or str(device.get("name") or addr)

        now = time.time()
        if since is not None and until is not None:
            t0 = float(since)
            t1 = float(until)
            if t1 < t0:
                t0, t1 = t1, t0
        elif since_first:
            first = device.get("first_seen")
            t0 = float(first) if first is not None else now - 90 * 86400.0
            t1 = now
            t0 = max(t0, t1 - 26280 * 3600.0)
        else:
            h = float(hours if hours is not None else 2160.0)
            t1 = now
            t0 = t1 - h * 3600.0

        report = await db.coverage_report(addr, t0, t1)
        return {
            "address": addr,
            "name": name,
            "range": report["range"],
            "bucket": report["bucket"],
            "coverage_pct": report["coverage_pct"],
            "segments": report["segments"],
            "sources": report.get("sources") or {},
            "samples": report.get("samples") or 0,
            "counts": report.get("counts") or {},
        }

    @app.get("/api/coverage/overview")
    async def api_coverage_overview(
        hours: float | None = Query(default=2160.0, gt=0, le=26280),
        since_first: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Coverage bars for all sensors over a shared window."""
        now = time.time()
        labels: dict[str, str] = app.state.labels
        if since_first:
            devices = await db.list_devices()
            firsts = [
                float(d["first_seen"])
                for d in devices
                if d.get("first_seen") is not None
            ]
            t0 = min(firsts) if firsts else now - 90 * 86400.0
            t1 = now
            t0 = max(t0, t1 - 26280 * 3600.0)
        else:
            h = float(hours if hours is not None else 2160.0)
            t1 = now
            t0 = t1 - h * 3600.0

        sensors = await db.coverage_overview(t0, t1, labels=labels)
        bucket = "hour" if (t1 - t0) <= 14 * 86400.0 else "day"
        return {
            "range": {"start": t0, "end": t1},
            "bucket": bucket,
            "sensors": sensors,
            "count": len(sensors),
        }

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
        hours: float = Query(24.0, gt=0, le=26280),
        since: float | None = Query(default=None),
        until: float | None = Query(default=None),
    ) -> dict[str, Any]:
        use_abs = since is not None and until is not None
        if use_abs:
            t0 = float(since)
            t1 = float(until)
            if t1 < t0:
                t0, t1 = t1, t0
            span_h = (t1 - t0) / 3600.0
            if span_h <= 0 or span_h > 26280:
                raise HTTPException(
                    status_code=400,
                    detail="since/until window must be between 0 and 26280 hours",
                )
            points = await db.history(address, since=t0, until=t1)
            hours_out = span_h
        else:
            if since is not None or until is not None:
                raise HTTPException(
                    status_code=400,
                    detail="since and until must both be set, or neither",
                )
            t0 = t1 = None
            points = await db.history(address, hours)
            hours_out = hours
        if not points:
            devices = await db.list_devices()
            known = {d["address"].upper() for d in devices}
            if address.upper() not in known:
                raise HTTPException(status_code=404, detail="Unknown device")
        payload: dict[str, Any] = {
            "address": address.upper(),
            "hours": hours_out,
            "points": points,
        }
        if use_abs:
            payload["since"] = t0
            payload["until"] = t1
        return payload

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
        hours: float = Query(168.0, gt=0, le=26280),
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
        hours: float = Query(168.0, gt=0, le=26280),
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
        hours: float = Query(168.0, gt=0, le=26280),
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
            item_source = (item.source or "").strip() or payload.node_id
            # Allow "{peer}/gatt" provenance; never trust empty.
            ok = await db.upsert_reading(
                reading,
                display,
                ts=item.ts,
                source=item_source,
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
