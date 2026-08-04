"""MQTT listener for Ring / Home Assistant door and window contact sensors."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from govee_charts.db import Database

logger = logging.getLogger(__name__)


def _normalize_contact_state(raw: str | bytes | None) -> str | None:
    if raw is None:
        return None
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
    text = text.strip().lower()
    if text in ("on", "open", "true", "1"):
        return "open"
    if text in ("off", "closed", "false", "0"):
        return "closed"
    return None


@dataclass(frozen=True)
class DoorsConfig:
    enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_password_file: str = ""
    # Subscribes to Home Assistant MQTT discovery binary_sensor states.
    discovery_prefix: str = "homeassistant"
    # Also listen to ring-mqtt raw contact topics.
    ring_topic: str = "ring/#"
    retention_days: float = 365.0
    # Optional path to HA recorder DB for one-shot history import.
    ha_db_path: str = ""
    # Optional HA device registry for friendly Ring MQTT names.
    ha_device_registry: str = ""
    # Manual overrides: sensor_id → display name
    names: dict[str, str] = field(default_factory=dict)
    # Optional Home Assistant REST poll for contacts not on MQTT (Tuya, …).
    ha_url: str = "http://127.0.0.1:8123"
    ha_token: str = ""
    ha_token_file: str = ""
    ha_poll_seconds: float = 10.0
    ha_entities: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> DoorsConfig:
        raw = raw or {}
        password = str(raw.get("mqtt_password") or "")
        pw_file = str(raw.get("mqtt_password_file") or "").strip()
        if not password and pw_file:
            path = Path(pw_file).expanduser()
            try:
                password = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning("Door MQTT password file unreadable (%s): %s", path, exc)
        token = str(raw.get("ha_token") or "")
        token_file = str(raw.get("ha_token_file") or "").strip()
        if not token and token_file:
            path = Path(token_file).expanduser()
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning("Door HA token file unreadable (%s): %s", path, exc)
        names_raw = raw.get("names") or {}
        names = {
            str(k).strip(): str(v).strip()
            for k, v in names_raw.items()
            if str(k).strip() and str(v).strip()
        }
        entities_raw = raw.get("ha_entities") or []
        if isinstance(entities_raw, str):
            entities_raw = [entities_raw]
        ha_entities = tuple(
            str(e).strip() for e in entities_raw if str(e).strip()
        )
        return cls(
            enabled=bool(raw.get("enabled", False)),
            mqtt_host=str(raw.get("mqtt_host") or "127.0.0.1").strip() or "127.0.0.1",
            mqtt_port=int(raw.get("mqtt_port") or 1883),
            mqtt_username=str(raw.get("mqtt_username") or "").strip(),
            mqtt_password=password,
            mqtt_password_file=pw_file,
            discovery_prefix=str(raw.get("discovery_prefix") or "homeassistant").strip()
            or "homeassistant",
            ring_topic=str(raw.get("ring_topic") or "ring/#").strip() or "ring/#",
            retention_days=float(raw.get("retention_days") or 365.0),
            ha_db_path=str(raw.get("ha_db_path") or "").strip(),
            ha_device_registry=str(raw.get("ha_device_registry") or "").strip(),
            names=names,
            ha_url=str(raw.get("ha_url") or "http://127.0.0.1:8123").strip().rstrip("/")
            or "http://127.0.0.1:8123",
            ha_token=token,
            ha_token_file=token_file,
            ha_poll_seconds=max(5.0, float(raw.get("ha_poll_seconds") or 10.0)),
            ha_entities=ha_entities,
        )


def load_ha_mqtt_names(path: str | Path) -> dict[str, str]:
    """Read friendly names from Home Assistant device registry (MQTT identifiers)."""
    registry = Path(path)
    if not registry.is_file():
        return {}
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("HA device registry unreadable (%s): %s", registry, exc)
        return {}
    out: dict[str, str] = {}
    for device in (data.get("data") or {}).get("devices") or []:
        if not isinstance(device, dict):
            continue
        name = str(device.get("name_by_user") or device.get("name") or "").strip()
        if not name:
            continue
        for ident in device.get("identifiers") or []:
            if (
                isinstance(ident, (list, tuple))
                and len(ident) >= 2
                and str(ident[0]) == "mqtt"
            ):
                out[str(ident[1])] = name
    return out


class DoorMqttListener:
    """Subscribe to MQTT contact sensors and persist open/close events."""

    def __init__(self, db: Database, cfg: DoorsConfig) -> None:
        self.db = db
        self.cfg = cfg
        self._names: dict[str, str] = dict(cfg.names)
        if cfg.ha_device_registry:
            loaded = load_ha_mqtt_names(cfg.ha_device_registry)
            # Config overrides registry
            self._names = {**loaded, **self._names}
            if loaded:
                logger.info("Loaded %d door/device name(s) from HA registry", len(loaded))
        self._last_state: dict[str, str] = {}
        self._object_ids: dict[str, str] = {}  # discovery object_id → sensor_id

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            from aiomqtt import Client, MqttError
        except ImportError:
            logger.error(
                "Door historization requires aiomqtt — pip install aiomqtt"
            )
            await stop_event.wait()
            return

        prefix = self.cfg.discovery_prefix.rstrip("/")
        topics = [
            f"{prefix}/binary_sensor/+/config",
            f"{prefix}/binary_sensor/+/state",
            self.cfg.ring_topic,
        ]

        backoff = 2.0
        while not stop_event.is_set():
            try:
                async with Client(
                    hostname=self.cfg.mqtt_host,
                    port=self.cfg.mqtt_port,
                    username=self.cfg.mqtt_username or None,
                    password=self.cfg.mqtt_password or None,
                ) as client:
                    for topic in topics:
                        await client.subscribe(topic)
                    logger.info(
                        "Door MQTT listening on %s:%d (%s)",
                        self.cfg.mqtt_host,
                        self.cfg.mqtt_port,
                        ", ".join(topics),
                    )
                    backoff = 2.0
                    message_iterator = client.messages
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(
                                message_iterator.__anext__(),
                                timeout=1.0,
                            )
                        except asyncio.TimeoutError:
                            continue
                        except StopAsyncIteration:
                            break
                        await self._handle_message(
                            str(message.topic), message.payload
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    break
                logger.warning(
                    "Door MQTT disconnected (%s) — retry in %.0fs", exc, backoff
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(60.0, backoff * 1.5)

    async def _handle_message(self, topic: str, payload: bytes | bytearray) -> None:
        parts = topic.split("/")
        # homeassistant/binary_sensor/<object_id>/config|state
        if (
            len(parts) >= 4
            and parts[0] == self.cfg.discovery_prefix.rstrip("/")
            and parts[1] == "binary_sensor"
        ):
            object_id = parts[2]
            kind = parts[3]
            if kind == "config":
                self._handle_discovery_config(object_id, payload)
                return
            if kind == "state":
                await self._handle_discovery_state(object_id, payload)
                return

        # ring/<location>/alarm/<device_id>/contact/state
        if (
            len(parts) >= 6
            and parts[0] == "ring"
            and parts[2] == "alarm"
            and parts[4] == "contact"
            and parts[5] == "state"
        ):
            sensor_id = parts[3]
            state = _normalize_contact_state(payload)
            if state is None:
                return
            name = self._names.get(sensor_id, sensor_id)
            await self._record(sensor_id, name, state, source="ring-mqtt")

    def _handle_discovery_config(self, object_id: str, payload: bytes | bytearray) -> None:
        try:
            cfg = json.loads(payload.decode() if payload else "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(cfg, dict):
            return
        device_class = str(cfg.get("device_class") or "").lower()
        # Ring contact sensors are typically opening / door / window
        if device_class not in ("door", "window", "opening", "garage_door"):
            # Still accept if unique_id looks like a contact from ring-mqtt
            uniq = str(cfg.get("unique_id") or "")
            if "contact" not in uniq.lower() and "~contact" not in str(
                cfg.get("~") or ""
            ):
                # ring-mqtt uses device_class opening for contacts
                return
        name = str(cfg.get("name") or object_id)
        uniq = str(cfg.get("unique_id") or object_id)
        # Prefer Ring device UUID when present in unique_id
        sensor_id = uniq
        for token in uniq.replace("__", "_").split("_"):
            if len(token) >= 32 and "-" in token:
                sensor_id = token
                break
        # ring-mqtt unique_id often ends with _contact
        if sensor_id.endswith("_contact"):
            sensor_id = sensor_id[: -len("_contact")]
        self._names[sensor_id] = name
        self._object_ids[object_id] = sensor_id
        logger.debug("Door discovery: %s → %s (%s)", object_id, name, sensor_id)

    async def _handle_discovery_state(
        self, object_id: str, payload: bytes | bytearray
    ) -> None:
        sensor_id = self._object_ids.get(object_id)
        if not sensor_id:
            # Unknown sensor — ignore until config arrives (or not a door)
            return
        state = _normalize_contact_state(payload)
        if state is None:
            return
        name = self._names.get(sensor_id, object_id)
        await self._record(sensor_id, name, state, source="mqtt-discovery")

    async def _record(
        self, sensor_id: str, name: str, state: str, *, source: str
    ) -> None:
        prev = self._last_state.get(sensor_id)
        if prev == state:
            return
        self._last_state[sensor_id] = state
        inserted = await self.db.insert_door_event(
            sensor_id=sensor_id,
            name=name,
            state=state,
            ts=time.time(),
            source=source,
        )
        if inserted:
            logger.info("Door %s → %s (%s)", name, state, sensor_id)


async def import_ha_door_history(
    db: Database,
    ha_db_path: str | Path,
    names: dict[str, str] | None = None,
) -> int:
    """
    Import open/close transitions from a Home Assistant recorder SQLite DB.
    Returns number of newly inserted events.
    """
    import sqlite3

    path = Path(ha_db_path)
    if not path.is_file():
        logger.warning("HA recorder DB not found: %s", path)
        return 0

    name_overrides = {
        str(k).strip(): str(v).strip()
        for k, v in (names or {}).items()
        if str(k).strip() and str(v).strip()
    }

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        metas = cur.execute(
            """
            SELECT metadata_id, entity_id
            FROM states_meta
            WHERE entity_id LIKE 'binary_sensor.%'
              AND (
                entity_id LIKE '%porte%'
                OR entity_id LIKE '%fenetre%'
                OR entity_id LIKE '%fenêtre%'
                OR entity_id LIKE '%door%'
                OR entity_id LIKE '%window%'
              )
              AND entity_id NOT LIKE '%tamper%'
              AND entity_id NOT LIKE '%motion%'
            """
        ).fetchall()
        inserted = 0
        for metadata_id, entity_id in metas:
            rows = cur.execute(
                """
                SELECT state, last_updated_ts
                FROM states
                WHERE metadata_id = ?
                ORDER BY last_updated_ts ASC
                """,
                (metadata_id,),
            ).fetchall()
            # Friendly name from override or entity_id
            entity_id_s = str(entity_id)
            if entity_id_s in name_overrides:
                name = name_overrides[entity_id_s]
            else:
                slug = entity_id_s.removeprefix("binary_sensor.")
                name = slug.replace("_", " ").strip().title()
            prev: str | None = None
            for raw_state, ts in rows:
                state = _normalize_contact_state(raw_state)
                if state is None or state == prev:
                    continue
                prev = state
                if await db.insert_door_event(
                    sensor_id=entity_id_s,
                    name=name,
                    state=state,
                    ts=float(ts),
                    source="ha-import",
                ):
                    inserted += 1
        return inserted
    finally:
        con.close()


def door_name_from_ha(
    entity_id: str,
    payload: dict[str, Any],
    *,
    overrides: dict[str, str] | None = None,
) -> str:
    """Pick a display name for a HA contact entity."""
    overrides = overrides or {}
    if entity_id in overrides:
        return overrides[entity_id]
    attrs = payload.get("attributes") or {}
    name = str(attrs.get("friendly_name") or "").strip()
    # Tuya door entities often look like "Porte cuisine Porte"
    if name.endswith(" Porte") and len(name) > 6:
        name = name[: -len(" Porte")].strip()
    if name:
        return name
    slug = str(entity_id).removeprefix("binary_sensor.")
    return slug.replace("_", " ").strip().title() or entity_id


class DoorHaPoller:
    """Poll Home Assistant REST for contact sensors not available on MQTT."""

    def __init__(self, db: Database, cfg: DoorsConfig) -> None:
        self.db = db
        self.cfg = cfg
        self._last_state: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.ha_token}",
            "Content-Type": "application/json",
        }

    async def _get_state(
        self, client: Any, entity_id: str
    ) -> dict[str, Any] | None:
        url = f"{self.cfg.ha_url}/api/states/{quote(entity_id, safe='')}"
        try:
            response = await client.get(url, headers=self._headers())
        except Exception as exc:
            logger.warning("HA door request failed for %s: %s", entity_id, exc)
            return None
        if response.status_code == 401:
            logger.error("HA rejected token (401) for door entity %s", entity_id)
            return None
        if response.status_code == 404:
            logger.warning("HA door entity not found: %s", entity_id)
            return None
        if response.status_code >= 400:
            logger.warning(
                "HA door error for %s: HTTP %s %s",
                entity_id,
                response.status_code,
                response.text[:200],
            )
            return None
        try:
            return response.json()
        except ValueError:
            logger.warning("HA non-JSON response for door entity %s", entity_id)
            return None

    async def _poll_once(self, client: Any) -> None:
        now = time.time()
        for entity_id in self.cfg.ha_entities:
            payload = await self._get_state(client, entity_id)
            if not payload:
                continue
            state = _normalize_contact_state(payload.get("state"))
            if state is None:
                continue
            name = door_name_from_ha(
                entity_id, payload, overrides=self.cfg.names
            )
            prev = self._last_state.get(entity_id)
            if prev == state:
                # Still refresh metadata / ensure row exists on first poll.
                if prev is not None:
                    continue
            inserted = await self.db.insert_door_event(
                sensor_id=entity_id,
                name=name,
                state=state,
                ts=now,
                source="ha",
            )
            self._last_state[entity_id] = state
            if inserted and prev is not None:
                logger.info("Door %s → %s (%s)", name, state, entity_id)
            elif prev is None:
                logger.info("Door %s initial %s (%s)", name, state, entity_id)

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self.cfg.ha_entities:
            return
        if not self.cfg.ha_token:
            logger.error(
                "Door HA poll enabled but no token "
                "(set doors.ha_token or doors.ha_token_file)"
            )
            return
        try:
            import httpx
        except ImportError:
            logger.error("Door HA poll requires httpx — pip install httpx")
            await stop_event.wait()
            return

        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info(
                "Door HA poller started (%d entit%s every %.0fs)",
                len(self.cfg.ha_entities),
                "y" if len(self.cfg.ha_entities) == 1 else "ies",
                self.cfg.ha_poll_seconds,
            )
            while not stop_event.is_set():
                try:
                    await self._poll_once(client)
                except Exception:
                    logger.exception("Door HA poll failed")
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.cfg.ha_poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass


def mqtt_url(cfg: DoorsConfig) -> str:
    """Diagnostic helper (password redacted)."""
    user = quote(cfg.mqtt_username, safe="") if cfg.mqtt_username else ""
    auth = f"{user}:***@" if user else ""
    return f"mqtt://{auth}{cfg.mqtt_host}:{cfg.mqtt_port}"
