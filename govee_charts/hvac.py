"""Home Assistant climate + power historization (Tuya AC, Ecojoko, …)."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from govee_charts.db import Database

logger = logging.getLogger(__name__)

ACTIVE_HVAC_STATES = frozenset(
    {
        "cool",
        "heat",
        "heat_cool",
        "auto",
        "dry",
        "fan_only",
        "fan",
    }
)


def is_hvac_active(state: str | None) -> bool:
    """True when the climate entity is not off / unavailable."""
    if not state:
        return False
    text = str(state).strip().lower()
    if text in ("off", "unavailable", "unknown", ""):
        return False
    return text in ACTIVE_HVAC_STATES or text not in ("idle",)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class HvacConfig:
    enabled: bool = False
    ha_url: str = "http://127.0.0.1:8123"
    ha_token: str = ""
    ha_token_file: str = ""
    climate_entity: str = "climate.medion_smart_mobile_camping_ac_p502_md37735"
    power_entity: str = "sensor.infocris_consommation_temps_reel"
    poll_seconds: float = 15.0
    retention_days: float = 365.0
    # Optional one-shot import from Home Assistant recorder SQLite.
    ha_db_path: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "HvacConfig":
        raw = raw or {}
        token = str(raw.get("ha_token") or "")
        token_file = str(raw.get("ha_token_file") or "").strip()
        if not token and token_file:
            path = Path(token_file).expanduser()
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning("HA token file unreadable (%s): %s", path, exc)
        return cls(
            enabled=bool(raw.get("enabled", False)),
            ha_url=str(raw.get("ha_url") or "http://127.0.0.1:8123").strip().rstrip("/")
            or "http://127.0.0.1:8123",
            ha_token=token,
            ha_token_file=token_file,
            climate_entity=str(
                raw.get("climate_entity")
                or "climate.medion_smart_mobile_camping_ac_p502_md37735"
            ).strip(),
            power_entity=str(
                raw.get("power_entity") or "sensor.infocris_consommation_temps_reel"
            ).strip(),
            poll_seconds=max(5.0, float(raw.get("poll_seconds") or 15.0)),
            retention_days=float(raw.get("retention_days") or 365.0),
            ha_db_path=str(raw.get("ha_db_path") or "").strip(),
        )


def climate_snapshot_from_ha(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a HA /api/states climate payload into storage fields."""
    attrs = payload.get("attributes") or {}
    state = str(payload.get("state") or "").strip()
    hvac_mode = _as_str(attrs.get("hvac_mode")) or state or None
    fan = attrs.get("fan_mode")
    return {
        "state": state,
        "hvac_mode": hvac_mode,
        "current_temp_c": _as_float(attrs.get("current_temperature")),
        "target_temp_c": _as_float(attrs.get("temperature")),
        "fan_mode": _as_str(fan) if fan is not None else None,
    }


def power_watts_from_ha(payload: dict[str, Any]) -> float | None:
    return _as_float(payload.get("state"))


class HvacHaPoller:
    """Poll Home Assistant REST for climate + power and persist changes."""

    def __init__(self, db: Database, cfg: HvacConfig) -> None:
        self.db = db
        self.cfg = cfg
        self._last_climate_key: tuple[Any, ...] | None = None
        self._last_power_watts: float | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.ha_token}",
            "Content-Type": "application/json",
        }

    async def _get_state(
        self, client: httpx.AsyncClient, entity_id: str
    ) -> dict[str, Any] | None:
        url = f"{self.cfg.ha_url}/api/states/{quote(entity_id, safe='')}"
        try:
            response = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            logger.warning("HA request failed for %s: %s", entity_id, exc)
            return None
        if response.status_code == 401:
            logger.error("HA rejected token (401) for %s", entity_id)
            return None
        if response.status_code == 404:
            logger.warning("HA entity not found: %s", entity_id)
            return None
        if response.status_code >= 400:
            logger.warning(
                "HA error for %s: HTTP %s %s",
                entity_id,
                response.status_code,
                response.text[:200],
            )
            return None
        try:
            return response.json()
        except ValueError:
            logger.warning("HA non-JSON response for %s", entity_id)
            return None

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        now = time.time()
        if self.cfg.climate_entity:
            climate = await self._get_state(client, self.cfg.climate_entity)
            if climate:
                snap = climate_snapshot_from_ha(climate)
                key = (
                    snap["state"],
                    snap["hvac_mode"],
                    snap["current_temp_c"],
                    snap["target_temp_c"],
                    snap["fan_mode"],
                )
                if key != self._last_climate_key:
                    inserted = await self.db.insert_hvac_event(
                        entity_id=self.cfg.climate_entity,
                        state=snap["state"],
                        hvac_mode=snap["hvac_mode"],
                        current_temp_c=snap["current_temp_c"],
                        target_temp_c=snap["target_temp_c"],
                        fan_mode=snap["fan_mode"],
                        ts=now,
                        source="ha",
                    )
                    self._last_climate_key = key
                    if inserted:
                        logger.info(
                            "HVAC %s → %s (target=%s current=%s)",
                            self.cfg.climate_entity,
                            snap["state"],
                            snap["target_temp_c"],
                            snap["current_temp_c"],
                        )

        if self.cfg.power_entity:
            power = await self._get_state(client, self.cfg.power_entity)
            if power:
                watts = power_watts_from_ha(power)
                if watts is not None:
                    await self.db.insert_power_sample(
                        entity_id=self.cfg.power_entity,
                        watts=watts,
                        ts=now,
                        source="ha",
                    )
                    if self._last_power_watts != watts:
                        logger.debug(
                            "Power %s → %.0f W", self.cfg.power_entity, watts
                        )
                    self._last_power_watts = watts

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self.cfg.ha_token:
            logger.error(
                "HVAC historization enabled but no HA token "
                "(set hvac.ha_token or hvac.ha_token_file)"
            )
            return
        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info(
                "HVAC poller started (%s + %s every %.0fs)",
                self.cfg.climate_entity,
                self.cfg.power_entity,
                self.cfg.poll_seconds,
            )
            while not stop_event.is_set():
                try:
                    await self._poll_once(client)
                except Exception:
                    logger.exception("HVAC poll failed")
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.cfg.poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass


def _attrs_from_ha_row(shared_attrs: str | None) -> dict[str, Any]:
    if not shared_attrs:
        return {}
    try:
        data = json.loads(shared_attrs)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def import_ha_hvac_history(db: Database, cfg: HvacConfig) -> tuple[int, int]:
    """
    Import climate transitions and power samples from a HA recorder SQLite DB.
    Returns (hvac_inserted, power_inserted).
    """
    path = Path(cfg.ha_db_path)
    if not path.is_file():
        logger.warning("HA recorder DB not found: %s", path)
        return 0, 0

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    hvac_n = 0
    power_n = 0
    try:
        cur = con.cursor()
        if cfg.climate_entity:
            meta = cur.execute(
                "SELECT metadata_id FROM states_meta WHERE entity_id = ?",
                (cfg.climate_entity,),
            ).fetchone()
            if meta:
                rows = cur.execute(
                    """
                    SELECT s.state, s.last_updated_ts, a.shared_attrs
                    FROM states s
                    LEFT JOIN state_attributes a ON s.attributes_id = a.attributes_id
                    WHERE s.metadata_id = ?
                    ORDER BY s.last_updated_ts ASC
                    """,
                    (meta[0],),
                ).fetchall()
                prev_key: tuple[Any, ...] | None = None
                for raw_state, ts, shared_attrs in rows:
                    attrs = _attrs_from_ha_row(shared_attrs)
                    state = str(raw_state or "").strip()
                    if not state or ts is None:
                        continue
                    snap = climate_snapshot_from_ha(
                        {"state": state, "attributes": attrs}
                    )
                    key = (
                        snap["state"],
                        snap["hvac_mode"],
                        snap["current_temp_c"],
                        snap["target_temp_c"],
                        snap["fan_mode"],
                    )
                    if key == prev_key:
                        continue
                    prev_key = key
                    if await db.insert_hvac_event(
                        entity_id=cfg.climate_entity,
                        state=snap["state"],
                        hvac_mode=snap["hvac_mode"],
                        current_temp_c=snap["current_temp_c"],
                        target_temp_c=snap["target_temp_c"],
                        fan_mode=snap["fan_mode"],
                        ts=float(ts),
                        source="ha-import",
                    ):
                        hvac_n += 1

        if cfg.power_entity:
            meta = cur.execute(
                "SELECT metadata_id FROM states_meta WHERE entity_id = ?",
                (cfg.power_entity,),
            ).fetchone()
            if meta:
                rows = cur.execute(
                    """
                    SELECT state, last_updated_ts
                    FROM states
                    WHERE metadata_id = ?
                    ORDER BY last_updated_ts ASC
                    """,
                    (meta[0],),
                ).fetchall()
                prev_watts: float | None = None
                for raw_state, ts in rows:
                    watts = _as_float(raw_state)
                    if watts is None or ts is None:
                        continue
                    if prev_watts is not None and watts == prev_watts:
                        continue
                    prev_watts = watts
                    if await db.insert_power_sample(
                        entity_id=cfg.power_entity,
                        watts=watts,
                        ts=float(ts),
                        source="ha-import",
                    ):
                        power_n += 1
        return hvac_n, power_n
    finally:
        con.close()


def hvac_active_bands(
    events: list[dict[str, Any]],
    *,
    now_ts: float | None = None,
) -> list[dict[str, float]]:
    """
    Convert discrete HVAC events into {x1,x2} active bands (ms epoch for Chart.js).
    """
    if not events:
        return []
    end = float(now_ts if now_ts is not None else time.time())
    bands: list[dict[str, float]] = []
    active_start: float | None = None
    for ev in events:
        ts = float(ev.get("ts") or 0)
        active = is_hvac_active(str(ev.get("state") or ""))
        if active and active_start is None:
            active_start = ts
        elif not active and active_start is not None:
            if ts > active_start:
                bands.append({"x1": active_start * 1000.0, "x2": ts * 1000.0})
            active_start = None
    if active_start is not None and end > active_start:
        bands.append({"x1": active_start * 1000.0, "x2": end * 1000.0})
    return bands
