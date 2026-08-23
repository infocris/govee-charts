"""Tests for SwitchBot GATT history decode helpers."""

from __future__ import annotations

import unittest

from govee_charts.switchbot_history import (
    build_history_fetch,
    decode_history_payload,
    decode_history_record,
    max_history_minutes_for_model,
    parse_history_meta,
)

ISSUE37_PAYLOAD = bytes(
    [0x97, 0x38, 0x89, 0x73, 0x89, 0x73, 0x68, 0x89, 0x73, 0x89, 0x73, 0x57, 0x79, 0x73, 0x37]
)


class SwitchbotHistoryDecodeTests(unittest.TestCase):
    def test_decode_record_with_valid_humidity(self) -> None:
        parsed = decode_history_record(bytes([0x57, 0x79, 0x37]))
        self.assertIsNotNone(parsed)
        temp_c, hum = parsed
        self.assertAlmostEqual(temp_c, 31.063, places=3)
        self.assertEqual(hum, 55.0)

    def test_decode_issue37_fetch_payload(self) -> None:
        records = decode_history_payload(ISSUE37_PAYLOAD, fallback_humidity=60.0)
        self.assertEqual(len(records), 5)
        self.assertAlmostEqual(records[0][0], 35.128, places=2)
        self.assertEqual(records[0][1], 60.0)
        self.assertAlmostEqual(records[1][0], 29.577, places=2)

    def test_parse_meta_issue37(self) -> None:
        raw = bytes.fromhex("0165be3e1465be424c000a0078")
        meta = parse_history_meta(raw[1:])
        self.assertEqual(meta["head"], 0x65be)
        self.assertEqual(meta["tail"], 0x3e14)
        self.assertEqual(meta["batch"], 10)
        self.assertEqual(meta["slot"], 120)

    def test_build_fetch_command(self) -> None:
        cmd = build_history_fetch(0x01, 0, 6)
        self.assertEqual(cmd, bytes.fromhex("570f3c01000006"))

    def test_max_history_by_model(self) -> None:
        self.assertEqual(max_history_minutes_for_model("switchbot-meter"), 36 * 1440)
        self.assertEqual(
            max_history_minutes_for_model("switchbot-meter-plus"), 68 * 1440
        )


if __name__ == "__main__":
    unittest.main()
