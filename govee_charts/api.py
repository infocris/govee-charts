"""FastAPI app serving the dashboard and JSON API."""

from __future__ import annotations

import asyncio
import json
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
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.types import Scope

from govee_charts.address import is_ble_mac, register_mac, resolve_device_address
from govee_charts.apartment import (
    TEMP_COUPLE_CLOSED_C,
    TEMP_COUPLE_OPEN_C,
    ApartmentLayout,
    infer_temp_coupling,
    ORIENTATIONS,
    compass_from_deg,
    save_overrides,
    solar_bias_c,
    suggest_cooling_airflow,
    suggest_cooling_airflow_v2,
    ventilation_mode,
)
from govee_charts.floorplan import (
    active_plan_meta,
    apply_plan_to_layout,
    compile_plan,
    duplicate_plan,
    empty_plan,
    find_plan,
    known_room_options,
    load_plans,
    plan_summary,
    save_plans,
    validate_plan_update,
)
from govee_charts.backfill import BackfillService
from govee_charts.categories import normalize_door_patch, normalize_patch, taxonomy
from govee_charts.connections import (
    OUTDOOR,
    connection_id_for_rooms,
    effective_opening_from_sensors,
    is_outdoor_connection,
    layout_connection_specs,
    outdoor_connection_id,
    parse_connection_id,
)
from govee_charts.csv_import import MAX_UPLOAD_BYTES, parse_upload, summarize_samples
from govee_charts.cursor_chat import (
    apartment_snapshot_dict,
    build_prompt,
    compact_apartment_snapshot,
    normalize_banner,
    normalize_cursor_chat_config,
    probe_agent_status,
    resolve_agent_bin,
    resolve_workspace,
    stream_agent_chat,
)
from govee_charts.db import (
    Database,
    WORKERS_HEARTBEAT_MAX_AGE_S,
    coverage_from_minute_set,
    is_db_locked,
)
from govee_charts.decode import Reading
from govee_charts.federation import csv_source
from govee_charts.energy import build_energy_summary, estimate_live_ac_watts
from govee_charts.map_chat_store import MapChatStore
from govee_charts.tts import (
    HOME_TTS_VOICE_ID,
    default_voice_for_lang,
    list_edge_voices,
    speak_via_home,
    synthesize,
)
from govee_charts.presence import PresenceConfig, PresenceService
from govee_charts.ha_th import HaThConfig, map_stale_after_s
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
    for name in (
        "app.js",
        "style.css",
        "index.html",
        "widget.js",
        "widget.html",
        "i18n.js",
        "plan-editor.js",
        "sw.js",
    ):
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
    html = html.replace('src="/static/i18n.js"', f'src="/static/i18n.js?v={ver}"')
    html = html.replace(
        'src="/static/plan-editor.js"', f'src="/static/plan-editor.js?v={ver}"'
    )
    return HTMLResponse(content=html, headers=dict(_HTML_CACHE_HEADERS))


def service_worker_response() -> Response:
    """Serve the notification service worker at site root (Safari scope)."""
    path = STATIC / "sw.js"
    body = path.read_bytes() if path.is_file() else b""
    return Response(
        content=body,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


def widget_html_response() -> HTMLResponse:
    """Serve the embeddable widget page with cache-busted script URL."""
    html = (STATIC / "widget.html").read_text(encoding="utf-8")
    ver = static_asset_version()
    html = html.replace(
        'src="/static/widget.js"', f'src="/static/widget.js?v={ver}"'
    )
    return HTMLResponse(content=html, headers=dict(_HTML_CACHE_HEADERS))


def _layout_hub_id(rooms: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str | None:
    degree: dict[str, int] = {
        str(r.get("id") or ""): 0 for r in rooms if r.get("id")
    }
    for edge in edges or []:
        a = str(edge.get("a") or "")
        b = str(edge.get("b") or "")
        if a in degree:
            degree[a] += 1
        if b in degree:
            degree[b] += 1
    return max(degree, key=degree.get) if degree else None


def _room_label_map(rooms: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {OUTDOOR: "Outdoor"}
    for room in rooms or []:
        rid = str(room.get("id") or "").strip().lower()
        if not rid:
            continue
        out[rid] = str(room.get("label") or rid)
    return out


async def _ensure_layout_connections(db: Database, layout: Any) -> tuple[str | None, list[dict[str, str]]]:
    """Sync layout → connections rows; migrate legacy room/kind once."""
    summary = layout.summary() if hasattr(layout, "summary") else layout
    rooms = list(summary.get("rooms") or [])
    edges = list(summary.get("edges") or [])
    specs = layout_connection_specs(rooms, edges)
    await db.sync_connections_from_layout(specs)
    hub_id = _layout_hub_id(rooms, edges)
    passable = [s for s in specs if s.get("kind") != "outdoor"]
    try:
        n = await db.migrate_connections_from_door_rooms(
            passable_specs=passable,
            hub_id=hub_id,
        )
        if n:
            logger.info("Migrated %d door sensor(s) onto connections", n)
    except Exception:
        logger.exception("Connection migration from door rooms failed")
    return hub_id, specs


def _enrich_connection_payload(
    row: dict[str, Any],
    *,
    linked_ids: list[str],
    sensors_by_id: dict[str, dict[str, Any]],
    labels: dict[str, str],
) -> dict[str, Any]:
    cid = str(row.get("connection_id") or "")
    room_a = str(row.get("room_a") or "")
    room_b = str(row.get("room_b") or "")
    linked = [sensors_by_id[sid] for sid in linked_ids if sid in sensors_by_id]
    forced = str(row.get("forced_state") or "").strip().lower()
    if forced not in ("open", "closed"):
        forced = ""
    reported, reported_ts = effective_opening_from_sensors(linked)
    if forced:
        state = forced
        ts = row.get("forced_at") or reported_ts
        source = "manual"
        is_forced = True
    else:
        state = reported
        ts = reported_ts
        source = "contact" if linked else None
        is_forced = False
    return {
        "id": cid,
        "connection_id": cid,
        "room_a": room_a,
        "room_b": room_b,
        "kind": row.get("kind") or "door",
        "label_a": labels.get(room_a, room_a),
        "label_b": labels.get(room_b, room_b),
        "sensors": linked,
        "sensor_ids": linked_ids,
        "state": state,
        "reported_state": reported,
        "forced": is_forced,
        "forced_state": forced or None,
        "ts": ts,
        "source": source,
        "is_outdoor": is_outdoor_connection(cid),
    }


async def _build_connections_response(db: Database, layout: Any) -> dict[str, Any]:
    hub_id, _specs = await _ensure_layout_connections(db, layout)
    summary = layout.summary()
    labels = _room_label_map(list(summary.get("rooms") or []))
    door_sensors = await db.list_door_sensors()
    sensors_by_id = {
        str(s.get("sensor_id") or ""): s
        for s in door_sensors
        if s.get("sensor_id")
    }
    link_map = await db.list_connection_sensor_map()
    sensor_to_conn = {
        sid: cid for cid, sids in link_map.items() for sid in sids
    }
    rows = await db.list_connection_rows()
    connections = [
        _enrich_connection_payload(
            row,
            linked_ids=list(link_map.get(str(row.get("connection_id") or ""), [])),
            sensors_by_id=sensors_by_id,
            labels=labels,
        )
        for row in rows
    ]
    # Stable UI order: inter-room doors first, then outdoor, by label.
    def _sort_key(c: dict[str, Any]) -> tuple:
        return (
            1 if c.get("is_outdoor") else 0,
            str(c.get("label_a") or ""),
            str(c.get("label_b") or ""),
        )

    connections.sort(key=_sort_key)
    sensors_out = []
    for s in door_sensors:
        sid = str(s.get("sensor_id") or "")
        item = dict(s)
        item["connection_id"] = sensor_to_conn.get(sid)
        sensors_out.append(item)
    return {
        "connections": connections,
        "sensors": sensors_out,
        "hub_id": hub_id,
        "count": len(connections),
    }


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


def _git_output(cmd: list[str], *, timeout: float = 120.0) -> tuple[int, str]:
    """Run a git command in the project root; return (returncode, combined output)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, "git not found on this host"
    except subprocess.TimeoutExpired:
        return 124, "git command timed out"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return int(proc.returncode), out


def run_git_status(*, fetch: bool = True) -> dict[str, Any]:
    """Compare local HEAD to its upstream (optional fetch first)."""
    if not (ROOT / ".git").is_dir():
        return {
            "ok": True,
            "git": False,
            "update_available": False,
            "behind": 0,
            "ahead": 0,
            "local": None,
            "remote": None,
            "upstream": None,
            "message": "Not a git repository",
        }

    fetch_output = ""
    if fetch:
        rc, fetch_output = _git_output(
            ["git", "fetch", "--quiet", "--prune"], timeout=90.0
        )
        if rc not in (0,):
            # Still report local vs last-known upstream when fetch fails.
            logger.warning("git fetch failed (%s): %s", rc, fetch_output[:200])

    rc, local = _git_output(["git", "rev-parse", "--short", "HEAD"])
    if rc != 0:
        return {
            "ok": False,
            "git": True,
            "update_available": False,
            "behind": 0,
            "ahead": 0,
            "local": None,
            "remote": None,
            "upstream": None,
            "message": local or "Could not read HEAD",
            "fetch_output": fetch_output,
        }
    local = local.strip() or None

    rc, upstream = _git_output(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
    )
    if rc != 0:
        return {
            "ok": True,
            "git": True,
            "update_available": False,
            "behind": 0,
            "ahead": 0,
            "local": local,
            "remote": None,
            "upstream": None,
            "message": "No upstream branch configured",
            "fetch_output": fetch_output,
        }
    upstream = upstream.strip() or None

    rc, remote = _git_output(["git", "rev-parse", "--short", "@{u}"])
    remote = (remote.strip() or None) if rc == 0 else None

    rc_b, behind_s = _git_output(["git", "rev-list", "--count", "HEAD..@{u}"])
    rc_a, ahead_s = _git_output(["git", "rev-list", "--count", "@{u}..HEAD"])
    try:
        behind = int(behind_s.strip()) if rc_b == 0 else 0
    except ValueError:
        behind = 0
    try:
        ahead = int(ahead_s.strip()) if rc_a == 0 else 0
    except ValueError:
        ahead = 0

    update_available = behind > 0
    if update_available:
        message = f"{behind} commit(s) available ({local} → {remote or upstream})"
    elif ahead > 0:
        message = f"Local is {ahead} commit(s) ahead of {upstream}"
    else:
        message = f"Up to date ({local})"

    return {
        "ok": True,
        "git": True,
        "update_available": update_available,
        "behind": behind,
        "ahead": ahead,
        "local": local,
        "remote": remote,
        "upstream": upstream,
        "message": message,
        "fetch_output": fetch_output,
    }


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


class DeviceCreateBody(BaseModel):
    address: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default="unknown", max_length=32)
    name: str | None = Field(default=None, max_length=80)
    label: str | None = None
    zone: str | None = None
    height: str | None = None
    height_cm: float | None = None
    room: str | None = None

    model_config = {"extra": "forbid"}


class PlacementCreateBody(BaseModel):
    effective_from: float | None = None
    label: str | None = None
    zone: str | None = None
    height: str | None = None
    height_cm: float | None = None
    room: str | None = None

    model_config = {"extra": "forbid"}


class PlacementPatch(BaseModel):
    label: str | None = None
    zone: str | None = None
    height: str | None = None
    height_cm: float | None = None
    room: str | None = None
    valid_from: float | None = None
    valid_until: float | None = None

    model_config = {"extra": "forbid"}


class DeviceMetaIngest(BaseModel):
    """Federation payload to sync device label / placement fields."""

    node_id: str = Field(default="peer", min_length=1, max_length=64)
    address: str = Field(min_length=1)
    name: str | None = None
    label: str | None = None
    zone: str | None = None
    height: str | None = None
    height_cm: float | None = None
    room: str | None = None

    model_config = {"extra": "forbid"}


class DoorPatch(BaseModel):
    room: str | None = None
    kind: str | None = None
    name: str | None = None

    model_config = {"extra": "forbid"}


class DoorForceBody(BaseModel):
    """Manual open/closed until the next live MQTT/HA transition."""

    state: str = Field(..., min_length=1)

    model_config = {"extra": "forbid"}


class ConnectionSensorsBody(BaseModel):
    """Replace the set of contact sensors linked to a connection."""

    sensor_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ConnectionForceBody(BaseModel):
    """Manual open/closed override for a room connection."""

    state: str = Field(..., min_length=1)

    model_config = {"extra": "forbid"}


class TtsBody(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str | None = None
    lang: str | None = None

    model_config = {"extra": "forbid"}


class MapChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    banner: dict[str, Any] | None = None
    advice_model: str | None = Field(default=None, max_length=8)

    model_config = {"extra": "forbid"}


class MapChatSessionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)

    model_config = {"extra": "forbid"}


class FacadePatch(BaseModel):
    exterior: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PlanCreate(BaseModel):
    name: str = Field(default="Untitled", max_length=120)
    mode: str = Field(..., min_length=1, max_length=32)

    model_config = {"extra": "forbid"}


class PlanDuplicate(BaseModel):
    name: str | None = Field(default=None, max_length=120)

    model_config = {"extra": "forbid"}


class BackfillDevicePatch(BaseModel):
    address: str = Field(min_length=1)
    enabled: bool | None = None
    gatt_enabled: bool | None = None

    model_config = {"extra": "forbid"}


class CompactionPatch(BaseModel):
    policy: str = Field(..., min_length=1, max_length=32)

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


def _validate_device_address(address: str) -> str:
    addr = address.strip().upper()
    if is_ble_mac(addr):
        return addr
    if addr.startswith("HA:") and len(addr) > 3:
        return addr
    raise ValueError(
        f"Invalid device address {address!r}; expected BLE MAC or HA:… id"
    )


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
    presence: PresenceService | None = None,
    scanner_enabled: bool = True,
    ble_alert_stale_after: float = 300.0,
    ha_th: HaThConfig | None = None,
    tts: dict[str, Any] | None = None,
    cursor_chat: dict[str, Any] | None = None,
    map_chat_store: MapChatStore | None = None,
    apartment_plans: dict[str, Any] | None = None,
    apartment_fallback: dict[str, Any] | None = None,
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
    app.state.map_chat_lock = asyncio.Lock()
    app.state.ssl_port = int(ssl_port) if ssl_port else None
    app.state.hvac = hvac or HvacConfig()
    app.state.presence = presence
    app.state.scanner_enabled = bool(scanner_enabled)
    app.state.ble_alert_stale_after = max(0.0, float(ble_alert_stale_after))
    app.state.ha_th = ha_th or HaThConfig()
    tts_cfg = dict(tts or {})
    home_url = str(tts_cfg.get("home_url") or "").strip().rstrip("/")
    return_audio = tts_cfg.get("return_audio")
    if return_audio is None:
        return_audio = False
    app.state.tts = {
        "home_url": home_url,
        "app": str(tts_cfg.get("app") or "govee-charts").strip() or "govee-charts",
        "channel": str(tts_cfg.get("channel") or "alerts").strip() or "alerts",
        "return_audio": bool(return_audio),
    }
    app.state.cursor_chat = normalize_cursor_chat_config(cursor_chat)
    app.state.map_chat_store = map_chat_store
    app.state.apartment_plans = (
        apartment_plans if isinstance(apartment_plans, dict) else load_plans()
    )
    if apartment_fallback is not None:
        app.state.apartment_fallback = apartment_fallback
    elif weather is not None and getattr(weather, "apartment", None) is not None:
        app.state.apartment_fallback = weather.apartment.summary()
    else:
        app.state.apartment_fallback = None

    def _plans_store() -> dict[str, Any]:
        store = getattr(app.state, "apartment_plans", None)
        if not isinstance(store, dict):
            store = load_plans()
            app.state.apartment_plans = store
        return store

    def _persist_plans(store: dict[str, Any]) -> None:
        save_plans(store)
        app.state.apartment_plans = store

    def _restore_fallback_layout(layout: ApartmentLayout) -> None:
        fb = getattr(app.state, "apartment_fallback", None)
        if not isinstance(fb, dict) or not fb.get("rooms"):
            return
        raw = {
            "enabled": layout.enabled,
            "ceiling_m": layout.ceiling_m,
            "door_height_m": layout.door_height_m,
            "area_m2": fb.get("area_m2", layout.area_m2),
            "floor": layout.floor,
            "floors_total": layout.floors_total,
            "timezone": layout.timezone,
            "rooms": fb.get("rooms") or [],
            "edges": fb.get("edges") or [],
        }
        restored = ApartmentLayout.from_dict(raw)
        layout.rooms = restored.rooms
        layout.edges = restored.edges
        layout.area_m2 = restored.area_m2
        layout._rebuild_matrices()

    @app.get("/")
    async def index() -> HTMLResponse:
        return index_html_response()

    @app.get("/sw.js")
    async def service_worker() -> Response:
        """Root-scoped SW so Safari standalone can use showNotification()."""
        return service_worker_response()

    @app.get("/overview")
    @app.get("/compare")
    @app.get("/facades")
    @app.get("/map")
    @app.get("/network")
    @app.get("/coverage")
    @app.get("/backfill")
    @app.get("/system")
    @app.get("/settings")
    async def index_views() -> HTMLResponse:
        """Client-side routes for direct URL navigation."""
        return index_html_response()

    @app.get("/widget")
    async def widget_view() -> HTMLResponse:
        """Standalone embeddable chart (iframe / link share)."""
        return widget_html_response()

    async def _health_heartbeat(component: str) -> float | None:
        try:
            return await db.get_runtime_heartbeat(component)
        except Exception as exc:
            if is_db_locked(exc):
                logger.warning("Health heartbeat read blocked (%s): %s", component, exc)
                return None
            raise

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        hb_sql = await _health_heartbeat("workers")
        hb_file = db.read_workers_heartbeat_file()
        hb_candidates = [t for t in (hb_sql, hb_file) if t is not None]
        hb = max(hb_candidates) if hb_candidates else None
        ble_hb = await _health_heartbeat("ble")
        pause_hb = await _health_heartbeat("ble_pause")
        now = time.time()
        age = (now - hb) if hb is not None else None
        stale_after = float(app.state.ble_alert_stale_after)
        scanner_enabled = bool(app.state.scanner_enabled)
        ble_age = (now - ble_hb) if ble_hb is not None else None
        pause_age = (now - pause_hb) if pause_hb is not None else None
        paused_for_gatt = bool(pause_age is not None and pause_age <= 20.0)
        workers_available = bool(
            age is not None and age <= WORKERS_HEARTBEAT_MAX_AGE_S
        )
        # BLE ads are written by the same process; a SQLite lock can stall the
        # workers row without stopping the scanner.
        if (
            not workers_available
            and scanner_enabled
            and ble_age is not None
            and ble_age <= WORKERS_HEARTBEAT_MAX_AGE_S
        ):
            workers_available = True
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

    @app.get("/api/tts/voices")
    async def api_tts_voices(
        lang: str = Query("fr", min_length=1, max_length=16),
    ) -> dict[str, Any]:
        """edge-tts voices filtered by language prefix (browser-tts skill)."""
        try:
            voices = await list_edge_voices(lang)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("TTS voices failed")
            raise HTTPException(
                status_code=502, detail=f"tts voices failed: {exc}"
            ) from exc
        prefix = (lang or "fr").strip().lower() or "fr"
        tts_cfg: dict[str, Any] = app.state.tts or {}
        home_enabled = bool(tts_cfg.get("home_url"))
        return {
            "ok": True,
            "lang": prefix,
            "default_voice": default_voice_for_lang(prefix),
            "voices": voices,
            "home_tts": {
                "enabled": home_enabled,
                "id": HOME_TTS_VOICE_ID,
                "app": tts_cfg.get("app") or "govee-charts",
                "channel": tts_cfg.get("channel") or "alerts",
            },
        }

    @app.post("/api/tts")
    async def api_tts(body: TtsBody) -> dict[str, Any]:
        """Synthesize speech via edge-tts, or play on Home TTS speakers."""
        voice_id = (body.voice or "").strip()
        if voice_id == HOME_TTS_VOICE_ID:
            tts_cfg: dict[str, Any] = app.state.tts or {}
            home_url = str(tts_cfg.get("home_url") or "").strip()
            if not home_url:
                raise HTTPException(
                    status_code=400, detail="home-tts is not configured"
                )
            lang = (body.lang or "fr").strip() or "fr"
            try:
                return await speak_via_home(
                    home_url,
                    body.text,
                    lang=lang,
                    app=str(tts_cfg.get("app") or "govee-charts"),
                    channel=str(tts_cfg.get("channel") or "alerts"),
                    return_audio=bool(tts_cfg.get("return_audio", False)),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("home-tts speak failed")
                raise HTTPException(
                    status_code=502, detail=f"home-tts failed: {exc}"
                ) from exc
        try:
            return await synthesize(body.text, body.voice)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("TTS synthesize failed")
            raise HTTPException(
                status_code=502, detail=f"tts failed: {exc}"
            ) from exc

    @app.get("/api/map-chat/status")
    async def api_map_chat_status() -> dict[str, Any]:
        """Whether Map Cursor chat can run (config + local agent CLI)."""
        cfg: dict[str, Any] = app.state.cursor_chat or {}
        enabled = bool(cfg.get("enabled"))
        agent_bin = resolve_agent_bin(str(cfg.get("agent_bin") or ""))
        workspace = resolve_workspace(str(cfg.get("workspace") or ""))
        store: MapChatStore | None = app.state.map_chat_store
        out: dict[str, Any] = {
            "enabled": enabled,
            "mode": cfg.get("mode") or "ask",
            "model": cfg.get("model") or "auto",
            "workspace": workspace,
            "agent_bin": agent_bin,
            "agent_found": bool(agent_bin),
            "history_enabled": store is not None,
            "logged_in": False,
            "ready": False,
            "detail": None,
        }
        if not enabled:
            out["detail"] = "cursor_chat.enabled is false"
            return out
        if not agent_bin:
            out["detail"] = (
                "Cursor agent CLI not found "
                "(set cursor_chat.agent_bin or install agent on PATH)"
            )
            return out
        status = await probe_agent_status(agent_bin)
        out["logged_in"] = bool(status.get("logged_in"))
        out["detail"] = status.get("detail")
        out["ready"] = bool(status.get("logged_in"))
        return out

    @app.get("/api/map-chat/sessions")
    async def api_map_chat_sessions(
        limit: int = Query(40, ge=1, le=100),
    ) -> dict[str, Any]:
        """List recent Map chat sessions for the session picker."""
        store: MapChatStore | None = app.state.map_chat_store
        if store is None:
            raise HTTPException(status_code=503, detail="Map chat history unavailable")
        sessions = await store.list_sessions(limit=limit)
        return {"ok": True, "sessions": sessions}

    @app.patch("/api/map-chat/sessions/{session_id}")
    async def api_map_chat_rename_session(
        session_id: str, body: MapChatSessionPatch
    ) -> dict[str, Any]:
        """Set or clear a custom title for one Map chat session."""
        store: MapChatStore | None = app.state.map_chat_store
        if store is None:
            raise HTTPException(status_code=503, detail="Map chat history unavailable")
        sid = (session_id or "").strip()
        if not sid:
            raise HTTPException(status_code=400, detail="empty session_id")
        session = await store.rename_session(sid, body.title)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True, "session": session}

    @app.get("/api/map-chat/history")
    async def api_map_chat_history(
        session_id: str | None = Query(default=None, max_length=128),
        limit: int = Query(50, ge=1, le=200),
        include_snapshot: bool = Query(False),
    ) -> dict[str, Any]:
        """List persisted Map chat exchanges (separate map_chat.db)."""
        store: MapChatStore | None = app.state.map_chat_store
        if store is None:
            raise HTTPException(status_code=503, detail="Map chat history unavailable")
        exchanges = await store.list_exchanges(
            session_id=session_id,
            limit=limit,
            include_snapshot=include_snapshot,
        )
        return {
            "ok": True,
            "session_id": (session_id or "").strip() or None,
            "exchanges": exchanges,
        }

    @app.get("/api/map-chat/history/{exchange_id}")
    async def api_map_chat_history_one(exchange_id: int) -> dict[str, Any]:
        store: MapChatStore | None = app.state.map_chat_store
        if store is None:
            raise HTTPException(status_code=503, detail="Map chat history unavailable")
        item = await store.get_exchange(exchange_id)
        if item is None:
            raise HTTPException(status_code=404, detail="exchange not found")
        return {"ok": True, "exchange": item}

    @app.post("/api/map-chat")
    async def api_map_chat(body: MapChatBody) -> StreamingResponse:
        """Ask the local Cursor agent about the live apartment map (SSE)."""
        cfg: dict[str, Any] = app.state.cursor_chat or {}
        if not cfg.get("enabled"):
            raise HTTPException(status_code=503, detail="Map chat is disabled")
        agent_bin = resolve_agent_bin(str(cfg.get("agent_bin") or ""))
        if not agent_bin:
            raise HTTPException(
                status_code=503,
                detail="Cursor agent CLI not found (set cursor_chat.agent_bin)",
            )
        lock: asyncio.Lock = app.state.map_chat_lock
        if lock.locked():
            raise HTTPException(
                status_code=503, detail="Map chat is busy; try again shortly"
            )

        message = (body.message or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="empty message")

        banner = normalize_banner(body.banner)
        advice_model = (
            "v2" if str(body.advice_model or "").strip().lower() == "v2" else "v1"
        )

        # Fresh apartment snapshot (same builder as GET /api/apartment),
        # with enough future outdoor hours for the chat forecast slice.
        try:
            apartment = await api_apartment(
                hours=24.0,
                future_hours=12.0,
                latitude=None,
                longitude=None,
            )
        except Exception as exc:
            logger.exception("map-chat apartment snapshot failed")
            raise HTTPException(
                status_code=502, detail=f"apartment snapshot failed: {exc}"
            ) from exc
        snapshot_obj = apartment_snapshot_dict(
            apartment, advice_model=advice_model
        )
        snapshot = compact_apartment_snapshot(
            apartment, advice_model=advice_model
        )
        prompt = build_prompt(
            message, snapshot, banner=banner, advice_model=advice_model
        )
        workspace = resolve_workspace(str(cfg.get("workspace") or ""))
        model = str(cfg.get("model") or "auto")
        mode = str(cfg.get("mode") or "ask")
        timeout_s = float(cfg.get("timeout_s") or 180.0)
        session_id = (body.session_id or "").strip() or None
        store: MapChatStore | None = app.state.map_chat_store

        async def event_gen():
            assistant_text = ""
            out_session = session_id
            err_msg: str | None = None
            async with lock:
                async for ev in stream_agent_chat(
                    agent_bin=agent_bin,
                    prompt=prompt,
                    workspace=workspace,
                    model=model,
                    mode=mode,
                    session_id=session_id,
                    timeout_s=timeout_s,
                ):
                    if ev.get("session_id"):
                        out_session = str(ev["session_id"])
                    if ev.get("type") == "delta" and ev.get("text"):
                        if ev.get("replace"):
                            assistant_text = str(ev["text"])
                        else:
                            assistant_text += str(ev["text"])
                    elif ev.get("type") == "done" and ev.get("text"):
                        assistant_text = str(ev["text"]) or assistant_text
                    elif ev.get("type") == "error":
                        err_msg = str(ev.get("message") or "agent error")
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

            if store is not None:
                try:
                    saved = await store.add_exchange(
                        session_id=str(out_session or "unknown"),
                        user_message=message,
                        assistant_message=assistant_text or None,
                        error=err_msg,
                        model=model,
                        snapshot=snapshot_obj,
                        banner=banner,
                    )
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "saved",
                                "id": saved.get("id"),
                                "session_id": saved.get("session_id"),
                                "created_at": saved.get("created_at"),
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                except Exception:
                    logger.exception("map-chat history persist failed")

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/system")
    async def api_system() -> dict[str, Any]:
        """Storage history, table inventory, and readings provenance summary."""
        node_id = str(app.state.node_id or "")
        inventory = await db.inventory_stats(node_id)
        daily = await db.list_db_size_daily(limit=365)
        current = {
            "day": Database.utc_day(),
            "db_bytes": inventory["db_file"]["db_bytes"],
            "wal_bytes": inventory["db_file"]["wal_bytes"],
            "total_bytes": inventory["db_file"]["total_bytes"],
            "readings_count": next(
                (
                    t["rows"]
                    for t in inventory["tables"]
                    if t["name"] == "readings"
                ),
                None,
            ),
            "recorded_at": time.time(),
        }
        devices = await db.list_devices(include_stats=True)
        labels: dict[str, str] = app.state.labels
        device_opts = [
            {
                "address": d["address"],
                "name": device_display_name(d, labels),
                "sample_count": int(d.get("sample_count") or 0),
            }
            for d in devices
        ]
        device_opts.sort(
            key=lambda d: (str(d["name"]).lower(), str(d["address"]))
        )
        sensor_storage = await db.sensor_storage_stats(labels=labels)
        return {
            "node_id": node_id,
            "storage": {"current": current, "daily": daily},
            "inventory": inventory,
            "devices": device_opts,
            "sensor_storage": sensor_storage,
        }

    @app.get("/api/system/device-sources")
    async def api_system_device_sources(
        address: list[str] | None = Query(default=None),
        addresses: str | None = Query(
            default=None,
            description="Comma-separated addresses (alternative to repeated address=)",
        ),
        days: float = Query(30, ge=0.04, le=366),
        grain: str = Query("day", pattern="^(day|hour)$"),
    ) -> dict[str, Any]:
        """Sample counts by provenance for one or more devices.

        ``grain=day`` buckets by UTC day; ``grain=hour`` by UTC hour.
        Pass multiple ``address`` query params and/or a comma-separated ``addresses``.
        """
        addrs: list[str] = []
        for raw in address or []:
            part = str(raw).strip()
            if part:
                addrs.append(part.upper())
        if addresses:
            for part in str(addresses).split(","):
                p = part.strip()
                if p:
                    addrs.append(p.upper())
        # Preserve order, unique.
        seen: set[str] = set()
        uniq: list[str] = []
        for a in addrs:
            if a not in seen:
                seen.add(a)
                uniq.append(a)
        if not uniq:
            raise HTTPException(status_code=400, detail="At least one address required")
        if len(uniq) > 40:
            raise HTTPException(status_code=400, detail="Too many addresses (max 40)")

        labels: dict[str, str] = app.state.labels
        devices_out: list[dict[str, str]] = []
        for addr in uniq:
            device = await db.get_device(addr)
            if device is None:
                raise HTTPException(status_code=404, detail=f"Unknown device {addr}")
            devices_out.append(
                {
                    "address": addr,
                    "name": device_display_name(device, labels),
                }
            )

        grain_l = grain.strip().lower()
        # Hour grain: keep the window practical (max 14 days of hourly points).
        lookback_days = float(days)
        if grain_l == "hour" and lookback_days > 14:
            lookback_days = 14.0
        end_ts = time.time()
        start_ts = end_ts - lookback_days * 86400.0
        node_id = str(app.state.node_id or "")

        async def _one(addr: str, name: str) -> dict[str, Any]:
            series = await db.device_source_series(
                [addr], start_ts, end_ts, node_id, grain=grain_l
            )
            return {"address": addr, "name": name, "series": series}

        devices_series = await asyncio.gather(
            *[_one(d["address"], d["name"]) for d in devices_out]
        )
        return {
            "addresses": uniq,
            "devices": list(devices_series),
            "node_id": node_id,
            "days": lookback_days,
            "grain": grain_l,
            "start_ts": start_ts,
            "end_ts": end_ts,
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

    @app.get("/api/git/status")
    async def api_git_status(
        fetch: bool = Query(default=True),
    ) -> dict[str, Any]:
        """Report whether the tracked branch has remote commits to pull."""
        lock: asyncio.Lock = app.state.git_pull_lock
        if lock.locked():
            return {
                "ok": True,
                "git": True,
                "busy": True,
                "update_available": False,
                "behind": 0,
                "ahead": 0,
                "message": "Git operation in progress",
            }
        async with lock:
            return await asyncio.to_thread(run_git_status, fetch=bool(fetch))

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
    async def api_devices(
        include_archived: bool = Query(default=False),
    ) -> list[dict[str, Any]]:
        labels: dict[str, str] = app.state.labels
        rows = await db.list_devices(include_archived=include_archived)
        devices = [enrich_device(d, labels) for d in rows]
        trends = await db.temperature_trends(
            [str(d.get("address") or "") for d in devices]
        )
        for d in devices:
            trend = trends.get(str(d.get("address") or "").upper())
            if trend:
                d["temp_trend"] = trend.get("dir")
                d["temp_delta_c"] = trend.get("delta_c")
                d["temp_rate_c_h"] = trend.get("rate_c_h")
        return devices

    @app.post("/api/devices")
    async def api_create_device(body: DeviceCreateBody) -> dict[str, Any]:
        try:
            addr = _validate_device_address(body.address)
            patch = normalize_patch(
                zone=body.zone,
                height=body.height,
                height_cm=body.height_cm,
                room=body.room,
                label=body.label,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        model = (body.model or "unknown").strip() or "unknown"
        device = await db.create_device(
            addr,
            model=model,
            name=body.name,
            label=patch.get("label"),
            zone=patch.get("zone"),
            height=patch.get("height"),
            height_cm=patch.get("height_cm"),
            room=patch.get("room"),
        )
        if is_ble_mac(addr):
            register_mac(app.state.suffix_map, addr)
        return enrich_device(device, app.state.labels)

    @app.get("/api/devices/discover")
    async def api_discover_devices(
        seconds: float = Query(default=120.0, gt=0, le=900),
        include_known: bool = Query(default=False),
    ) -> dict[str, Any]:
        """List recently heard Govee BLE sensors; unknown = not registered (or archived)."""
        since = time.time() - float(seconds)
        candidates = await db.list_ble_discover_candidates(
            since_ts=since, include_known=include_known
        )
        labels: dict[str, str] = app.state.labels
        sensors: list[dict[str, Any]] = []
        for row in candidates:
            display = str(row.get("name") or row.get("address") or "")
            addr = str(row.get("address") or "").upper()
            if labels.get(addr):
                display = labels[addr]
            sensors.append(
                {
                    "address": addr,
                    "name": display,
                    "model": row.get("model"),
                    "temperature_c": row.get("temperature_c"),
                    "humidity": row.get("humidity"),
                    "battery": row.get("battery"),
                    "rssi": row.get("rssi"),
                    "last_seen": row.get("last_seen"),
                    "unknown": bool(row.get("unknown")),
                    "archived": bool(row.get("archived")),
                }
            )
        scanning = await db.ble_discover_scan_pending()
        return {
            "scanner_enabled": bool(app.state.scanner_enabled),
            "scanning": scanning,
            "seconds": float(seconds),
            "sensors": sensors,
            "unknown_count": sum(1 for s in sensors if s.get("unknown")),
        }

    @app.post("/api/devices/discover/scan")
    async def api_discover_devices_scan() -> dict[str, Any]:
        """Ask the BLE worker to run a ~15s discovery pass."""
        if not app.state.scanner_enabled:
            raise HTTPException(
                status_code=503,
                detail="Local BLE scanner is disabled",
            )
        await db.request_ble_discover()
        return {"ok": True, "scanning": True, "duration_s": 15.0}

    @app.delete("/api/devices/{address}")
    async def api_delete_device(
        address: str,
        purge: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            addr = _validate_device_address(address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if purge:
            ok = await db.purge_device(addr)
            if not ok:
                raise HTTPException(status_code=404, detail="Unknown device")
            return {"ok": True, "address": addr, "purged": True}

        archived = await db.archive_device(addr)
        if archived is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        return {
            "ok": True,
            "address": addr,
            "purged": False,
            "device": enrich_device(archived, app.state.labels),
        }

    @app.get("/api/devices/{address}/placements")
    async def api_list_placements(address: str) -> dict[str, Any]:
        try:
            addr = _validate_device_address(address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        device = await db.get_device(addr, include_archived=True)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        placements = await db.list_placements(addr)
        return {
            "address": addr,
            "placements": placements,
        }

    @app.post("/api/devices/{address}/placements")
    async def api_create_placement(
        address: str, body: PlacementCreateBody
    ) -> dict[str, Any]:
        try:
            addr = _validate_device_address(address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        device = await db.get_device(addr)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")

        provided = body.model_dump(exclude_unset=True)
        patch: dict[str, Any] = {}
        if any(k in provided for k in ("zone", "height", "height_cm", "room", "label")):
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
        try:
            placement = await db.add_placement(
                addr,
                effective_from=body.effective_from,
                label=patch["label"] if "label" in patch else ...,
                zone=patch["zone"] if "zone" in patch else ...,
                height=patch["height"] if "height" in patch else ...,
                height_cm=patch["height_cm"] if "height_cm" in patch else ...,
                room=patch["room"] if "room" in patch else ...,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "placement": placement}

    @app.patch("/api/devices/{address}/placements/{placement_id}")
    async def api_patch_placement(
        address: str, placement_id: int, body: PlacementPatch
    ) -> dict[str, Any]:
        try:
            addr = _validate_device_address(address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        device = await db.get_device(addr, include_archived=True)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")

        provided = body.model_dump(exclude_unset=True)
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

        placements = await db.list_placements(addr)
        owned = next((p for p in placements if p["id"] == placement_id), None)
        if owned is None:
            raise HTTPException(status_code=404, detail="Placement not found")

        try:
            updated = await db.update_placement(
                placement_id,
                label=patch["label"] if "label" in patch else ...,
                zone=patch["zone"] if "zone" in patch else ...,
                height=patch["height"] if "height" in patch else ...,
                height_cm=patch["height_cm"] if "height_cm" in patch else ...,
                room=patch["room"] if "room" in patch else ...,
                valid_from=provided["valid_from"] if "valid_from" in provided else ...,
                valid_until=provided["valid_until"] if "valid_until" in provided else ...,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Placement not found")
        return {"ok": True, "placement": updated}

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
        hours: float = Query(24.0, gt=0, le=26280),
        future_hours: float | None = Query(default=None, gt=0, le=384),
        latitude: float | None = Query(default=None, ge=-90, le=90),
        longitude: float | None = Query(default=None, ge=-180, le=180),
        target_temp_c: float | None = Query(default=None, ge=10, le=40),
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
        # Live map / cross-section: ignore readings older than this (seconds).
        # BLE Govee ~15 min; Tuya HA T&H uses ha_th.stale_after (default 2 h).
        ha_th_cfg: HaThConfig | None = getattr(app.state, "ha_th", None)
        sensor_stale_after_s = map_stale_after_s(cfg=ha_th_cfg)
        now_ts = time.time()
        for d in devices:
            room = (d.get("room") or "").strip().lower()
            if room not in by_room:
                continue
            last_ts = d.get("last_reading_ts")
            if last_ts is None:
                last_ts = d.get("last_seen")
            try:
                last_f = float(last_ts) if last_ts is not None else None
            except (TypeError, ValueError):
                last_f = None
            after_s = map_stale_after_s(
                address=str(d.get("address") or ""),
                model=str(d.get("model") or ""),
                cfg=ha_th_cfg,
            )
            stale = last_f is None or (now_ts - last_f) > after_s
            by_room[room].append(
                {
                    "address": d.get("address"),
                    "name": device_display_name(d, labels),
                    "zone": d.get("zone"),
                    "height": d.get("height"),
                    "height_cm": d.get("height_cm"),
                    "temperature_c": d.get("temperature_c"),
                    "humidity": d.get("humidity"),
                    "last_reading_ts": last_f,
                    "stale": stale,
                    "stale_after_s": after_s,
                }
            )
        trends = await db.temperature_trends(
            [str(s.get("address") or "") for sensors in by_room.values() for s in sensors]
        )
        for sensors in by_room.values():
            for s in sensors:
                trend = trends.get(str(s.get("address") or "").upper())
                if not trend:
                    continue
                s["temp_trend"] = trend.get("dir")
                s["temp_delta_c"] = trend.get("delta_c")
                s["temp_rate_c_h"] = trend.get("rate_c_h")
        for room in payload["rooms"]:
            room["sensors"] = by_room.get(room["id"], [])
        payload["sensor_stale_after_s"] = sensor_stale_after_s

        def _exterior_comparative(
            sensors: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            """Exterior sensors for façade comparison — prefer height=high.

            Keep a stale high sensor (show last reading + warning on the map)
            rather than substituting a fresh low sensor.
            """
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
                            "window_scenarios": proj.get("window_scenarios") or {},
                            "opening_state": proj.get("opening_state"),
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
            hub_id, _specs = await _ensure_layout_connections(db, layout)
            conn_payload = await _build_connections_response(db, layout)
            connections = list(conn_payload.get("connections") or [])
        except Exception as exc:
            logger.warning("Apartment connections failed: %s", exc)
            hub_id = None
            connections = []
        conn_by_id = {
            str(c.get("id") or ""): c for c in connections if c.get("id")
        }

        for room in payload["rooms"]:
            rid = room["id"]
            outdoor_id = outdoor_connection_id(rid)
            outdoor_conn = conn_by_id.get(outdoor_id)
            contacts: list[dict[str, Any]] = []
            if outdoor_conn:
                for s in outdoor_conn.get("sensors") or []:
                    contacts.append(
                        {
                            "sensor_id": s.get("sensor_id"),
                            "name": s.get("name") or s.get("sensor_id"),
                            "kind": s.get("kind") or "window",
                            "state": s.get("state"),
                            "ts": s.get("ts"),
                        }
                    )
            room["contacts"] = contacts
            room["outdoor_connection_id"] = outdoor_id
            room["window_forced"] = bool(
                outdoor_conn and outdoor_conn.get("forced")
            )
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
            has_exterior = bool(room.get("exterior"))
            if (
                outdoor_conn
                and outdoor_conn.get("forced")
                and outdoor_conn.get("state") in ("open", "closed")
                and (windows or (has_exterior and not contacts))
            ):
                room["window_state"] = outdoor_conn["state"]
            elif any(str(c.get("state") or "").lower() == "open" for c in windows):
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

        for edge in payload.get("edges") or []:
            kind = str(edge.get("kind") or "door")
            a = str(edge.get("a") or "")
            b = str(edge.get("b") or "")
            edge["temp_delta_max_c"] = None
            edge["opening_source"] = None
            if kind == "wall":
                edge["contacts"] = []
                edge["opening"] = "sealed"
                edge["opening_source"] = "layout"
                edge["connection_id"] = None
                edge["forced"] = False
                edge["reported_opening"] = None
                continue
            try:
                cid = connection_id_for_rooms(a, b)
            except ValueError:
                edge["contacts"] = []
                edge["opening"] = "unknown"
                continue
            conn = conn_by_id.get(cid)
            related: list[dict[str, Any]] = []
            if conn:
                for s in conn.get("sensors") or []:
                    related.append(
                        {
                            "sensor_id": s.get("sensor_id"),
                            "name": s.get("name") or s.get("sensor_id"),
                            "kind": s.get("kind") or "door",
                            "state": s.get("state"),
                            "ts": s.get("ts"),
                            "room": s.get("room"),
                        }
                    )
            edge["contacts"] = related
            edge["connection_id"] = cid
            edge["forced"] = bool(conn and conn.get("forced"))
            edge["reported_opening"] = (
                conn.get("reported_state") if conn else None
            )
            if conn and conn.get("state") in ("open", "closed"):
                edge["opening"] = conn["state"]
                edge["opening_source"] = (
                    "manual" if conn.get("forced") else "contact"
                )
                continue
            if related:
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

        payload["hub_id"] = hub_id
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

        outdoor_rh = outdoor.get("humidity_now")
        if outdoor_rh is None:
            outdoor_rh = solar.get("humidity")
        payload["airflow_v2"] = suggest_cooling_airflow_v2(
            payload.get("rooms") or [],
            payload.get("edges") or [],
            outdoor_temp_c=(
                float(outdoor_temp) if outdoor_temp is not None else None
            ),
            outdoor_humidity=(
                float(outdoor_rh) if outdoor_rh is not None else None
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
            hvac=payload.get("hvac"),
            target_temp_c=target_temp_c,
        )
        payload["window_advice_v2"] = payload["airflow_v2"].get("advice") or {}

        presence_svc: PresenceService | None = app.state.presence
        if presence_svc is not None and presence_svc.cfg.ready:
            try:
                payload["presence"] = await presence_svc.snapshot(
                    apartment_rooms=list(payload.get("rooms") or [])
                )
            except Exception as exc:
                logger.warning("Apartment presence snapshot failed: %s", exc)
                payload["presence"] = {"enabled": True, "people": [], "error": str(exc)}
        else:
            payload["presence"] = {"enabled": False, "people": []}

        payload["active_plan"] = active_plan_meta(_plans_store())
        payload["room_options"] = known_room_options()
        return payload

    @app.get("/api/apartment/plans")
    async def api_list_plans() -> dict[str, Any]:
        store = _plans_store()
        return {
            "active_plan_id": store.get("active_plan_id"),
            "plans": [plan_summary(p) for p in store.get("plans") or []],
            "room_options": known_room_options(),
        }

    @app.post("/api/apartment/plans")
    async def api_create_plan(payload: PlanCreate) -> dict[str, Any]:
        try:
            plan = empty_plan(name=payload.name, mode=payload.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store = _plans_store()
        plans = list(store.get("plans") or [])
        plans.append(plan)
        store = {**store, "plans": plans}
        try:
            _persist_plans(store)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to save plan: {exc}"
            ) from exc
        return plan

    @app.get("/api/apartment/plans/{plan_id}")
    async def api_get_plan(plan_id: str) -> dict[str, Any]:
        plan = find_plan(_plans_store(), plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Unknown plan")
        return plan

    @app.put("/api/apartment/plans/{plan_id}")
    async def api_put_plan(plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        store = _plans_store()
        existing = find_plan(store, plan_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Unknown plan")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected JSON object")
        try:
            updated = validate_plan_update(existing, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        plans = []
        for p in store.get("plans") or []:
            if str(p.get("id")) == str(plan_id):
                plans.append(updated)
            else:
                plans.append(p)
        store = {**store, "plans": plans}
        try:
            _persist_plans(store)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to save plan: {exc}"
            ) from exc
        # If this is the active plan, recompile into the live layout.
        if store.get("active_plan_id") == plan_id:
            weather_svc: WeatherService | None = app.state.weather
            if weather_svc is not None and weather_svc.apartment is not None:
                compiled = apply_plan_to_layout(weather_svc.apartment, updated)
                if not compiled.get("ok"):
                    logger.warning(
                        "Active plan saved but compile failed: %s",
                        compiled.get("error") or compiled.get("warnings"),
                    )
                else:
                    try:
                        await _ensure_layout_connections(db, weather_svc.apartment)
                    except Exception as exc:
                        logger.warning("Connection sync after plan save failed: %s", exc)
        return updated

    @app.post("/api/apartment/plans/compile-preview")
    async def api_compile_plan_preview(payload: dict[str, Any]) -> dict[str, Any]:
        """Compile an in-memory plan body (editor preview; does not persist)."""
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected JSON object")
        try:
            return compile_plan(payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/apartment/plans/{plan_id}/compile")
    async def api_compile_plan(plan_id: str) -> dict[str, Any]:
        plan = find_plan(_plans_store(), plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Unknown plan")
        return compile_plan(plan)

    @app.post("/api/apartment/plans/{plan_id}/activate")
    async def api_activate_plan(plan_id: str) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            raise HTTPException(status_code=503, detail="Apartment layout not available")
        store = _plans_store()
        plan = find_plan(store, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Unknown plan")
        compiled = apply_plan_to_layout(weather_svc.apartment, plan)
        if not compiled.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=compiled.get("error")
                or "; ".join(compiled.get("warnings") or ["Compile failed"]),
            )
        store = {**store, "active_plan_id": plan_id}
        try:
            _persist_plans(store)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to activate plan: {exc}"
            ) from exc
        try:
            await _ensure_layout_connections(db, weather_svc.apartment)
        except Exception as exc:
            logger.warning("Connection sync after activate failed: %s", exc)
        logger.info(
            "Activated floor plan %s (%s) → %d rooms",
            plan_id,
            plan.get("name"),
            len(compiled.get("rooms") or []),
        )
        return {
            "active_plan_id": plan_id,
            "compiled": compiled,
            "active_plan": active_plan_meta(store),
        }

    @app.post("/api/apartment/plans/{plan_id}/deactivate")
    async def api_deactivate_plan(plan_id: str) -> dict[str, Any]:
        """Clear active plan and restore config.toml layout (if this plan was active)."""
        weather_svc: WeatherService | None = app.state.weather
        store = _plans_store()
        if store.get("active_plan_id") != plan_id:
            raise HTTPException(status_code=400, detail="Plan is not active")
        store = {**store, "active_plan_id": None}
        try:
            _persist_plans(store)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to deactivate plan: {exc}"
            ) from exc
        if weather_svc is not None and weather_svc.apartment is not None:
            _restore_fallback_layout(weather_svc.apartment)
            try:
                await _ensure_layout_connections(db, weather_svc.apartment)
            except Exception as exc:
                logger.warning("Connection sync after deactivate failed: %s", exc)
        return {"active_plan_id": None, "active_plan": None}

    @app.post("/api/apartment/plans/{plan_id}/duplicate")
    async def api_duplicate_plan(
        plan_id: str, payload: PlanDuplicate | None = None
    ) -> dict[str, Any]:
        store = _plans_store()
        plan = find_plan(store, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Unknown plan")
        name = payload.name if payload else None
        clone = duplicate_plan(plan, name=name)
        plans = list(store.get("plans") or [])
        plans.append(clone)
        store = {**store, "plans": plans}
        try:
            _persist_plans(store)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to duplicate plan: {exc}"
            ) from exc
        return clone

    @app.delete("/api/apartment/plans/{plan_id}")
    async def api_delete_plan(plan_id: str) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        store = _plans_store()
        plan = find_plan(store, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Unknown plan")
        was_active = store.get("active_plan_id") == plan_id
        plans = [p for p in (store.get("plans") or []) if str(p.get("id")) != plan_id]
        store = {
            **store,
            "plans": plans,
            "active_plan_id": None if was_active else store.get("active_plan_id"),
        }
        try:
            _persist_plans(store)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to delete plan: {exc}"
            ) from exc
        if was_active and weather_svc is not None and weather_svc.apartment is not None:
            _restore_fallback_layout(weather_svc.apartment)
            try:
                await _ensure_layout_connections(db, weather_svc.apartment)
            except Exception as exc:
                logger.warning("Connection sync after plan delete failed: %s", exc)
        return {"deleted": plan_id, "active_plan_id": store.get("active_plan_id")}

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

        try:
            updated = await db.update_device_categories(address, **patch)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        return enrich_device(updated, app.state.labels)

    @app.patch("/api/devices/{address}/compaction")
    async def api_patch_compaction(
        address: str,
        payload: CompactionPatch,
    ) -> dict[str, Any]:
        """Set per-device readings compaction policy."""
        from govee_charts.compaction import normalize_policy, POLICY_LABELS

        try:
            policy = normalize_policy(payload.policy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state = await db.set_compaction_policy(address, policy)
        if state is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        return {
            "address": state["address"],
            "policy": state["policy"],
            "label": POLICY_LABELS.get(state["policy"], state["policy"]),
            "last_run_ts": state.get("last_run_ts"),
            "last_saved_bytes": state.get("last_saved_bytes"),
            "updated_at": state.get("updated_at"),
        }

    @app.get("/api/devices/{address}/compaction/preview")
    async def api_compaction_preview(address: str) -> dict[str, Any]:
        """Dry-run report for every compaction policy (no data changes)."""
        report = await db.preview_compaction(
            address, labels=app.state.labels
        )
        if report is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        return report

    def _check_federation_token(
        request: Request,
        x_govee_token: str | None,
    ) -> None:
        expected = app.state.federation_token
        if not expected:
            return
        provided = x_govee_token or request.headers.get("Authorization", "").removeprefix(
            "Bearer "
        ).strip()
        if provided != expected:
            raise HTTPException(status_code=401, detail="Invalid federation token")

    @app.post("/api/devices/meta")
    async def api_ingest_device_meta(
        payload: DeviceMetaIngest,
        request: Request,
        x_govee_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Apply label/placement fields pushed by a federation peer (current open placement only)."""
        _check_federation_token(request, x_govee_token)
        if payload.node_id == app.state.node_id:
            raise HTTPException(status_code=400, detail="Refusing meta from self")

        ble_name = (payload.name or "").strip()
        address = resolve_device_address(
            payload.address,
            ble_name,
            suffix_map=app.state.suffix_map,
        )
        register_mac(app.state.suffix_map, address)

        try:
            patch = normalize_patch(
                zone=payload.zone,
                height=payload.height,
                height_cm=payload.height_cm,
                room=payload.room,
                label=payload.label,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = await db.update_device_categories(address, **patch)
        if updated is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown device {address} (peer must already know this sensor)",
            )
        logger.info(
            "Federation meta from %s → %s (%s)",
            payload.node_id,
            address,
            device_display_name(updated, app.state.labels),
        )
        return {
            "ok": True,
            "node_id": app.state.node_id,
            "device": enrich_device(updated, app.state.labels),
        }

    @app.post("/api/devices/{address}/push-meta")
    async def api_push_device_meta(address: str) -> dict[str, Any]:
        """Push this device's label/placement fields to all federation peers."""
        peers: list[str] = list(app.state.peers or [])
        if not peers:
            raise HTTPException(status_code=400, detail="No federation peers configured")

        device = await db.get_device(address)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")

        body = {
            "node_id": app.state.node_id,
            "address": str(device.get("address") or address).upper(),
            "name": str(device.get("name") or "").strip() or None,
            "label": device.get("label"),
            "zone": device.get("zone"),
            "height": device.get("height"),
            "height_cm": device.get("height_cm"),
            "room": device.get("room"),
        }

        headers: dict[str, str] = {"Content-Type": "application/json"}
        token = app.state.federation_token
        if token:
            headers["X-Govee-Token"] = token

        async def _one(peer: str) -> dict[str, Any]:
            try:
                async with httpx.AsyncClient(
                    timeout=10.0,
                    verify=False,
                    headers=headers,
                ) as client:
                    res = await client.post(f"{peer}/api/devices/meta", json=body)
                detail = ""
                try:
                    data = res.json()
                    if isinstance(data, dict):
                        detail = str(data.get("detail") or data.get("ok") or "")
                except Exception:
                    detail = (res.text or "")[:200]
                return {
                    "url": peer,
                    "ok": res.status_code < 400,
                    "status": res.status_code,
                    "detail": detail,
                }
            except Exception as exc:
                return {
                    "url": peer,
                    "ok": False,
                    "status": 0,
                    "detail": str(exc),
                }

        results = await asyncio.gather(*(_one(p) for p in peers))
        ok_n = sum(1 for r in results if r.get("ok"))
        logger.info(
            "Pushed device meta for %s to %d/%d peer(s)",
            body["address"],
            ok_n,
            len(peers),
        )
        return {
            "ok": ok_n == len(peers),
            "address": body["address"],
            "peers": list(results),
        }

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

    @app.get("/api/connections")
    async def api_connections() -> dict[str, Any]:
        """Apartment openings with assigned contact sensors and open/closed state."""
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            return {
                "connections": [],
                "sensors": await db.list_door_sensors(),
                "hub_id": None,
                "count": 0,
                "enabled": False,
            }
        payload = await _build_connections_response(db, weather_svc.apartment)
        payload["enabled"] = True
        return payload

    @app.put("/api/connections/{connection_id:path}/sensors")
    async def api_put_connection_sensors(
        connection_id: str,
        payload: ConnectionSensorsBody,
    ) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            raise HTTPException(
                status_code=503, detail="Apartment layout not available"
            )
        hub_id, _specs = await _ensure_layout_connections(db, weather_svc.apartment)
        try:
            parse_connection_id(connection_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = await db.set_connection_sensors(
            connection_id,
            list(payload.sensor_ids or []),
            hub_id=hub_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown connection")
        full = await _build_connections_response(db, weather_svc.apartment)
        for conn in full.get("connections") or []:
            if conn.get("id") == updated.get("connection_id"):
                return conn
        raise HTTPException(status_code=404, detail="Unknown connection")

    @app.post("/api/connections/{connection_id:path}/force")
    async def api_force_connection(
        connection_id: str,
        payload: ConnectionForceBody,
    ) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            raise HTTPException(
                status_code=503, detail="Apartment layout not available"
            )
        await _ensure_layout_connections(db, weather_svc.apartment)
        state = str(payload.state or "").strip().lower()
        if state not in ("open", "closed"):
            raise HTTPException(
                status_code=400, detail="state must be 'open' or 'closed'"
            )
        try:
            updated = await db.force_connection_state(connection_id, state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown connection")
        full = await _build_connections_response(db, weather_svc.apartment)
        for conn in full.get("connections") or []:
            if conn.get("id") == updated.get("connection_id"):
                return conn
        raise HTTPException(status_code=404, detail="Unknown connection")

    @app.post("/api/connections/{connection_id:path}/unlock")
    async def api_unlock_connection(connection_id: str) -> dict[str, Any]:
        weather_svc: WeatherService | None = app.state.weather
        if weather_svc is None or weather_svc.apartment is None:
            raise HTTPException(
                status_code=503, detail="Apartment layout not available"
            )
        await _ensure_layout_connections(db, weather_svc.apartment)
        updated = await db.clear_connection_force(connection_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown connection")
        full = await _build_connections_response(db, weather_svc.apartment)
        for conn in full.get("connections") or []:
            if conn.get("id") == updated.get("connection_id"):
                return conn
        raise HTTPException(status_code=404, detail="Unknown connection")

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

    @app.post("/api/doors/{sensor_id:path}/force")
    async def api_force_door(
        sensor_id: str,
        payload: DoorForceBody,
    ) -> dict[str, Any]:
        """Lock effective open/closed until the user unlocks (MQTT still logs)."""
        state = str(payload.state or "").strip().lower()
        if state not in ("open", "closed"):
            raise HTTPException(
                status_code=400, detail="state must be 'open' or 'closed'"
            )
        updated = await db.force_door_state(sensor_id, state)
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown door sensor")
        return updated

    @app.post("/api/doors/{sensor_id:path}/unlock")
    async def api_unlock_door(sensor_id: str) -> dict[str, Any]:
        """Clear a locked override; effective state follows live MQTT/HA again."""
        updated = await db.clear_door_force(sensor_id)
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
        target_temp_c: float | None = Query(default=None, ge=10, le=40),
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
            target_temp_c=target_temp_c,
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
            ok = False
            for attempt in range(3):
                try:
                    ok = await db.upsert_reading(
                        reading,
                        display,
                        ts=item.ts,
                        source=item_source,
                    )
                    break
                except Exception as exc:
                    if not is_db_locked(exc) or attempt >= 2:
                        raise
                    await asyncio.sleep(0.05 * (attempt + 1))
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
