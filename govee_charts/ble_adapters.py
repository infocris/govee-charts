"""List the host's Bluetooth adapters and combine them with scanner status.

On Linux, BlueZ exposes each controller (``hci0``, ``hci1``, …) on D-Bus as
``org.bluez.Adapter1``. Elsewhere (macOS CoreBluetooth) there is a single
implicit adapter, reported as ``default``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ADAPTER = "default"
_DBUS_TIMEOUT = 3.0
# Workers refresh per-adapter heartbeats at most every ADAPTER_HB_INTERVAL.
ADAPTER_HB_INTERVAL = 15.0
_SCAN_FRESH_S = 3 * ADAPTER_HB_INTERVAL
_ADV_FRESH_S = 180.0


def scan_heartbeat_key(adapter: str | None) -> str:
    return f"ble_scan:{adapter or DEFAULT_ADAPTER}"


def adv_heartbeat_key(adapter: str | None) -> str:
    return f"ble_adv:{adapter or DEFAULT_ADAPTER}"


def _bus_type(name: str) -> str | None:
    try:
        path = os.path.realpath(f"/sys/class/bluetooth/{name}/device")
    except OSError:
        return None
    if "/usb" in path:
        return "usb"
    if os.path.exists(path):
        return "uart"
    return None


async def list_system_adapters() -> list[dict[str, Any]] | None:
    """BlueZ adapters sorted by name, or None when BlueZ cannot be queried."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus
    except ImportError:
        return None
    bus = None
    try:
        bus = await asyncio.wait_for(
            MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=_DBUS_TIMEOUT
        )
        intro = await asyncio.wait_for(
            bus.introspect("org.bluez", "/"), timeout=_DBUS_TIMEOUT
        )
        manager = bus.get_proxy_object("org.bluez", "/", intro).get_interface(
            "org.freedesktop.DBus.ObjectManager"
        )
        objects = await asyncio.wait_for(
            manager.call_get_managed_objects(), timeout=_DBUS_TIMEOUT
        )
    except Exception as exc:
        logger.warning("Could not list BlueZ adapters: %s", exc)
        return None
    finally:
        if bus is not None:
            bus.disconnect()
    adapters: list[dict[str, Any]] = []
    for path, ifaces in objects.items():
        props = ifaces.get("org.bluez.Adapter1")
        if props is None:
            continue
        name = path.rsplit("/", 1)[-1]

        def val(key: str) -> Any:
            v = props.get(key)
            return getattr(v, "value", v)

        adapters.append(
            {
                "name": name,
                "address": val("Address"),
                "alias": val("Alias"),
                "powered": bool(val("Powered")),
                "discovering": bool(val("Discovering")),
                "bus": _bus_type(name),
            }
        )
    adapters.sort(key=lambda a: a["name"])
    return adapters


def adapter_status(
    *,
    configured: bool,
    scanner_enabled: bool,
    scan_ts: float | None,
    adv_ts: float | None,
    now: float | None = None,
) -> str:
    """One word for the UI: disabled / ok / silent / not_scanning."""
    if not configured or not scanner_enabled:
        return "disabled"
    now = time.time() if now is None else now
    if scan_ts is None or now - scan_ts > _SCAN_FRESH_S:
        return "not_scanning"
    if adv_ts is None or now - adv_ts > _ADV_FRESH_S:
        return "silent"
    return "ok"


def merge_adapters(
    system: list[dict[str, Any]] | None,
    configured: list[str],
    *,
    scanner_enabled: bool,
    heartbeats: dict[str, float | None],
    now: float | None = None,
) -> list[dict[str, Any]]:
    """System adapters plus configured ones BlueZ does not list (unplugged).

    An empty ``configured`` list means "system default adapter": on Linux
    that is the first BlueZ adapter, elsewhere the implicit ``default``.
    """
    rows: dict[str, dict[str, Any]] = {}
    for a in system or []:
        rows[a["name"]] = {**a, "present": True}
    if system is None and not rows:
        rows[DEFAULT_ADAPTER] = {"name": DEFAULT_ADAPTER, "present": True}
    if configured:
        active = set(configured)
    elif system:
        active = {system[0]["name"]}
    else:
        active = {DEFAULT_ADAPTER}
    for name in configured:
        rows.setdefault(name, {"name": name, "present": False})
    out: list[dict[str, Any]] = []
    for name in sorted(rows):
        row = rows[name]
        # Heartbeats use the configured label (``default`` when list is empty).
        hb_label = name if configured else DEFAULT_ADAPTER
        scan_ts = heartbeats.get(scan_heartbeat_key(hb_label))
        adv_ts = heartbeats.get(adv_heartbeat_key(hb_label))
        is_on = name in active
        out.append(
            {
                **row,
                "enabled": is_on,
                "last_scan_ts": scan_ts if is_on else None,
                "last_adv_ts": adv_ts if is_on else None,
                "status": adapter_status(
                    configured=is_on,
                    scanner_enabled=scanner_enabled,
                    scan_ts=scan_ts,
                    adv_ts=adv_ts,
                    now=now,
                ),
            }
        )
    return out
