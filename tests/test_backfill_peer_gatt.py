"""Tests for peer GATT election helpers."""

from __future__ import annotations

import unittest

from govee_charts.backfill import peer_can_run_gatt


class PeerCanRunGattTests(unittest.TestCase):
    def test_missing_backfill_payload_assumes_yes(self) -> None:
        self.assertTrue(peer_can_run_gatt({"ok": True}, "AA:BB"))

    def test_gatt_disabled_on_peer(self) -> None:
        peer = {
            "backfill": {
                "EC:6F:05:C6:28:6D": {"enabled": True, "gatt_enabled": False},
            }
        }
        self.assertFalse(peer_can_run_gatt(peer, "EC:6F:05:C6:28:6D"))

    def test_backfill_disabled_on_peer(self) -> None:
        peer = {
            "backfill": {
                "EC:6F:05:C6:28:6D": {"enabled": False, "gatt_enabled": True},
            }
        }
        self.assertFalse(peer_can_run_gatt(peer, "ec:6f:05:c6:28:6d"))

    def test_unknown_device_on_peer(self) -> None:
        peer = {"backfill": {}}
        self.assertFalse(peer_can_run_gatt(peer, "AA:BB:CC:DD:EE:FF"))

    def test_gatt_enabled(self) -> None:
        peer = {
            "backfill": {
                "CE:2A:82:06:62:3D": {"enabled": True, "gatt_enabled": True},
            }
        }
        self.assertTrue(peer_can_run_gatt(peer, "CE:2A:82:06:62:3D"))


if __name__ == "__main__":
    unittest.main()
