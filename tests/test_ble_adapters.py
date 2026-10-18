"""Adapter list merges BlueZ adapters, scanner config and per-adapter heartbeats."""

from __future__ import annotations

from govee_charts.ble_adapters import merge_adapters

NOW = 10_000.0
SYSTEM = [
    {"name": "hci0", "address": "98:FE:54:67:F5:A0", "powered": True, "discovering": True, "bus": "uart"},
    {"name": "hci1", "address": "5C:F3:70:8F:CD:56", "powered": True, "discovering": True, "bus": "usb"},
    {"name": "hci2", "address": "F4:4E:FC:9A:0A:B8", "powered": True, "discovering": False, "bus": "usb"},
]


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_status_per_configured_adapter():
    hb = {
        "ble_scan:hci0": NOW - 5, "ble_adv:hci0": NOW - 10,
        "ble_scan:hci1": NOW - 5, "ble_adv:hci1": NOW - 900,
        "ble_scan:hci9": NOW - 600,
    }
    rows = _by_name(
        merge_adapters(SYSTEM, ["hci0", "hci1", "hci9"], scanner_enabled=True, heartbeats=hb, now=NOW)
    )
    assert rows["hci0"]["status"] == "ok"
    assert rows["hci1"]["status"] == "silent"
    assert rows["hci2"]["status"] == "disabled" and not rows["hci2"]["enabled"]
    # Configured but unplugged: still listed so it can be unticked.
    assert rows["hci9"]["present"] is False and rows["hci9"]["status"] == "not_scanning"


def test_empty_config_means_first_adapter_with_default_heartbeats():
    hb = {"ble_scan:default": NOW - 5, "ble_adv:default": NOW - 5}
    rows = _by_name(merge_adapters(SYSTEM, [], scanner_enabled=True, heartbeats=hb, now=NOW))
    assert rows["hci0"]["enabled"] and rows["hci0"]["status"] == "ok"
    assert not rows["hci1"]["enabled"]


def test_scanner_off_and_no_bluez_listing():
    rows = merge_adapters(None, [], scanner_enabled=False, heartbeats={}, now=NOW)
    assert rows == [
        {"name": "default", "present": True, "enabled": True, "last_scan_ts": None,
         "last_adv_ts": None, "status": "disabled"}
    ]
