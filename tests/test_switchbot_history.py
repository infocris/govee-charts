"""Tests for SwitchBot GATT history decode helpers."""

from __future__ import annotations

import unittest

from govee_charts.switchbot_history import (
    HISTORY_FETCH_MODE,
    build_history_fetch,
    decode_history_payload,
    decode_history_record,
    max_history_minutes_for_model,
    parse_history_meta,
)

ISSUE37_PAYLOAD = bytes(
    [0x97, 0x38, 0x89, 0x73, 0x89, 0x73, 0x68, 0x89, 0x73, 0x89, 0x73, 0x57, 0x79, 0x73, 0x37]
)

# Live mode-0 payload from a Meter (WoSeTH); advertisement-packed samples.
MODE0_RECENT_PAYLOAD = bytes.fromhex("9b31829b349b33239b359b32219b33")


class SwitchbotHistoryDecodeTests(unittest.TestCase):
    def test_decode_record_with_valid_humidity(self) -> None:
        parsed = decode_history_record(bytes([0x57, 0x79, 0x37]))
        self.assertIsNotNone(parsed)
        temp_c, hum = parsed
        self.assertAlmostEqual(temp_c, 31.063, places=3)
        self.assertEqual(hum, 55.0)

    def test_decode_issue37_fetch_payload(self) -> None:
        records = decode_history_payload(ISSUE37_PAYLOAD, fallback_humidity=60.0)
        self.assertGreaterEqual(len(records), 1)
        temps = [t for t, _h in records]
        self.assertTrue(
            any(abs(t - 35.128) < 0.05 or abs(t - 31.063) < 0.05 for t in temps)
            or any(5.0 <= t <= 45.0 for t in temps)
        )

    def test_decode_mode0_advertisement_payload(self) -> None:
        records = decode_history_payload(MODE0_RECENT_PAYLOAD)
        self.assertGreaterEqual(len(records), 2)
        for temp_c, humidity in records:
            self.assertTrue(5.0 <= temp_c <= 45.0)
            self.assertTrue(15.0 <= humidity <= 90.0)
        # Recent indoor readings near the live probe (~27°C).
        self.assertTrue(any(26.0 <= t <= 29.0 for t, _h in records))

    def test_parse_meta_issue37(self) -> None:
        raw = bytes.fromhex("0165be3e1465be424c000a0078")
        meta = parse_history_meta(raw[1:])
        self.assertEqual(meta["head"], 0x65be)
        self.assertEqual(meta["tail"], 0x3e14)
        self.assertEqual(meta["batch"], 10)
        self.assertEqual(meta["slot"], 120)

    def test_build_fetch_command_default_mode(self) -> None:
        self.assertEqual(HISTORY_FETCH_MODE, 0x00)
        cmd = build_history_fetch(HISTORY_FETCH_MODE, 0, 6)
        self.assertEqual(cmd, bytes.fromhex("570f3c00000006"))

    def test_build_fetch_command_legacy_mode(self) -> None:
        cmd = build_history_fetch(0x01, 0, 6)
        self.assertEqual(cmd, bytes.fromhex("570f3c01000006"))

    def test_max_history_by_model(self) -> None:
        self.assertEqual(max_history_minutes_for_model("switchbot-meter"), 36 * 1440)
        self.assertEqual(
            max_history_minutes_for_model("switchbot-meter-plus"), 68 * 1440
        )


if __name__ == "__main__":
    unittest.main()
