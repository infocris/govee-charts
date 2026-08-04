"""Decode Govee BLE manufacturer payloads (H5075 / H5179)."""

from __future__ import annotations

from dataclasses import dataclass

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from govee_charts.address import resolve_device_address

# Govee manufacturer company IDs (as exposed by bleak)
GOVEE_H5075_MFG_ID = 0xEC88  # H5075 / H5072
GOVEE_H5179_MFG_ID = 0x8801  # Legacy H5179
# Newer H5179 firmware (e.g. 1.00.x / HW 3.x) advertises as company 0x0001
# with the H5101-style packed payload and local name GV5179_XXXX.
GOVEE_H5179_NEW_MFG_ID = 0x0001
GOVEE_EC88_UUID_HINT = "ec88"


@dataclass(frozen=True)
class Reading:
    temperature_c: float
    humidity: float
    battery: int
    address: str
    name: str
    model: str
    rssi: int | None


def decode_h5075(payload: bytes) -> tuple[float, float, int] | None:
    """Decode H5075 manufacturer payload → (temp_c, humidity, battery)."""
    if len(payload) < 5:
        return None

    packed = int.from_bytes(payload[1:4], "big")
    negative = (packed & 0x800000) != 0
    packed &= 0x7FFFFF

    humidity_raw = packed % 1000
    humidity = humidity_raw / 10.0
    temperature = (packed - humidity_raw) / 10000.0
    if negative:
        temperature = -temperature

    battery = int(payload[4])
    if not (-40.0 <= temperature <= 60.0 and 0.0 <= humidity <= 100.0):
        return None
    if not (0 <= battery <= 100):
        return None
    return temperature, humidity, battery


def decode_h5179(payload: bytes) -> tuple[float, float, int] | None:
    """Decode legacy H5179 manufacturer payload (bleak, company ID already stripped).

    Layout (9 bytes): [0:4] unknown · [4:6] temp int16 LE /100 ·
    [6:8] humidity uint16 LE /100 · [8] battery %
    """
    if len(payload) < 9:
        return None

    temp_raw = int.from_bytes(payload[4:6], "little", signed=True)
    humidity_raw = int.from_bytes(payload[6:8], "little", signed=False)
    battery = int(payload[8])

    temperature = temp_raw / 100.0
    humidity = humidity_raw / 100.0
    if not (-40.0 <= temperature <= 60.0 and 0.0 <= humidity <= 100.0):
        return None
    if not (0 <= battery <= 100):
        return None
    return temperature, humidity, battery


def decode_h5179_new(payload: bytes) -> tuple[float, float, int] | None:
    """Decode newer H5179 firmware (company 0x0001, same packing as H5101/H5177).

    Bleak payload (company ID stripped), typically 6 bytes:
    [0:2] header · [2:5] packed temp/humidity big-endian · [5] battery.
    Matches govee-ble ``decode_temp_humid_battery_error(data[2:6])``.
    """
    if len(payload) < 6:
        return None

    chunk = payload[2:6]
    packed = int.from_bytes(chunk[0:3], "big")
    negative = (packed & 0x800000) != 0
    packed &= 0x7FFFFF
    humidity_raw = packed % 1000
    humidity = humidity_raw / 10.0
    temperature = int(packed / 1000) / 10.0
    if negative:
        temperature = -temperature
    battery = int(chunk[3] & 0x7F)
    if chunk[3] & 0x80:
        return None
    if not (-40.0 <= temperature <= 60.0 and 0.0 <= humidity <= 100.0):
        return None
    if not (0 <= battery <= 100):
        return None
    return temperature, humidity, battery


def _adv_name(adv: AdvertisementData, name: str | None = None) -> str:
    if name:
        return str(name)
    local = getattr(adv, "local_name", None)
    return str(local or "")


def _has_ec88_uuid(adv: AdvertisementData) -> bool:
    for uuid in adv.service_uuids or []:
        if GOVEE_EC88_UUID_HINT in str(uuid).lower():
            return True
    return False


def detect_model(adv: AdvertisementData, name: str | None = None) -> str | None:
    """Return 'h5179' / 'h5179_new' / 'h5075' if manufacturer data matches."""
    mfg = adv.manufacturer_data or {}
    if GOVEE_H5179_MFG_ID in mfg:
        return "h5179"
    if GOVEE_H5075_MFG_ID in mfg:
        return "h5075"
    # Company 0x0001 is shared by many devices — require GV5179 name or ec88 UUID.
    if GOVEE_H5179_NEW_MFG_ID in mfg:
        label = _adv_name(adv, name).upper()
        if "GV5179" in label or "H5179" in label or _has_ec88_uuid(adv):
            return "h5179_new"
    return None


def advertisement_rssi(
    device: BLEDevice,
    adv: AdvertisementData,
) -> int | None:
    """RSSI from advertisement (bleak 3.x) or device (bleak 0.18.x on Linux)."""
    adv_rssi = getattr(adv, "rssi", None)
    if adv_rssi is not None:
        return int(adv_rssi)
    device_rssi = getattr(device, "rssi", None)
    if device_rssi is None or device_rssi == 0:
        return None
    return int(device_rssi)


def decode_advertisement(
    address: str,
    name: str,
    adv: AdvertisementData,
    *,
    device: BLEDevice | None = None,
    suffix_map: dict[str, str] | None = None,
) -> Reading | None:
    """Decode a BLE advertisement into a Reading, or None if not a known Govee sensor."""
    model = detect_model(adv, name)
    if model is None:
        return None

    mfg = adv.manufacturer_data or {}
    if model == "h5179":
        values = decode_h5179(bytes(mfg[GOVEE_H5179_MFG_ID]))
        store_model = "h5179"
    elif model == "h5179_new":
        values = decode_h5179_new(bytes(mfg[GOVEE_H5179_NEW_MFG_ID]))
        store_model = "h5179"
    else:
        values = decode_h5075(bytes(mfg[GOVEE_H5075_MFG_ID]))
        store_model = "h5075"

    if values is None:
        return None

    temp, humidity, battery = values
    if device is not None:
        rssi = advertisement_rssi(device, adv)
    else:
        rssi = getattr(adv, "rssi", None)
        rssi = int(rssi) if rssi is not None else None
    ble_name = name or address.upper()
    canonical = resolve_device_address(address, ble_name, suffix_map=suffix_map)
    return Reading(
        temperature_c=temp,
        humidity=humidity,
        battery=battery,
        address=canonical,
        name=ble_name,
        model=store_model,
        rssi=rssi,
    )
