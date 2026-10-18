"""Windowed scans drop cached BlueZ devices once BlueZ itself has forgotten them."""

from __future__ import annotations

import sys
import time

import pytest

from govee_charts.scanner import GoveeScanner

MAC = "A4:C1:38:F4:2E:08"


def _seen(s: GoveeScanner, age: float) -> object:
    device = object()
    s._ble_devices[MAC] = (device, time.time() - age)
    return device


def test_continuous_scan_keeps_cache():
    s = GoveeScanner(None)
    device = _seen(s, 120.0)
    assert s.get_ble_device(MAC) is device


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="BlueZ only")
def test_windowed_scan_expires_cache_on_bluez():
    s = GoveeScanner(None, scan_window=30.0)
    device = _seen(s, 5.0)
    assert s.get_ble_device(MAC) is device
    _seen(s, 120.0)
    assert s.get_ble_device(MAC) is None


def test_adapter_lookup_defaults_to_none():
    s = GoveeScanner(None)
    assert s.get_ble_adapter(MAC) is None
    s._ble_adapters[MAC] = "hci1"
    assert s.get_ble_adapter(MAC.lower()) == "hci1"
