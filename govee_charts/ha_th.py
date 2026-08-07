"""Home Assistant temperature / humidity sensors → readings (Tuya T&H, …)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from govee_charts.db import Database
from govee_charts.decode import Reading

logger = logging.getLogger(__name__)

BATTERY_STATE_PCT = {
    "high": 100,
    "full": 100,
    "middle": 50,
    "medium": 50,
    "mid": 50,
    "low": 20,
    "replace": 5,
    "critical": 5,
}


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in ("unavailable", "unknown", "none", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def battery_from_ha(payload: dict[str, Any] | None) -> int:
    """Map HA battery % or Tuya enum (high/middle/low) to 0–100."""
    if not payload:
        return 0
    state = payload.get("state")
    pct = _as_float(state)
    if pct is not None and 0 <= pct <= 100:
        return int(round(pct))
    key = str(state or "").strip().lower()
    if key in BATTERY_STATE_PCT:
        return BATTERY_STATE_PCT[key]
    attrs = payload.get("attributes") or {}
    for key_name in ("battery_level", "battery"):
        pct = _as_float(attrs.get(key_name))
        if pct is not None and 0 <= pct <= 100:
            return int(round(pct))
    return 0


@dataclass(frozen=True)
class HaThDevice:
    address: str
    label: str
    temperature_entity: str
    humidity_entity: str = ""
    battery_entity: str = ""
    model: str = "tuya-th"
    zone: str = "exterior"
    height: str = ""
    room: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HaThDevice | None:
        raw = raw or {}
        temp = str(raw.get("temperature_entity") or "").strip()
        if not temp:
            return None
        address = str(raw.get("address") or "").strip().upper()
        if not address:
            # Stable synthetic id from the HA entity slug.
            slug = temp.removeprefix("sensor.").upper().replace("_", "-")
            address = f"HA:{slug}"
        label = str(raw.get("label") or raw.get("name") or "").strip()
        if not label:
            label = address
        return cls(
            address=address,
            label=label,
            temperature_entity=temp,
            humidity_entity=str(raw.get("humidity_entity") or "").strip(),
            battery_entity=str(raw.get("battery_entity") or "").strip(),
            model=str(raw.get("model") or "tuya-th").strip() or "tuya-th",
            zone=str(raw.get("zone") or "").strip().lower(),
            height=str(raw.get("height") or "").strip().lower(),
            room=str(raw.get("room") or "").strip().lower(),
        )


@dataclass(frozen=True)
class HaThConfig:
    enabled: bool = False
    ha_url: str = "http://127.0.0.1:8123"
    ha_token: str = ""
    ha_token_file: str = ""
    poll_seconds: float = 60.0
    sample_interval: float = 60.0
    devices: tuple[HaThDevice, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HaThConfig:
        raw = raw or {}
        token = str(raw.get("ha_token") or "")
        token_file = str(raw.get("ha_token_file") or "").strip()
        if not token and token_file:
            path = Path(token_file).expanduser()
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning("HA token file unreadable (%s): %s", path, exc)
        devices: list[HaThDevice] = []
        seen: set[str] = set()
        for item in raw.get("devices") or []:
            if not isinstance(item, dict):
                continue
            device = HaThDevice.from_dict(item)
            if not device or device.address in seen:
                continue
            seen.add(device.address)
            devices.append(device)
        return cls(
            enabled=bool(raw.get("enabled", False)),
            ha_url=str(raw.get("ha_url") or "http://127.0.0.1:8123")
            .strip()
            .rstrip("/")
            or "http://127.0.0.1:8123",
            ha_token=token,
            ha_token_file=token_file,
            poll_seconds=max(10.0, float(raw.get("poll_seconds") or 60.0)),
            sample_interval=max(
                10.0, float(raw.get("sample_interval") or 60.0)
            ),
            devices=tuple(devices),
        )

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.ha_token and self.devices)


class HaThPoller:
    """Poll HA REST for T/H sensors and store them as chart devices."""

    def __init__(self, db: Database, cfg: HaThConfig, *, node_id: str = "") -> None:
        self.db = db
        self.cfg = cfg
        self.node_id = (node_id or "ha").strip() or "ha"
        self._last_store_ts: dict[str, float] = {}
        self._categories_seeded: set[str] = set()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.ha_token}",
            "Content-Type": "application/json",
        }

    async def _get_state(
        self, client: httpx.AsyncClient, entity_id: str
    ) -> dict[str, Any] | None:
        if not entity_id:
            return None
        url = f"{self.cfg.ha_url}/api/states/{quote(entity_id, safe='')}"
        try:
            response = await client.get(url, headers=self._headers())
        except Exception as exc:
            logger.warning("HA T/H request failed for %s: %s", entity_id, exc)
            return None
        if response.status_code == 401:
            logger.error("HA rejected token (401) for T/H entity %s", entity_id)
            return None
        if response.status_code == 404:
            logger.warning("HA T/H entity not found: %s", entity_id)
            return None
        if response.status_code >= 400:
            logger.warning(
                "HA T/H error for %s: HTTP %s %s",
                entity_id,
                response.status_code,
                response.text[:200],
            )
            return None
        try:
            return response.json()
        except ValueError:
            logger.warning("HA non-JSON response for T/H entity %s", entity_id)
            return None

    async def _ensure_categories(self, device: HaThDevice) -> None:
        if device.address in self._categories_seeded:
            return
        existing = await self.db.get_device(device.address)
        if existing is None:
            return
        kwargs: dict[str, Any] = {}
        if device.label and not existing.get("label"):
            kwargs["label"] = device.label
        if device.zone and not existing.get("zone"):
            kwargs["zone"] = device.zone
        if device.height and not existing.get("height"):
            kwargs["height"] = device.height
        if device.room and not existing.get("room"):
            kwargs["room"] = device.room
        if kwargs:
            await self.db.update_device_categories(device.address, **kwargs)
        self._categories_seeded.add(device.address)

    async def _poll_device(
        self, client: httpx.AsyncClient, device: HaThDevice, *, now: float
    ) -> None:
        last = self._last_store_ts.get(device.address, 0.0)
        if now - last < self.cfg.sample_interval:
            return

        temp_payload = await self._get_state(client, device.temperature_entity)
        if not temp_payload:
            return
        temp_c = _as_float(temp_payload.get("state"))
        if temp_c is None:
            return

        humidity = 0.0
        if device.humidity_entity:
            hum_payload = await self._get_state(client, device.humidity_entity)
            hum = _as_float((hum_payload or {}).get("state"))
            if hum is not None:
                humidity = hum

        battery = 0
        if device.battery_entity:
            bat_payload = await self._get_state(client, device.battery_entity)
            battery = battery_from_ha(bat_payload)

        reading = Reading(
            temperature_c=temp_c,
            humidity=humidity,
            battery=battery,
            address=device.address,
            name=device.label,
            model=device.model,
            rssi=None,
        )
        inserted = await self.db.upsert_reading(
            reading,
            device.label,
            ts=now,
            source=f"{self.node_id}/ha",
        )
        self._last_store_ts[device.address] = now
        await self._ensure_categories(device)
        if inserted:
            logger.info(
                "HA T/H %s → %.1f °C / %.0f %% (%s)",
                device.label,
                temp_c,
                humidity,
                device.address,
            )

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        now = time.time()
        for device in self.cfg.devices:
            try:
                await self._poll_device(client, device, now=now)
            except Exception:
                logger.exception("HA T/H poll failed for %s", device.address)

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self.cfg.devices:
            return
        if not self.cfg.ha_token:
            logger.error(
                "HA T/H poll enabled but no token "
                "(set ha_th.ha_token or ha_th.ha_token_file)"
            )
            return

        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info(
                "HA T/H poller started (%d device%s every %.0fs)",
                len(self.cfg.devices),
                "" if len(self.cfg.devices) == 1 else "s",
                self.cfg.poll_seconds,
            )
            while not stop_event.is_set():
                try:
                    await self._poll_once(client)
                except Exception:
                    logger.exception("HA T/H poll failed")
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.cfg.poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass
