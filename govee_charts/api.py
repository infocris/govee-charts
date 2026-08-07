"""FastAPI app serving the dashboard and JSON API."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.types import Scope

from govee_charts.address import register_mac, resolve_device_address
from govee_charts.apartment import (
    TEMP_COUPLE_CLOSED_C,
    TEMP_COUPLE_OPEN_C,
    infer_temp_coupling,
    ORIENTATIONS,
    compass_from_deg,
    save_overrides,
    solar_bias_c,
    suggest_cooling_airflow,
    ventilation_mode,
)
from govee_charts.backfill import BackfillService
from govee_charts.categories import normalize_door_patch, normalize_patch, taxonomy
from govee_charts.csv_import import MAX_UPLOAD_BYTES, parse_upload, summarize_samples
from govee_charts.db import Database, coverage_from_minute_set
from govee_charts.decode import Reading
from govee_charts.federation import csv_source
from govee_charts.energy import build_energy_summary, estimate_live_ac_watts
from govee_charts.hvac import HvacConfig, hvac_active_bands, is_hvac_active
from govee_charts import mail_inbox
from govee_charts.weather import WeatherService

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
logger = logging.getLogger(__name__)

# HTML must never stick in the browser; static assets are versioned via ?v=.
_HTML_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def static_asset_version() -> str:
    """Version token from static asset mtimes (changes after deploy / edit)."""
    stamp = 0
    for name in ("app.js", "style.css", "index.html"):
        path = STATIC / name
        try:
            stamp = max(stamp, int(path.stat().st_mtime))
        except OSError:
            continue
    return str(stamp or int(time.time()))


def index_html_response() -> HTMLResponse:
    """Serve index.html with no-cache headers and cache-busted asset URLs."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    ver = static_asset_version()
    html = html.replace('href="/static/style.css"', f'href="/static/style.css?v={ver}"')
    html = html.replace('src="/static/app.js"', f'src="/static/app.js?v={ver}"')
    return HTMLResponse(content=html, headers=dict(_HTML_CACHE_HEADERS))


class VersionedStaticFiles(StaticFiles):
    """Static files with short cache; clients bust via ?v= from index.html."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # Versioned URLs (?v=mtime) make short caching safe across restarts.
        response.headers["Cache-Control"] = "public, max-age=60, must-revalidate"
        return response


def peer_browse_url(peer: str, ssl_port: int | None) -> str:
    """Browser UI URL for a federation peer.

    Keep an explicit HTTPS peer port (e.g. :8082). Only rewrite plain HTTP
    peers to HTTPS on *this* node's ssl_port when TLS is enabled locally.
    """
    peer = peer.rstrip("/")
    parsed = urlparse(peer)
    host = parsed.hostname
    if not host:
        return peer
    scheme = (parsed.scheme or "http").lower()
    port = parsed.port

    # Already HTTPS: respect the configured port (do not force local ssl_port).
    if scheme == "https":
        if port:
            return f"https://{host}:{int(port)}"
        return f"https://{host}"

    # HTTP peer used for federation API — offer HTTPS UI when we have ssl_port.
    if ssl_port:
        return f"https://{host}:{int(ssl_port)}"
    return peer


def _git_output(cmd: list[str]) -> tuple[int, str]:
    """Run a git command in the project root; return (returncode, combined output)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        return 127, "git not found on this host"
    except subprocess.TimeoutExpired:
        return 124, "git command timed out"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return int(proc.returncode), out


def run_git_pull() -> dict[str, Any]:
    """Fast-forward pull from the configured remote (safe for local edits)."""
    if not (ROOT / ".git").is_dir():
        return {
            "ok": False,
            "message": "Not a git repository",
            "output": "",
            "before": None,
            "after": None,
            "changed": False,
        }

    rc, before = _git_output(["git", "rev-parse", "--short", "HEAD"])
    if rc != 0:
        return {
            "ok": False,
            "message": "Could not read HEAD",
            "output": before,
            "before": None,
            "after": None,
            "changed": False,
        }
    before = before.strip() or None

    rc, output = _git_output(["git", "pull", "--ff-only"])
    rc2, after = _git_output(["git", "rev-parse", "--short", "HEAD"])
    after = (after.strip() or None) if rc2 == 0 else before
    changed = bool(before and after and before != after)

    if rc != 0:
        detail = output or "git pull --ff-only failed"
        return {
            "ok": False,
            "message": detail.splitlines()[-1][:240],
            "output": output,
            "before": before,
            "after": after,
            "changed": False,
        }

    if changed:
        message = f"Updated {before} → {after}. Restart UI/workers to load code changes."
    else:
        message = f"Already up to date ({after or before})."

    return {
        "ok": True,
        "message": message,
        "output": output,
        "before": before,
        "after": after,
        "changed": changed,
    }


async def probe_peer_health(peer: str, *, ssl_port: int | None) -> dict[str, Any]:
    """Server-side /api/health probe (avoids browser mixed-content blocks)."""
    peer = peer.rstrip("/")
    browse = peer_browse_url(peer, ssl_port)
    label = peer
    try:
        parsed = urlparse(peer)
        if parsed.hostname:
            label = parsed.hostname
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=2.5, verify=False) as client:
            res = await client.get(f"{peer}/api/health")
            if res.status_code >= 400:
                return {
                    "url": peer,
                    "browse_url": browse,
                    "node_id": label,
                    "online": False,
                }
            data = res.json() if res.content else {}
            node_id = str((data or {}).get("node_id") or label).strip() or label
            return {
                "url": peer,
                "browse_url": browse,
                "node_id": node_id,
                "online": True,
            }
    except Exception:
        return {
            "url": peer,
            "browse_url": browse,
            "node_id": label,
            "online": False,
        }


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
    height_cm: float | None = None
    room: str | None = None
    label: str | None = None

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
    enabled: bool | None = None
    gatt_enabled: bool | None = None

    model_config = {"extra": "forbid"}


class MailInboxSet(BaseModel):
    """Create a new disposable inbox, or register an existing address."""

    address: str | None = None

    model_config = {"extra": "forbid"}


_BACKFILL_MODELS = ("h5075", "h5072", "h5179")


def device_display_name(
    device: dict[str, Any],
    labels: dict[str, str] | None = None,
) -> str:
    """UI label > config.toml [labels] > BLE advertisement name > address."""
    addr = str(device.get("address") or "").upper()
    custom = str(device.get("label") or "").strip()
    if custom:
        return custom
    if labels and addr in labels:
        return labels[addr]
    return str(device.get("name") or addr)


def enrich_device(
    device: dict[str, Any],
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Copy device row and set ``name`` to the resolved display name."""
    out = dict(device)
    out["ble_name"] = device.get("name")
    out["name"] = device_display_name(device, labels)
    return out


async def _backfill_devices_from_db(
    db: Database,
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Eligible sensors + persisted flags (works without a live worker)."""
    flags_map = await db.list_backfill_flags()
    rows: list[dict[str, Any]] = []
    for device in await db.list_devices(include_stats=False):
        addr = str(device.get("address") or "").upper()
        if not addr:
            continue
        model = str(device.get("model") or "").lower()
        if model and model not in _BACKFILL_MODELS:
            continue
        flags = flags_map.get(addr) or {}
        rows.append(
            {
                "address": addr,
                "name": device_display_name(device, labels),
                "model": model or None,
                "enabled": bool(flags.get("enabled")),
                "gatt_enabled": bool(flags.get("gatt_enabled", True)),
                "rssi": None,
                "local_best": False,
                "queued_jobs": 0,
                "phase": None,
            }
        )
    rows.sort(key=lambda e: (str(e["name"]).lower(), e["address"]))
    return rows


def _backfill_disabled_snapshot(
    devices: list[dict[str, Any]],
    *,
    recent: list[Any],
    recent_jobs: list[Any],
) -> dict[str, Any]:
    return {
        "enabled": False,
        "paused": False,
        "worker": "disabled",
        "current": None,
        "queue": [],
        "devices": devices,
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


async def _hvac_live_snapshot(
    db: Database,
    hvac_cfg: HvacConfig,
    *,
    include_energy: bool = True,
) -> dict[str, Any]:
    """Latest climate + power + estimated AC watts for UI overlays."""
    climate = await db.latest_hvac(
        entity_id=hvac_cfg.climate_entity or None
    )
    power = await db.latest_power(entity_id=hvac_cfg.power_entity or None)
    active = is_hvac_active(str((climate or {}).get("state") or ""))
    home_watts = None
    if power and power.get("watts") is not None:
        try:
            home_watts = float(power["watts"])
        except (TypeError, ValueError):
            home_watts = None
    ac_watts = await estimate_live_ac_watts(
        db,
        home_watts=home_watts,
        active=active,
        power_entity=hvac_cfg.power_entity,
        climate_entity=hvac_cfg.climate_entity,
        idle_floor_w=hvac_cfg.ac_idle_floor_w,
    )
    energy = None
    if include_energy:
        try:
            energy = await build_energy_summary(
                db,
                energy_entity=hvac_cfg.energy_entity,
                water_heater_entity=hvac_cfg.water_heater_energy_entity,
                power_entity=hvac_cfg.power_entity,
                climate_entity=hvac_cfg.climate_entity,
                water_heater_indoor_fraction=hvac_cfg.water_heater_indoor_fraction,
                other_loads_indoor_fraction=hvac_cfg.other_loads_indoor_fraction,
                ac_cop=hvac_cfg.ac_cop,
                ac_idle_floor_w=hvac_cfg.ac_idle_floor_w,
                timezone=hvac_cfg.timezone,
                include_heat_gain=False,
            )
        except Exception as exc:
            logger.warning("Energy summary failed: %s", exc)
            energy = {"error": str(exc)}
    return {
        "enabled": True,
        "room": hvac_cfg.room,
        "climate": climate,
        "power": power,
        "active": active,
        "ac_watts": ac_watts,
        "energy": energy,
    }


def create_app(
    db: Database,
    *,
    labels: dict[str, str] | None = None,
    federation_token: str | None = None,
    node_id: str = "local",
    peers: list[str] | None = None,
    suffix_map: dict[str, str] | None = None,
    weather: WeatherService | None = None,
    on_restart_ui: Callable[[], None] | None = None,
    on_restart_workers: Callable[[], tuple[bool, str]] | None = None,
    backfill: BackfillService | None = None,
    ssl_port: int | None = None,
    hvac: HvacConfig | None = None,
    scanner_enabled: bool = True,
    ble_alert_stale_after: float = 300.0,
) -> FastAPI:
    app = FastAPI(title="Govee Charts", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.labels = {k.upper(): v for k, v in (labels or {}).items()}
    app.state.suffix_map = suffix_map or {}
    app.state.federation_token = federation_token or None
    app.state.node_id = node_id
    app.state.peers = [p.rstrip("/") for p in (peers or []) if p.strip()]
    app.state.weather = weather
    app.state.on_restart_ui = on_restart_ui
    app.state.on_restart_workers = on_restart_workers
    app.state.backfill = backfill
    app.state.restart_ui_scheduled = False
    app.state.git_pull_lock = asyncio.Lock()
    app.state.mail_fetch_lock = asyncio.Lock()
    app.state.ssl_port = int(ssl_port) if ssl_port else None
    app.state.hvac = hvac or HvacConfig()
    app.state.scanner_enabled = bool(scanner_enabled)
    app.state.ble_alert_stale_after = max(0.0, float(ble_alert_stale_after))

    @app.get("/")
    async def index() -> HTMLResponse:
        return index_html_response()

    @app.get("/overview")
    @app.get("/compare")
    @app.get("/facades")
    @app.get("/map")
    @app.get("/network")
    @app.get("/coverage")
    @app.get("/backfill")
    async def index_views() -> HTMLResponse:
        """Client-side routes for direct URL navigation."""
        return index_html_response()

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        hb = await db.get_runtime_heartbeat("workers")
        ble_hb = await db.get_runtime_heartbeat("ble")
        pause_hb = await db.get_runtime_heartbeat("ble_pause")
        now = time.time()
        age = (now - hb) if hb is not None else None
        workers_available = bool(age is not None and age <= 15.0)
        stale_after = float(app.state.ble_alert_stale_after)
        scanner_enabled = bool(app.state.scanner_enabled)
        ble_age = (now - ble_hb) if ble_hb is not None else None
        pause_age = (now - pause_hb) if pause_hb is not None else None
        paused_for_gatt = bool(pause_age is not None and pause_age <= 20.0)
        if not scanner_enabled or stale_after <= 0:
            ble_ok = True
        elif paused_for_gatt:
            ble_ok = True
        elif ble_age is None:
            # Scanner enabled but never reported — treat as not ok once workers
            # are clearly up (avoids a flash on cold start).
            ble_ok = not workers_available
        else:
            ble_ok = ble_age <= stale_after
        return {
            "ok": True,
            "node_id": app.state.node_id,
            "systemd": bool(os.environ.get("INVOCATION_ID")),
            "asset_version": static_asset_version(),
            "workers_last_seen": hb,
            "workers_age_s": round(age, 2) if age is not None else None,
            "workers_available": workers_available,
            "ble": {
                "enabled": scanner_enabled,
                "paused_for_gatt": paused_for_gatt,
                "last_adv_ts": ble_hb,
                "age_s": round(ble_age, 2) if ble_age is not None else None,
                "stale_after_s": stale_after,
                "ok": ble_ok,
            },
        }

    @app.get("/api/backfill")
    async def api_backfill(
        recent_limit: int = Query(10, ge=1, le=500),
        job_limit: int = Query(10, ge=1, le=200),
    ) -> dict[str, Any]:
        """Live history backfill queue snapshot + recent recovered readings."""
        recent = await db.recent_gatt_readings(limit=recent_limit)
        recent_jobs = await db.recent_backfill_jobs(limit=job_limit)
        service: BackfillService | None = app.state.backfill
        if service is None:
            devices = await _backfill_devices_from_db(db, app.state.labels)
            return _backfill_disabled_snapshot(
                devices, recent=recent, recent_jobs=recent_jobs
            )
        snap = await service.snapshot()
        snap["recent"] = recent
        snap["recent_jobs"] = recent_jobs
        return snap

    @app.post("/api/backfill/pause")
    async def api_backfill_pause(
        recent_limit: int = Query(10, ge=1, le=500),
        job_limit: int = Query(10, ge=1, le=200),
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
        recent_limit: int = Query(10, ge=1, le=500),
        job_limit: int = Query(10, ge=1, le=200),
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
        recent_limit: int = Query(10, ge=1, le=500),
        job_limit: int = Query(10, ge=1, le=200),
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
        recent_limit: int = Query(10, ge=1, le=500),
        job_limit: int = Query(10, ge=1, le=200),
    ) -> dict[str, Any]:
        """Enable/disable backfill and/or GATT for one sensor (always persisted)."""
        if payload.enabled is None and payload.gatt_enabled is None:
            raise HTTPException(
                status_code=400,
                detail="enabled or gatt_enabled required",
            )
        address = payload.address.strip().upper()
        service: BackfillService | None = app.state.backfill
        if service is not None:
            try:
                result = await service.set_device_flags(
                    address,
                    enabled=payload.enabled,
                    gatt_enabled=payload.gatt_enabled,
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

        device = await db.get_device(address)
        if device is None:
            raise HTTPException(status_code=404, detail=f"Unknown device {address}")
        model = str(device.get("model") or "").lower()
        if model and model not in _BACKFILL_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Model {model or '?'} does not support GATT history",
            )
        try:
            flags = await db.set_backfill_flags(
                address,
                enabled=payload.enabled,
                gatt_enabled=payload.gatt_enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload.enabled is False:
            await db.cancel_open_backfill_jobs(address)
        devices = await _backfill_devices_from_db(db, app.state.labels)
        snap = _backfill_disabled_snapshot(
            devices,
            recent=await db.recent_gatt_readings(limit=recent_limit),
            recent_jobs=await db.recent_backfill_jobs(limit=job_limit),
        )
        snap["device_update"] = {
            "address": address,
            "name": device_display_name(device, app.state.labels),
            "enabled": flags["enabled"],
            "gatt_enabled": flags["gatt_enabled"],
            "cancelled": 0,
            "enqueued": 0,
        }
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

    def _form_bool(raw: str | None, default: bool = False) -> bool:
        if raw is None:
            return default
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    _OVERWRITE_EPS_TEMP = 0.05
    _OVERWRITE_EPS_HUM = 0.05
    _OVERWRITE_SAMPLE_CAP = 20
    # Nearby different-ts readings that would sawtooth the chart if both kept.
    _ZIGZAG_WINDOW_S = 60.0
    _ZIGZAG_EPS_TEMP = 1.0
    _ZIGZAG_EPS_HUM = 5.0
    _ZIGZAG_SAMPLE_CAP = 20

    def _compare_overwrite_diffs(
        samples: list[tuple[float, float, float]],
        existing_values: dict[int, tuple[float, float, float]],
    ) -> dict[str, Any]:
        """Diff file samples vs DB for minutes that already exist."""
        by_minute: dict[int, tuple[float, float, float]] = {}
        for ts, temp, hum in samples:
            minute = int(float(ts) // 60)
            by_minute[minute] = (float(ts), float(temp), float(hum))

        would_overwrite = 0
        temp_max = 0.0
        hum_max = 0.0
        sample_rows: list[dict[str, Any]] = []
        for minute, (ts, temp, hum) in sorted(by_minute.items()):
            old = existing_values.get(minute)
            if old is None:
                continue
            _old_ts, old_temp, old_hum = old
            d_temp = abs(old_temp - temp)
            d_hum = abs(old_hum - hum)
            if d_temp <= _OVERWRITE_EPS_TEMP and d_hum <= _OVERWRITE_EPS_HUM:
                continue
            would_overwrite += 1
            if d_temp > temp_max:
                temp_max = d_temp
            if d_hum > hum_max:
                hum_max = d_hum
            if len(sample_rows) < _OVERWRITE_SAMPLE_CAP:
                sample_rows.append(
                    {
                        "ts": ts,
                        "old_temp": round(old_temp, 2),
                        "new_temp": round(temp, 2),
                        "old_hum": round(old_hum, 2),
                        "new_hum": round(hum, 2),
                    }
                )
        return {
            "would_overwrite": would_overwrite,
            "overwrite_temp_max": round(temp_max, 2),
            "overwrite_hum_max": round(hum_max, 2),
            "overwrite_samples": sample_rows,
        }

    def _compare_zigzag(
        samples: list[tuple[float, float, float]],
        existing_rows: list[tuple[float, float, float, str | None]],
        *,
        overwrite: bool,
    ) -> dict[str, Any]:
        """
        Detect CSV vs nearby DB readings at a *different* timestamp (same minute).

        Insert-only keeps both → chart zigzag. Overwrite updates the DB minute
        in place, so those conflicts are marked resolved.
        """
        by_minute_db: dict[int, list[tuple[float, float, float, str | None]]] = {}
        for ts, temp, hum, source in existing_rows:
            by_minute_db.setdefault(int(ts // 60), []).append(
                (ts, temp, hum, source)
            )

        by_csv: dict[int, tuple[float, float, float]] = {}
        for ts, temp, hum in samples:
            minute = int(float(ts) // 60)
            by_csv[minute] = (float(ts), float(temp), float(hum))

        zigzag = 0
        temp_max = 0.0
        hum_max = 0.0
        sample_rows: list[dict[str, Any]] = []
        for minute, (ts, temp, hum) in sorted(by_csv.items()):
            neighbors: list[tuple[float, float, float, str | None]] = []
            for m in (minute - 1, minute, minute + 1):
                neighbors.extend(by_minute_db.get(m) or [])
            best: tuple[float, float, float, float, float, float, str | None] | None = None
            # (score, d_temp, d_hum, db_ts, db_temp, db_hum, source)
            for db_ts, db_temp, db_hum, source in neighbors:
                gap = abs(db_ts - ts)
                if gap <= 0.5:
                    continue  # same timestamp → overwrite path
                if gap > _ZIGZAG_WINDOW_S:
                    continue
                d_temp = abs(db_temp - temp)
                d_hum = abs(db_hum - hum)
                if d_temp < _ZIGZAG_EPS_TEMP and d_hum < _ZIGZAG_EPS_HUM:
                    continue
                score = d_temp + d_hum / 10.0
                if best is None or score > best[0]:
                    best = (score, d_temp, d_hum, db_ts, db_temp, db_hum, source)
            if best is None:
                continue
            _score, d_temp, d_hum, db_ts, db_temp, db_hum, source = best
            zigzag += 1
            if d_temp > temp_max:
                temp_max = d_temp
            if d_hum > hum_max:
                hum_max = d_hum
            if len(sample_rows) < _ZIGZAG_SAMPLE_CAP:
                sample_rows.append(
                    {
                        "ts": ts,
                        "db_ts": db_ts,
                        "csv_temp": round(temp, 2),
                        "db_temp": round(db_temp, 2),
                        "csv_hum": round(hum, 2),
                        "db_hum": round(db_hum, 2),
                        "source": source or "—",
                    }
                )

        remaining = 0 if overwrite else zigzag
        return {
            "zigzag_count": zigzag,
            "zigzag_remaining": remaining,
            "zigzag_resolved_by_overwrite": zigzag if overwrite else 0,
            "zigzag_temp_max": round(temp_max, 2),
            "zigzag_hum_max": round(hum_max, 2),
            "zigzag_samples": sample_rows,
            "zigzag_window_s": _ZIGZAG_WINDOW_S,
            "zigzag_eps_temp": _ZIGZAG_EPS_TEMP,
            "zigzag_eps_hum": _ZIGZAG_EPS_HUM,
        }

    @app.post("/api/backfill/import/preview")
    async def api_backfill_import_preview(
        address: str = Form(...),
        file: UploadFile = File(...),
        overwrite: str = Form("false"),
    ) -> dict[str, Any]:
        """Parse a Govee CSV/ZIP and compare against existing readings (no write)."""
        overwrite_flag = _form_bool(overwrite)
        device = await _resolve_import_device(address)
        addr = str(device["address"]).upper()
        labels: dict[str, str] = app.state.labels
        name = device_display_name(device, labels)
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
        empty_overwrite = {
            "would_overwrite": 0,
            "overwrite_temp_max": 0.0,
            "overwrite_hum_max": 0.0,
            "overwrite_samples": [],
        }
        empty_zigzag = {
            "zigzag_count": 0,
            "zigzag_remaining": 0,
            "zigzag_resolved_by_overwrite": 0,
            "zigzag_temp_max": 0.0,
            "zigzag_hum_max": 0.0,
            "zigzag_samples": [],
            "zigzag_window_s": _ZIGZAG_WINDOW_S,
            "zigzag_eps_temp": _ZIGZAG_EPS_TEMP,
            "zigzag_eps_hum": _ZIGZAG_EPS_HUM,
        }

        if not samples:
            return {
                "address": addr,
                "name": name,
                "overwrite": overwrite_flag,
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
                    **empty_overwrite,
                    **empty_zigzag,
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
        existing_values = await db.reading_values_by_minute(addr, start, end_excl)
        overwrite_meta = _compare_overwrite_diffs(samples, existing_values)
        # Pad window so neighbors just outside the file range are visible.
        existing_rows = await db.reading_rows_in_range(
            addr, start - _ZIGZAG_WINDOW_S, end_excl + _ZIGZAG_WINDOW_S
        )
        zigzag_meta = _compare_zigzag(
            samples, existing_rows, overwrite=overwrite_flag
        )

        file_cov = coverage_from_minute_set(file_minutes, start, end_excl)
        db_cov = coverage_from_minute_set(existing_minutes, start, end_excl)

        return {
            "address": addr,
            "name": name,
            "overwrite": overwrite_flag,
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
                **overwrite_meta,
                **zigzag_meta,
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
        overwrite: str = Form("false"),
    ) -> dict[str, Any]:
        """Ingest a previously previewed Govee CSV/ZIP into readings."""
        overwrite_flag = _form_bool(overwrite)
        device = await _resolve_import_device(address)
        addr = str(device["address"]).upper()
        labels: dict[str, str] = app.state.labels
        name = device_display_name(device, labels)
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
        result = await db.insert_gatt_readings(
            address=addr,
            display_name=name,
            model=model,
            samples=samples,
            battery=int(battery),
            rssi=None,
            source=source,
            overwrite=overwrite_flag,
            eps_temp=_OVERWRITE_EPS_TEMP,
            eps_hum=_OVERWRITE_EPS_HUM,
        )
        inserted = int(result.get("inserted") or 0)
        overwritten = int(result.get("overwritten") or 0)
        summary = summarize_samples(samples)
        unique_minutes = len({int(float(ts) // 60) for ts, _, _ in samples})
        skipped = max(0, unique_minutes - inserted - (overwritten if overwrite_flag else 0))
        logger.info(
            "CSV import %s → %s: inserted=%d overwritten=%d skipped=%d "
            "bad_rows=%d overwrite=%s files=%s",
            source,
            name,
            inserted,
            overwritten,
            skipped,
            bad_rows,
            overwrite_flag,
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
            "overwritten": overwritten,
            "skipped": skipped,
            "overwrite": overwrite_flag,
            "range": summary["range"],
        }

    @app.get("/api/mail/inbox")
    async def api_mail_inbox_get() -> dict[str, Any]:
        """Current disposable inbox used for Govee CSV email export."""
        state = mail_inbox.load_state()
        if not state:
            return {"address": None, "provider": mail_inbox.PROVIDER, "configured": False}
        return {**state, "configured": True}

    @app.post("/api/mail/inbox")
    async def api_mail_inbox_set(body: MailInboxSet = MailInboxSet()) -> dict[str, Any]:
        """Create a new disposable inbox, or save an existing address."""
        existing = (body.address or "").strip()
        try:
            if existing:
                if "@" not in existing:
                    raise HTTPException(status_code=400, detail="Invalid email address")
                meta = await mail_inbox.get_inbox(existing)
                state = {
                    "address": meta["address"],
                    "created_at": meta.get("created_at"),
                    "expires_in": None,
                    "provider": mail_inbox.PROVIDER,
                }
            else:
                state = await mail_inbox.create_inbox()
        except mail_inbox.MailInboxError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail=f"Inbox provider unreachable: {exc}"
            ) from exc
        mail_inbox.save_state(state)
        logger.info("Disposable mail inbox set to %s", state["address"])
        return {**state, "configured": True}

    @app.delete("/api/mail/inbox")
    async def api_mail_inbox_clear() -> dict[str, Any]:
        mail_inbox.clear_state()
        return {"ok": True, "address": None, "configured": False}

    @app.post("/api/mail/fetch")
    async def api_mail_fetch() -> dict[str, Any]:
        """Poll disposable inbox and return CSV/ZIP attachments (base64)."""
        state = mail_inbox.load_state()
        if not state or not state.get("address"):
            raise HTTPException(
                status_code=400,
                detail="No inbox configured — create or set an address first",
            )
        lock: asyncio.Lock = app.state.mail_fetch_lock
        if lock.locked():
            raise HTTPException(status_code=409, detail="Mail fetch already in progress")
        async with lock:
            try:
                result = await mail_inbox.fetch_csv_attachments(str(state["address"]))
            except mail_inbox.MailInboxError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=503, detail=f"Inbox provider unreachable: {exc}"
                ) from exc
        # Drop oversized payloads early (same limit as upload import).
        kept_messages: list[dict[str, Any]] = []
        codes_all: list[str] = []
        codes_seen: set[str] = set()
        for msg in result.get("messages") or []:
            files = []
            for att in msg.get("attachments") or []:
                size = int(att.get("size") or 0)
                if size > MAX_UPLOAD_BYTES:
                    continue
                files.append(att)
            kept = {**msg, "attachments": files}
            kept_messages.append(kept)
            for code in kept.get("verification_codes") or []:
                code_s = str(code)
                if code_s and code_s not in codes_seen:
                    codes_seen.add(code_s)
                    codes_all.append(code_s)
        attachment_count = sum(len(m.get("attachments") or []) for m in kept_messages)
        return {
            "address": result.get("address") or state["address"],
            "provider": result.get("provider") or mail_inbox.PROVIDER,
            "messages": kept_messages,
            "attachment_count": attachment_count,
            "verification_codes": codes_all,
        }

    @app.post("/api/git/pull")
    async def api_git_pull() -> dict[str, Any]:
        """Pull latest commits with --ff-only (does not restart services)."""
        lock: asyncio.Lock = app.state.git_pull_lock
        if lock.locked():
            raise HTTPException(status_code=409, detail="Git pull already in progress")
        async with lock:
            logger.warning("Git pull requested from UI")
            result = await asyncio.to_thread(run_git_pull)
        if not result.get("ok"):
            raise HTTPException(
                status_code=503,
                detail=str(result.get("message") or "git pull failed"),
            )
        return result

    @app.post("/api/restart")
    async def api_restart(
        target: str = Query(default="ui", pattern="^(ui|workers)$")
    ) -> dict[str, Any]:
        under_systemd = bool(os.environ.get("INVOCATION_ID"))
        if target == "workers":
            callback_workers = app.state.on_restart_workers
            if callback_workers is None:
                raise HTTPException(
                    status_code=503,
                    detail="Workers restart not available in this runtime",
                )
            ok, message = callback_workers()
            if not ok:
                raise HTTPException(status_code=503, detail=message)
            return {
                "ok": True,
                "target": "workers",
                "scheduled": True,
                "systemd": under_systemd,
                "message": message,
            }

        if app.state.restart_ui_scheduled:
            return {
                "ok": True,
                "target": "ui",
                "scheduled": True,
                "systemd": under_systemd,
                "message": "UI restart already scheduled",
            }

        callback = app.state.on_restart_ui
        if callback is None:
            raise HTTPException(status_code=503, detail="UI restart not available")

        app.state.restart_ui_scheduled = True

        async def _delayed() -> None:
            await asyncio.sleep(0.15)
            logger.warning("UI restart requested from UI — stopping process")
            callback()

        asyncio.create_task(_delayed())
        return {
            "ok": True,
            "target": "ui",
            "scheduled": True,
            "systemd": under_systemd,
            "message": (
                "Restarting UI via systemd…"
                if under_systemd
                else "Process exiting — restart manually if not under systemd"
            ),
        }

    @app.get("/api/federation")
    async def api_federation() -> dict[str, Any]:
        """Local node id + peers with server-side health probes."""
        ssl_port = app.state.ssl_port
        peers_cfg: list[str] = list(app.state.peers or [])
        probed = await asyncio.gather(
            *(probe_peer_health(url, ssl_port=ssl_port) for url in peers_cfg)
        )
        return {
            "node_id": app.state.node_id,
            "ssl_port": ssl_port,
            "peers": list(probed),
        }

    @app.get("/api/devices")
    async def api_devices() -> list[dict[str, Any]]:
        labels: dict[str, str] = app.state.labels
        return [
            enrich_device(d, labels) for d in await db.list_devices()
        ]

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
        name = device_display_name(device, labels)

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
        recent = await db.recent_readings(addr, limit=10)
        recent_jobs = await db.recent_backfill_jobs_for_address(addr, limit=10)
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
            "recent": recent,
            "recent_jobs": recent_jobs,
        }

    @app.get("/api/history/aggregate")
    async def api_history_aggregate(
        address: str = Query(..., min_length=1),
        bucket: str = Query("day", pattern="^(day|week|month)$"),
        hours: float | None = Query(default=2160.0, gt=0, le=26280),
        since: float | None = Query(default=None),
        until: float | None = Query(default=None),
        since_first: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Per-sensor temperature/humidity aggregates by day, week, or month."""
        addr = address.strip().upper()
        device = await db.get_device(addr)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        labels: dict[str, str] = app.state.labels
        name = device_display_name(device, labels)

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

        try:
            rows = await db.history_aggregate(addr, t0, t1, bucket=bucket)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "address": addr,
            "name": name,
            "bucket": bucket,
            "range": {"start": t0, "end": t1},
            "rows": rows,
            "count": len(rows),
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
        hours: float = Query(24.0, gt=0, le=384),
        future_hours: float | None = Query(default=None, gt=0, le=384),
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
    ) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            return {"enabled": False, "rooms": [], "orientations": []}
        layout = weather_svc.apartment
        payload = layout.summary()
        past_h = float(hours)
        fut_h = float(future_hours) if future_hours is not None else past_h
        payload["hours"] = past_h
        payload["future_hours"] = fut_h

        # Attach sensors grouped by room category
        labels: dict[str, str] = app.state.labels
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
                    "name": device_display_name(d, labels),
                    "zone": d.get("zone"),
                    "height": d.get("height"),
                    "height_cm": d.get("height_cm"),
                    "temperature_c": d.get("temperature_c"),
                    "humidity": d.get("humidity"),
                }
            )
        for room in payload["rooms"]:
            room["sensors"] = by_room.get(room["id"], [])

        def _exterior_comparative(
            sensors: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            """Exterior sensors for façade comparison — prefer height=high."""
            exterior = [
                s
                for s in sensors
                if str(s.get("zone") or "").lower() == "exterior"
            ]
            high = [
                s
                for s in exterior
                if str(s.get("height") or "").lower() == "high"
            ]
            return high or exterior

        solar: dict[str, Any] = {"available": False}
        outdoor_summary: dict[str, Any] = {"available": False}
        forecast = None
        if weather_svc.enabled:
            try:
                forecast = await weather_svc.fetch_forecast(
                    latitude=latitude,
                    longitude=longitude,
                    horizon_hours=fut_h,
                )
            except Exception as exc:
                solar = {"available": False, "error": str(exc)}
                forecast = None

        if forecast and forecast.get("enabled") and forecast.get("outdoor"):
            now = time.time()
            since = now - past_h * 3600.0
            until = now + fut_h * 3600.0
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
                    "hours": past_h,
                    "future_hours": fut_h,
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
                        "hours": past_h,
                        "future_hours": fut_h,
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

            # Projections (future) for rooms with sensors — needs outdoor forecast.
            addresses: list[str] = []
            addr_by_room: dict[str, str] = {}
            for room in payload["rooms"]:
                for s in room.get("sensors") or []:
                    zone = (s.get("zone") or "").strip().lower()
                    if zone == "exterior":
                        continue
                    if s.get("address"):
                        addr = str(s["address"]).upper()
                        addresses.append(addr)
                        addr_by_room[room["id"]] = addr
                        break

            if addresses:
                try:
                    proj_resp = await weather_svc.build_response(
                        db,
                        hours=past_h,
                        future_hours=fut_h,
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
                            "hours": past_h,
                            "future_hours": fut_h,
                            "points": proj.get("points") or [],
                        }
                except Exception as exc:
                    logger.warning("Apartment room projections failed: %s", exc)

        payload["solar"] = solar
        payload["outdoor"] = outdoor_summary

        # Indoor history always (façade charts + network thermal coupling).
        # hist_temp_* = window extremes; live temp_min/max are set below from
        # current interior sensor readings.
        # façade comparative history uses exterior height=high when available.
        for room in payload["rooms"]:
            room.setdefault("room_history", None)
            room.setdefault("room_projection", None)
            room.setdefault("facade_history", None)
            room["hist_temp_max"] = None
            room["hist_temp_min"] = None
            addr = None
            for s in room.get("sensors") or []:
                zone = (s.get("zone") or "").strip().lower()
                if zone == "exterior":
                    continue
                if s.get("address"):
                    addr = str(s["address"]).upper()
                    break
            if addr:
                try:
                    hist = await db.history(addr, past_h)
                except Exception:
                    hist = []
                if hist:
                    points = [
                        {
                            "ts": float(p["ts"]),
                            "temperature_c": round(float(p["temperature_c"]), 2),
                            "humidity": p.get("humidity"),
                        }
                        for p in hist
                        if p.get("temperature_c") is not None
                    ]
                    if points:
                        temps = [float(p["temperature_c"]) for p in points]
                        room["room_history"] = {"address": addr, "points": points}
                        room["hist_temp_max"] = round(max(temps), 2)
                        room["hist_temp_min"] = round(min(temps), 2)

            facade_sensors = _exterior_comparative(room.get("sensors") or [])
            facade_addr = None
            for s in facade_sensors:
                if s.get("address"):
                    facade_addr = str(s["address"]).upper()
                    break
            if facade_addr:
                try:
                    fhist = await db.history(facade_addr, past_h)
                except Exception:
                    fhist = []
                if fhist:
                    fpoints = [
                        {
                            "ts": float(p["ts"]),
                            "temperature_c": round(float(p["temperature_c"]), 2),
                            "humidity": p.get("humidity"),
                        }
                        for p in fhist
                        if p.get("temperature_c") is not None
                    ]
                    if fpoints:
                        room["facade_history"] = {
                            "address": facade_addr,
                            "name": next(
                                (
                                    str(s.get("name") or facade_addr)
                                    for s in facade_sensors
                                    if str(s.get("address") or "").upper()
                                    == facade_addr
                                ),
                                facade_addr,
                            ),
                            "height": "high"
                            if any(
                                str(s.get("height") or "").lower() == "high"
                                for s in facade_sensors
                            )
                            else None,
                            "points": fpoints,
                        }

        # Network graph extras: contacts + opening state on edges / façades.
        try:
            door_sensors = await db.list_door_sensors()
        except Exception as exc:
            logger.warning("Apartment door list failed: %s", exc)
            door_sensors = []
        contacts_by_room: dict[str, list[dict[str, Any]]] = {
            r["id"]: [] for r in payload["rooms"]
        }
        for contact in door_sensors:
            rid = str(contact.get("room") or "").strip().lower()
            if rid not in contacts_by_room:
                continue
            contacts_by_room[rid].append(
                {
                    "sensor_id": contact.get("sensor_id"),
                    "name": contact.get("name") or contact.get("sensor_id"),
                    "kind": contact.get("kind") or "door",
                    "state": contact.get("state"),
                    "ts": contact.get("ts"),
                }
            )
        for room in payload["rooms"]:
            rid = room["id"]
            contacts = contacts_by_room.get(rid, [])
            room["contacts"] = contacts
            sensors = room.get("sensors") or []
            interior = [
                s
                for s in sensors
                if str(s.get("zone") or "").lower() != "exterior"
            ]
            exterior = _exterior_comparative(sensors)
            live_temps: list[float] = []
            for s in interior:
                try:
                    if s.get("temperature_c") is not None:
                        live_temps.append(float(s["temperature_c"]))
                except (TypeError, ValueError):
                    continue
            if live_temps:
                room["temp_min"] = round(min(live_temps), 2)
                room["temp_max"] = round(max(live_temps), 2)
                room["temp_c"] = round(sum(live_temps) / len(live_temps), 2)
            else:
                room["temp_min"] = None
                room["temp_max"] = None
                room["temp_c"] = None
            facade_temps: list[float] = []
            for s in exterior:
                try:
                    if s.get("temperature_c") is not None:
                        facade_temps.append(float(s["temperature_c"]))
                except (TypeError, ValueError):
                    continue
            if facade_temps:
                room["facade_temp_min"] = round(min(facade_temps), 2)
                room["facade_temp_max"] = round(max(facade_temps), 2)
                room["facade_temp_c"] = round(
                    sum(facade_temps) / len(facade_temps), 2
                )
                room["facade_sensor_names"] = [
                    str(s.get("name") or s.get("address") or "")
                    for s in exterior
                    if s.get("temperature_c") is not None
                ]
            else:
                room["facade_sensor_names"] = []
                proj = room.get("facade_projection") or {}
                proj_now = proj.get("temp_now")
                if proj_now is not None:
                    try:
                        t = round(float(proj_now), 2)
                    except (TypeError, ValueError):
                        t = None
                    room["facade_temp_min"] = t
                    room["facade_temp_max"] = t
                    room["facade_temp_c"] = t
                else:
                    room["facade_temp_min"] = None
                    room["facade_temp_max"] = None
                    room["facade_temp_c"] = None
            hums: list[float] = []
            for s in interior:
                try:
                    if s.get("humidity") is not None:
                        hums.append(float(s["humidity"]))
                except (TypeError, ValueError):
                    continue
            room["humidity"] = round(sum(hums) / len(hums), 1) if hums else None
            windows = [
                c for c in contacts if str(c.get("kind") or "") == "window"
            ]
            if any(str(c.get("state") or "").lower() == "open" for c in windows):
                room["window_state"] = "open"
            elif windows and all(
                str(c.get("state") or "").lower() == "closed" for c in windows
            ):
                room["window_state"] = "closed"
            elif windows:
                room["window_state"] = "unknown"
            else:
                room["window_state"] = None
            # Coupling fallback when the history window has no samples.
            if room.get("hist_temp_max") is None and room.get("temp_max") is not None:
                room["hist_temp_max"] = room["temp_max"]
            if room.get("hist_temp_min") is None and room.get("temp_min") is not None:
                room["hist_temp_min"] = room["temp_min"]

        degree: dict[str, int] = {r["id"]: 0 for r in payload["rooms"]}
        for edge in payload.get("edges") or []:
            a = str(edge.get("a") or "")
            b = str(edge.get("b") or "")
            if a in degree:
                degree[a] += 1
            if b in degree:
                degree[b] += 1
        hub_id = max(degree, key=degree.get) if degree else None

        for edge in payload.get("edges") or []:
            kind = str(edge.get("kind") or "door")
            a = str(edge.get("a") or "")
            b = str(edge.get("b") or "")
            related: list[dict[str, Any]] = []
            if kind in ("door", "wall_partial"):
                allowed_kinds = (
                    ("door",) if kind == "door" else ("door", "other")
                )
                for rid in (a, b):
                    for c in contacts_by_room.get(rid, []):
                        if str(c.get("kind") or "door") in allowed_kinds:
                            related.append({**c, "room": rid})
                # Hub rooms (e.g. corridor) often host shared contacts such as
                # the entrance door. Only attribute a contact to a hub↔leaf
                # edge when it belongs to the leaf room; otherwise leave empty
                # so thermal coupling can infer the opening.
                if hub_id and hub_id in (a, b) and kind == "door":
                    leaf = b if a == hub_id else a
                    related = [c for c in related if c.get("room") == leaf]
            edge["contacts"] = related
            edge["temp_delta_max_c"] = None
            edge["opening_source"] = None
            if kind == "wall":
                edge["opening"] = "sealed"
                edge["opening_source"] = "layout"
                continue
            if related:
                if any(str(c.get("state") or "").lower() == "open" for c in related):
                    edge["opening"] = "open"
                elif all(
                    str(c.get("state") or "").lower() == "closed" for c in related
                ):
                    edge["opening"] = "closed"
                else:
                    edge["opening"] = "unknown"
                edge["opening_source"] = "contact"
                continue
            # No door contact: infer air sharing from close 24h maxima.
            room_a = next(
                (r for r in payload["rooms"] if r["id"] == a), None
            )
            room_b = next(
                (r for r in payload["rooms"] if r["id"] == b), None
            )
            couple = infer_temp_coupling(
                None if room_a is None else room_a.get("hist_temp_max"),
                None if room_b is None else room_b.get("hist_temp_max"),
            )
            edge["opening"] = couple["opening"]
            edge["opening_source"] = couple["source"]
            edge["temp_delta_max_c"] = couple.get("delta_c")
            edge["temp_couple"] = {
                "open_threshold_c": couple.get("open_threshold_c"),
                "closed_threshold_c": couple.get("closed_threshold_c"),
            }

        payload["temp_couple"] = {
            "open_threshold_c": TEMP_COUPLE_OPEN_C,
            "closed_threshold_c": TEMP_COUPLE_CLOSED_C,
            "hours": past_h,
        }

        outdoor = payload.get("outdoor") or {}
        solar = payload.get("solar") or {}
        outdoor_temp = outdoor.get("temp_now")
        if outdoor_temp is None:
            outdoor_temp = solar.get("temperature_c")
        payload["airflow"] = suggest_cooling_airflow(
            payload.get("rooms") or [],
            payload.get("edges") or [],
            outdoor_temp_c=(
                float(outdoor_temp) if outdoor_temp is not None else None
            ),
            wind_speed_ms=(
                outdoor.get("wind_speed_ms")
                if outdoor.get("wind_speed_ms") is not None
                else solar.get("wind_speed_ms")
            ),
            wind_direction_deg=(
                outdoor.get("wind_direction_deg")
                if outdoor.get("wind_direction_deg") is not None
                else solar.get("wind_direction_deg")
            ),
        )

        hvac_cfg: HvacConfig = app.state.hvac
        if hvac_cfg.enabled:
            payload["hvac"] = await _hvac_live_snapshot(
                db, hvac_cfg, include_energy=False
            )
        else:
            payload["hvac"] = {"enabled": False, "active": False, "room": hvac_cfg.room}

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
                height_cm=provided["height_cm"] if "height_cm" in provided else ...,
                room=provided["room"] if "room" in provided else ...,
                label=provided["label"] if "label" in provided else ...,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = await db.update_device_categories(address, **patch)
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        return enrich_device(updated, app.state.labels)

    @app.get("/api/history")
    async def api_history(
        address: str = Query(..., min_length=1),
        hours: float = Query(24.0, gt=0, le=26280),
        since: float | None = Query(default=None),
        until: float | None = Query(default=None),
        max_points: int = Query(5000, ge=100, le=50000),
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
            points = await db.history(
                address, since=t0, until=t1, max_points=max_points
            )
            hours_out = span_h
        else:
            if since is not None or until is not None:
                raise HTTPException(
                    status_code=400,
                    detail="since and until must both be set, or neither",
                )
            t0 = t1 = None
            points = await db.history(address, hours, max_points=max_points)
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
        """Latest climate state + latest power sample + energy/heat summary."""
        hvac_cfg: HvacConfig = app.state.hvac
        if not hvac_cfg.enabled:
            return {
                "enabled": False,
                "climate": None,
                "power": None,
                "active": False,
                "ac_watts": None,
                "energy": None,
                "room": hvac_cfg.room,
            }
        return await _hvac_live_snapshot(db, hvac_cfg)

    @app.get("/api/energy/summary")
    async def api_energy_summary(
        hours: float | None = Query(default=None, gt=0, le=26280),
    ) -> dict[str, Any]:
        """Electrical + indoor-heat estimate (today, or last ``hours``)."""
        hvac_cfg: HvacConfig = app.state.hvac
        if not hvac_cfg.enabled:
            return {"enabled": False}
        summary = await build_energy_summary(
            db,
            energy_entity=hvac_cfg.energy_entity,
            water_heater_entity=hvac_cfg.water_heater_energy_entity,
            power_entity=hvac_cfg.power_entity,
            climate_entity=hvac_cfg.climate_entity,
            water_heater_indoor_fraction=hvac_cfg.water_heater_indoor_fraction,
            other_loads_indoor_fraction=hvac_cfg.other_loads_indoor_fraction,
            ac_cop=hvac_cfg.ac_cop,
            ac_idle_floor_w=hvac_cfg.ac_idle_floor_w,
            timezone=hvac_cfg.timezone,
            hours=hours,
        )
        summary["enabled"] = True
        return summary

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
        hours: float = Query(24.0, gt=0, le=384),
        future_hours: float | None = Query(default=None, gt=0, le=384),
        address: list[str] | None = Query(default=None),
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
    ) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None:
            return {
                "enabled": False,
                "hours": hours,
                "future_hours": future_hours if future_hours is not None else hours,
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
            future_hours=future_hours,
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
            existing = await db.get_device(address)
            display = device_display_name(
                {
                    **(existing or {}),
                    "address": address,
                    "name": ble_name,
                },
                labels,
            )
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

    app.mount("/static", VersionedStaticFiles(directory=STATIC), name="static")
    return app
