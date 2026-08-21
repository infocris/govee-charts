"""Decode SwitchBot Meter family BLE advertisements (Meter Plus, etc.)."""

from __future__ import annotations

import time
from typing import Any

from bleak.backends.scanner import AdvertisementData

SWITCHBOT_MFG_ID = 0x0969
SWITCHBOT_FD3D_UUID = "0000fd3d-0000-1000-8000-00805f9b34fb"

# Device-type bytes in 0xFD3D service data (ASCII, bit7 masked).
_METER_TYPES: dict[int, str] = {
    ord("T"): "switchbot-meter",
    ord("i"): "switchbot-meter-plus",
    ord("4"): "switchbot-meter-pro",
    ord("5"): "switchbot-meter-pro-co2",
    ord("w"): "switchbot-meter-outdoor",
}

_TYPE_CACHE_TTL_S = 300.0
_type_cache: dict[str, tuple[int, float]] = {}


def _fd3d_payload(adv: AdvertisementData) -> bytes | None:
    sd = adv.service_data or {}
    for key, raw in sd.items():
        if "fd3d" in str(key).lower():
            return bytes(raw)
    return None


def _switchbot_mfg_payload(adv: AdvertisementData) -> bytes | None:
    mfg = adv.manufacturer_data or {}
    for cid, raw in mfg.items():
        if int(cid) & 0xFFFF == SWITCHBOT_MFG_ID:
            return bytes(raw)
    return None


def mac_from_manufacturer(adv: AdvertisementData) -> str | None:
    """Extract the real BLE MAC from SwitchBot 0x0969 manufacturer data.

    On macOS, CoreBluetooth exposes UUID peripherals; SwitchBot still embeds the
    MAC as the first 6 bytes of company-id 0x0969 payload (after Bleak strips
    the company id itself).
    """
    mfg = _switchbot_mfg_payload(adv)
    if mfg is None or len(mfg) < 6:
        return None
    mac_bytes = mfg[:6]
    if mac_bytes == b"\x00" * 6:
        return None
    return ":".join(f"{b:02X}" for b in mac_bytes)


def is_switchbot_meter_type(dev_type: int) -> bool:
    return (dev_type & 0x7F) in _METER_TYPES


def meter_model_for_type(dev_type: int) -> str | None:
    return _METER_TYPES.get(dev_type & 0x7F)


def _cache_type(address: str, dev_type: int) -> None:
    _type_cache[address.upper()] = (dev_type & 0x7F, time.time())


def _cached_type(address: str) -> int | None:
    entry = _type_cache.get(address.upper())
    if entry is None:
        return None
    dev_type, seen = entry
    if time.time() - seen > _TYPE_CACHE_TTL_S:
        _type_cache.pop(address.upper(), None)
        return None
    return dev_type


def resolve_meter_type(address: str, adv: AdvertisementData) -> int | None:
    """Return SwitchBot meter device-type byte, using a short-lived per-MAC cache."""
    svc = _fd3d_payload(adv)
    if svc:
        dev_type = svc[0] & 0x7F
        if is_switchbot_meter_type(dev_type):
            _cache_type(address, dev_type)
            return dev_type
        return None
    return _cached_type(address)


def decode_temp_humidity(block: bytes) -> tuple[float, float] | None:
    """Shared 3-byte SwitchBot temp/hum block."""
    if len(block) < 3:
        return None
    frac = block[0] & 0x0F
    temp_int = block[1] & 0x7F
    hum = block[2] & 0x7F
    positive = (block[1] & 0x80) != 0
    if frac > 9 or hum > 100:
        return None
    tenths = temp_int * 10 + frac
    max_tenths = 800 if positive else 400
    if tenths > max_tenths:
        return None
    temp_c = tenths / 10.0 if positive else -tenths / 10.0
    if not (-40.0 <= temp_c <= 60.0):
        return None
    return temp_c, float(hum)


def decode_switchbot_advertisement(
    address: str,
    name: str,
    adv: AdvertisementData,
) -> dict[str, Any] | None:
    """Decode a SwitchBot Meter-family advertisement into reading fields."""
    mac = mac_from_manufacturer(adv)
    # Prefer the embedded MAC for type cache so split ADV/SCAN_RSP pairs still
    # match after macOS UUID→MAC resolution.
    lookup = mac or address
    dev_type = resolve_meter_type(lookup, adv)
    if dev_type is None and mac and mac.upper() != address.upper():
        # Service-data-only packet may have been cached under the platform UUID.
        dev_type = resolve_meter_type(address, adv)
        if dev_type is not None:
            _cache_type(mac, dev_type)
    if dev_type is None:
        return None

    model = meter_model_for_type(dev_type)
    if model is None:
        return None

    temp: float | None = None
    humidity: float | None = None
    battery: int | None = None

    svc = _fd3d_payload(adv)
    if svc and len(svc) >= 3:
        batt = svc[2] & 0x7F
        if 0 <= batt <= 100:
            battery = int(batt)
        if dev_type in (ord("T"), ord("i")) and len(svc) >= 6:
            parsed = decode_temp_humidity(svc[3:6])
            if parsed:
                temp, humidity = parsed

    mfg = _switchbot_mfg_payload(adv)
    if mfg and len(mfg) >= 11:
        parsed = decode_temp_humidity(mfg[8:11])
        if parsed:
            temp, humidity = parsed

    if temp is None or humidity is None:
        return None

    canonical = mac or address
    label = (name or "").strip()
    if not label:
        short = {
            "switchbot-meter-plus": "MeterPlus",
            "switchbot-meter": "Meter",
            "switchbot-meter-pro": "MeterPro",
            "switchbot-meter-pro-co2": "MeterProCO2",
            "switchbot-meter-outdoor": "MeterOutdoor",
        }.get(model or "", "SwitchBot")
        suffix = canonical.replace(":", "")[-4:].upper()
        label = f"{short}-{suffix}"

    return {
        "temperature_c": temp,
        "humidity": humidity,
        "battery": battery if battery is not None else 0,
        "model": model,
        "name": label,
        "mac": mac,
    }
