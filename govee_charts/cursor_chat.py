"""Map-view chat via local Cursor Agent CLI (ask mode, read-only)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SNAPSHOT_MAX_CHARS = 12_000
PROMPT_MAX_CHARS = 16_000
USER_MESSAGE_MAX = 4_000

SYSTEM_PREAMBLE = (
    "You are advising on apartment climate for the Govee Charts Map view. "
    "The JSON snapshot includes the apartment layout (room areas, façade "
    "orientations, ceiling and door-frame heights) plus live sensors, "
    "doors/windows, outdoor now, next-12h forecast, HVAC, and thermal "
    "coupling — use that JSON; do not open config.toml. Ceiling is about "
    "2.5 m and interior door frames about 2.0 m: air above the lintel is a "
    "weakly mixed pocket. Answer clearly in the user's language. Ask mode is "
    "read-only: do not edit files or run mutating commands."
)

SYSTEM_PREAMBLE_V2 = (
    SYSTEM_PREAMBLE
    + " Advice model v2 is active: prefer per-room façade exterior sensors "
    "over the weather station when they disagree; ignore an exterior reading "
    "that matches indoor air while the station is clearly cooler (exhaust plume). "
    "If HVAC/AC is active, isolate that room (close its door and windows) "
    "instead of opening a through-draft. Do not follow the window banner or "
    "airflow path if façade temperatures contradict them."
)

FORECAST_CHAT_HOURS = 12.0


def normalize_cursor_chat_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(raw or {})
    mode = str(cfg.get("mode") or "ask").strip().lower() or "ask"
    if mode not in ("ask", "plan"):
        mode = "ask"
    timeout = float(cfg.get("timeout_s") or 180.0)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "agent_bin": str(cfg.get("agent_bin") or "").strip(),
        "mode": mode,
        "model": str(cfg.get("model") or "auto").strip() or "auto",
        "workspace": str(cfg.get("workspace") or "").strip(),
        "timeout_s": max(30.0, min(timeout, 600.0)),
        "db_path": str(cfg.get("db_path") or "data/map_chat.db").strip()
        or "data/map_chat.db",
    }


def resolve_agent_bin(configured: str = "") -> str | None:
    explicit = (configured or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        return None
    found = shutil.which("agent")
    if found:
        return found
    home = Path.home() / ".local" / "bin" / "agent"
    if home.is_file() and os.access(home, os.X_OK):
        return str(home.resolve())
    return None


def resolve_workspace(configured: str = "") -> str:
    explicit = (configured or "").strip()
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    # Prefer repo root when running from package / systemd WorkingDirectory.
    cwd = Path.cwd().resolve()
    if (cwd / "govee_charts").is_dir() and (cwd / "static").is_dir():
        return str(cwd)
    here = Path(__file__).resolve().parent.parent
    if (here / "govee_charts").is_dir():
        return str(here)
    return str(cwd)


def _round_num(value: Any, digits: int = 1) -> Any:
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _outdoor_forecast_next_hours(
    payload: dict[str, Any],
    *,
    hours: float = FORECAST_CHAT_HOURS,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Compact hourly outdoor points from now through the next ``hours``."""
    outdoor = payload.get("outdoor") or {}
    points = outdoor.get("points") or []
    if not points:
        return []
    t0 = float(now if now is not None else time.time())
    t1 = t0 + float(hours) * 3600.0
    out: list[dict[str, Any]] = []
    for p in points:
        try:
            ts = float(p.get("ts"))
        except (TypeError, ValueError):
            continue
        # Keep the current hour (±30 min) through the horizon.
        if ts < t0 - 1800.0 or ts > t1 + 60.0:
            continue
        item: dict[str, Any] = {
            "ts": int(ts),
            "temp_c": _round_num(p.get("temperature_c")),
            "humidity": _round_num(p.get("humidity"), 0),
        }
        wind = _round_num(p.get("wind_speed_ms"))
        if wind is not None:
            item["wind_ms"] = wind
        cloud = _round_num(p.get("cloud_cover"), 0)
        if cloud is not None:
            item["cloud_pct"] = cloud
        out.append(item)
    out.sort(key=lambda row: int(row.get("ts") or 0))
    return out


def apartment_snapshot_dict(
    payload: dict[str, Any],
    *,
    advice_model: str = "v1",
) -> dict[str, Any]:
    """Compact /api/apartment payload for prompts and chat history."""
    ceiling_m = _round_num(payload.get("ceiling_m"), 2)
    rooms_out: list[dict[str, Any]] = []
    for room in payload.get("rooms") or []:
        sensors = []
        for s in room.get("sensors") or []:
            if s.get("stale"):
                continue
            item: dict[str, Any] = {
                "name": s.get("name"),
                "zone": s.get("zone"),
                "temp_c": _round_num(s.get("temperature_c")),
                "humidity": _round_num(s.get("humidity"), 0),
            }
            if s.get("height"):
                item["height"] = s.get("height")
            if s.get("height_cm") is not None:
                item["height_cm"] = _round_num(s.get("height_cm"), 0)
            sensors.append(item)
        area_m2 = _round_num(room.get("area_m2"), 1)
        exterior = [
            str(o).strip().lower()
            for o in (room.get("exterior") or [])
            if str(o).strip()
        ]
        room_row: dict[str, Any] = {
            "id": room.get("id"),
            "label": room.get("label"),
            "area_m2": area_m2,
            "exterior": exterior,
            "temp_c": _round_num(room.get("temp_avg") or room.get("temp_now") or room.get("temp_c")),
            "humidity": _round_num(room.get("humidity"), 0),
            "window": room.get("window_state"),
            "sensors": sensors,
        }
        if room.get("facade_temp_c") is not None:
            room_row["facade_temp_c"] = _round_num(room.get("facade_temp_c"))
            room_row["facade_temp_min"] = _round_num(room.get("facade_temp_min"))
            room_row["facade_temp_max"] = _round_num(room.get("facade_temp_max"))
        if area_m2 is not None and ceiling_m is not None:
            room_row["volume_m3"] = _round_num(area_m2 * ceiling_m, 1)
        rooms_out.append(room_row)

    edges_out: list[dict[str, Any]] = []
    for edge in payload.get("edges") or []:
        edges_out.append(
            {
                "a": edge.get("a"),
                "b": edge.get("b"),
                "kind": edge.get("kind"),
                "opening": edge.get("opening"),
                "source": edge.get("opening_source"),
                "delta_c": _round_num(edge.get("temp_delta_max_c")),
            }
        )

    outdoor = payload.get("outdoor") or {}
    solar = payload.get("solar") or {}
    hvac = payload.get("hvac") or {}
    use_v2 = str(advice_model or "v1").strip().lower() == "v2"
    airflow = (
        payload.get("airflow_v2") if use_v2 else payload.get("airflow")
    ) or {}
    couple = payload.get("temp_couple") or {}
    forecast_12h = _outdoor_forecast_next_hours(payload, hours=FORECAST_CHAT_HOURS)
    loc = outdoor.get("location") or {}

    out = {
        "layout": {
            "ceiling_m": ceiling_m,
            "door_height_m": _round_num(payload.get("door_height_m"), 2),
            "window_sill_m": _round_num(payload.get("window_sill_m"), 2),
            "height_bands_cm": payload.get("height_bands_cm"),
            "area_m2": _round_num(payload.get("area_m2"), 1),
            "floor": payload.get("floor"),
            "floors_total": payload.get("floors_total"),
        },
        "rooms": rooms_out,
        "edges": edges_out,
        "outdoor_temp_c": _round_num(
            outdoor.get("temp_now")
            if outdoor.get("temp_now") is not None
            else solar.get("temperature_c")
        ),
        "outdoor": {
            "available": bool(outdoor.get("available")),
            "temp_c": _round_num(
                outdoor.get("temp_now")
                if outdoor.get("temp_now") is not None
                else solar.get("temperature_c")
            ),
            "humidity": _round_num(outdoor.get("humidity_now"), 0),
            "wind_ms": _round_num(outdoor.get("wind_speed_ms")),
            "wind_compass": outdoor.get("wind_compass"),
            "location": loc.get("name") if isinstance(loc, dict) else None,
        },
        "forecast_next_12h": forecast_12h,
        "temp_couple": {
            "open_if_delta_le_c": couple.get("open_threshold_c"),
            "isolated_if_delta_ge_c": couple.get("closed_threshold_c"),
        },
        "hvac": {
            "enabled": bool(hvac.get("enabled")),
            "active": bool(hvac.get("active")),
            "room": hvac.get("room"),
            "mode": hvac.get("mode") or hvac.get("hvac_mode"),
            "setpoint_c": _round_num(hvac.get("temperature") or hvac.get("setpoint")),
        },
        "airflow": {
            "mode": airflow.get("mode"),
            "inlet": airflow.get("inlet"),
            "outlet": airflow.get("outlet"),
            "path": airflow.get("path") or [],
            "delta_c": _round_num(airflow.get("delta_c")),
            "actions": airflow.get("actions") or airflow.get("suggestions") or [],
            "summary": airflow.get("summary") or airflow.get("hint"),
        },
        "advice_model": "v2" if use_v2 else "v1",
    }
    if use_v2:
        wa = payload.get("window_advice_v2") or airflow.get("advice") or {}
        out["window_advice"] = {
            "tone": wa.get("tone"),
            "mode": wa.get("mode"),
            "hvac_isolate": wa.get("hvac_isolate"),
            "hvac_close_door": wa.get("hvac_close_door"),
            "station_temp_c": _round_num(wa.get("station_temp_c")),
            "dew_c": _round_num(wa.get("dew_c")),
            "open_rooms": [
                r.get("label") or r.get("id") for r in (wa.get("open_rooms") or [])
            ],
            "close_rooms": [
                r.get("label") or r.get("id") for r in (wa.get("close_rooms") or [])
            ],
            "actions": wa.get("actions") or [],
            "rooms": [
                {
                    "id": r.get("id"),
                    "kind": r.get("kind"),
                    "indoor_c": _round_num(r.get("indoor_c")),
                    "window_c": _round_num(r.get("window_c")),
                    "window_source": r.get("window_source"),
                    "facade_c": _round_num(r.get("facade_c")),
                    "window": r.get("window_state"),
                }
                for r in (wa.get("rooms") or [])
            ],
        }
    return out


def compact_apartment_snapshot(
    payload: dict[str, Any],
    *,
    advice_model: str = "v1",
) -> str:
    """Shrink /api/apartment payload for the agent prompt (JSON string)."""
    snap = apartment_snapshot_dict(payload, advice_model=advice_model)
    text = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    if len(text) > SNAPSHOT_MAX_CHARS:
        text = text[: SNAPSHOT_MAX_CHARS - 1] + "…"
    return text


def normalize_banner(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    detail = str(raw.get("detail") or "").strip()
    tone = str(raw.get("tone") or "idle").strip() or "idle"
    hidden = bool(raw.get("hidden"))
    if hidden and not title and not detail:
        return {"hidden": True, "tone": tone, "title": "", "detail": ""}
    return {
        "hidden": hidden,
        "tone": tone[:32],
        "title": title[:500],
        "detail": detail[:2000],
    }


def build_prompt(
    user_message: str,
    snapshot: str,
    *,
    banner: dict[str, Any] | None = None,
    advice_model: str = "v1",
) -> str:
    msg = (user_message or "").strip()
    if len(msg) > USER_MESSAGE_MAX:
        msg = msg[: USER_MESSAGE_MAX - 1] + "…"
    banner_block = ""
    if banner and not banner.get("hidden"):
        title = str(banner.get("title") or "").strip()
        detail = str(banner.get("detail") or "").strip()
        tone = str(banner.get("tone") or "").strip()
        if title or detail:
            banner_block = (
                "\n\nWindow advice banner shown to the user at request time"
                + (f" (tone={tone})" if tone else "")
                + ":\n"
                + (f"Title: {title}\n" if title else "")
                + (f"Detail: {detail}\n" if detail else "")
            )
    preamble = (
        SYSTEM_PREAMBLE_V2
        if str(advice_model or "").strip().lower() == "v2"
        else SYSTEM_PREAMBLE
    )
    prompt = (
        f"{preamble}\n\n"
        f"Live apartment snapshot (JSON):\n{snapshot}"
        f"{banner_block}\n"
        f"User question:\n{msg}"
    )
    if len(prompt) > PROMPT_MAX_CHARS:
        prompt = prompt[: PROMPT_MAX_CHARS - 1] + "…"
    return prompt


def _assistant_text(event: dict[str, Any]) -> str:
    message = event.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _delta_from_assistant(pieces: list[str], text: str) -> str | None:
    """Map stream-partial assistant events to new text only."""
    if not text:
        return None
    joined = "".join(pieces)
    if joined and text == joined:
        return None
    if joined and text.startswith(joined):
        pieces.clear()
        pieces.append(text)
        return text[len(joined) :]
    pieces.append(text)
    return text


async def probe_agent_status(
    agent_bin: str, *, timeout_s: float = 15.0
) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            agent_bin,
            "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
    except OSError as exc:
        return {"ok": False, "logged_in": False, "detail": str(exc)}

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"ok": False, "logged_in": False, "detail": "agent status timed out"}

    text = (stdout_b or b"").decode("utf-8", errors="replace").strip()
    err = (stderr_b or b"").decode("utf-8", errors="replace").strip()
    combined = text or err
    logged_in = "logged in" in combined.lower() and "not logged" not in combined.lower()
    return {
        "ok": proc.returncode == 0,
        "logged_in": logged_in,
        "detail": combined[:500] if combined else f"exit {proc.returncode}",
    }


async def stream_agent_chat(
    *,
    agent_bin: str,
    prompt: str,
    workspace: str,
    model: str = "auto",
    mode: str = "ask",
    session_id: str | None = None,
    timeout_s: float = 180.0,
) -> AsyncIterator[dict[str, Any]]:
    """Yield {type: delta|done|error, ...} from `agent -p` stream-json."""
    cmd = [
        agent_bin,
        "-p",
        "--mode",
        mode,
        "--trust",
        "--workspace",
        workspace,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--stream-partial-output",
    ]
    sid = (session_id or "").strip()
    if sid:
        cmd.extend(["--resume", sid])
    cmd.append(prompt)

    env = os.environ.copy()
    # Ensure ~/.local/bin is visible when systemd PATH is minimal.
    local_bin = str(Path.home() / ".local" / "bin")
    path = env.get("PATH") or ""
    if local_bin not in path.split(":"):
        env["PATH"] = f"{local_bin}:{path}" if path else local_bin

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=workspace,
        )
    except OSError as exc:
        yield {"type": "error", "message": f"failed to start agent: {exc}"}
        return

    assert proc.stdout is not None
    pieces: list[str] = []
    out_session = sid or None
    final_text = ""
    stderr_chunks: list[bytes] = []

    async def _drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk)

    stderr_task = asyncio.create_task(_drain_stderr())

    try:
        while True:
            try:
                line_b = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=timeout_s
                )
            except asyncio.TimeoutError:
                proc.kill()
                yield {
                    "type": "error",
                    "message": f"agent timed out after {int(timeout_s)}s",
                    "session_id": out_session,
                }
                return
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if event.get("session_id"):
                out_session = str(event["session_id"])
            if etype == "assistant":
                text = _assistant_text(event)
                delta = _delta_from_assistant(pieces, text)
                if delta:
                    final_text = "".join(pieces)
                    yield {
                        "type": "delta",
                        "text": delta,
                        "session_id": out_session,
                    }
            elif etype == "result":
                if event.get("session_id"):
                    out_session = str(event["session_id"])
                if event.get("is_error"):
                    msg = str(
                        event.get("result")
                        or event.get("error")
                        or "agent run failed"
                    )
                    yield {
                        "type": "error",
                        "message": msg[:500],
                        "session_id": out_session,
                    }
                    return
                result_text = str(event.get("result") or final_text or "")
                if result_text and result_text != final_text:
                    # Emit only the missing suffix if partials were incomplete.
                    if final_text and result_text.startswith(final_text):
                        extra = result_text[len(final_text) :]
                        if extra:
                            yield {
                                "type": "delta",
                                "text": extra,
                                "session_id": out_session,
                            }
                    elif not final_text:
                        yield {
                            "type": "delta",
                            "text": result_text,
                            "session_id": out_session,
                        }
                    final_text = result_text
                yield {
                    "type": "done",
                    "text": final_text,
                    "session_id": out_session,
                }
                return
    finally:
        stderr_task.cancel()
        try:
            await stderr_task
        except asyncio.CancelledError:
            pass
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    err_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
    if proc.returncode not in (0, None):
        yield {
            "type": "error",
            "message": (err_text or f"agent exited {proc.returncode}")[:500],
            "session_id": out_session,
        }
        return
    if final_text:
        yield {"type": "done", "text": final_text, "session_id": out_session}
    else:
        yield {
            "type": "error",
            "message": err_text or "agent produced no response",
            "session_id": out_session,
        }
