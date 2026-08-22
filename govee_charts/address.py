"""Canonical BLE MAC resolution for cross-platform device identity."""

from __future__ import annotations

import re

# Govee local names embed the last two MAC octets as hex (e.g. GVH5075_1270 → …:12:70).
GOVEE_NAME_SUFFIX_RE = re.compile(
    r"^(?:GVH5075|Govee_H5179|GVH5177|GV5179)_([0-9A-Fa-f]{4})$"
)
BLE_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.IGNORECASE)


def is_ble_mac(address: str) -> bool:
    return bool(BLE_MAC_RE.fullmatch(address.strip()))


def is_ha_device_id(address: str) -> bool:
    return address.strip().upper().startswith("HA:")


def is_federated_device_address(address: str) -> bool:
    """True for addresses peers may ingest (BLE MAC or HA:… synthetic ids)."""
    addr = address.strip().upper()
    return is_ble_mac(addr) or is_ha_device_id(addr)


def name_mac_suffix(name: str) -> str | None:
    if not name:
        return None
    match = GOVEE_NAME_SUFFIX_RE.match(name.strip())
    return match.group(1).upper() if match else None


def mac_address_suffix(mac: str) -> str:
    parts = mac.strip().upper().replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"Invalid MAC: {mac!r}")
    return parts[4] + parts[5]


def build_suffix_map(labels: dict[str, str] | None = None) -> dict[str, str]:
    """Map 4-char Govee name suffix → canonical MAC from label keys."""
    result: dict[str, str] = {}
    for mac in labels or {}:
        mac_up = mac.strip().upper()
        if not is_ble_mac(mac_up):
            continue
        try:
            result[mac_address_suffix(mac_up)] = mac_up
        except ValueError:
            continue
    return result


def register_mac(suffix_map: dict[str, str], address: str) -> None:
    """Record a seen MAC so UUID-only peers can resolve the same device later."""
    address = address.strip().upper()
    if not is_ble_mac(address):
        return
    try:
        suffix_map[mac_address_suffix(address)] = address
    except ValueError:
        return


def resolve_device_address(
    address: str,
    name: str,
    *,
    suffix_map: dict[str, str] | None = None,
) -> str:
    """Return canonical BLE MAC when known, else uppercased platform address."""
    address = address.strip().upper()
    if is_ble_mac(address):
        return address

    suffix = name_mac_suffix(name)
    if suffix and suffix_map and suffix in suffix_map:
        return suffix_map[suffix]

    return address
