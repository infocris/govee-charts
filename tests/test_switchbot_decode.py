from __future__ import annotations

import unittest
from types import SimpleNamespace

from govee_charts.decode import decode_advertisement
from govee_charts.switchbot_decode import (
    decode_switchbot_advertisement,
    decode_temp_humidity,
    meter_model_for_type,
    resolve_meter_type,
)


def _adv(
    *,
    mfg: dict[int, bytes] | None = None,
    service_data: dict[str, bytes] | None = None,
    local_name: str = "",
    rssi: int = -65,
) -> SimpleNamespace:
    return SimpleNamespace(
        manufacturer_data=mfg or {},
        service_data=service_data or {},
        service_uuids=list((service_data or {}).keys()),
        local_name=local_name,
        rssi=rssi,
    )


class SwitchBotDecodeTests(unittest.TestCase):
    def test_meter_plus_live_capture(self) -> None:
        """Payload captured from EC:6F:05:C6:28:6D on 2026-08-19."""
        mfg = bytes.fromhex("ec6f05c6286d050f059a38")
        svc = bytes.fromhex("69c0e4059a38")
        adv = _adv(
            mfg={0x0969: mfg},
            service_data={
                "0000fd3d-0000-1000-8000-00805f9b34fb": svc,
            },
        )
        out = decode_switchbot_advertisement("EC:6F:05:C6:28:6D", "", adv)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["model"], "switchbot-meter-plus")
        self.assertAlmostEqual(out["temperature_c"], 26.5, places=1)
        self.assertAlmostEqual(out["humidity"], 56.0, places=1)

    def test_meter_live_capture(self) -> None:
        """Payload captured from CE:2A:82:06:62:3D on 2026-08-19."""
        mfg = bytes.fromhex("ce2a8206623d0703069c32")
        svc = bytes.fromhex("5400e4069c32")
        adv = _adv(
            mfg={0x0969: mfg},
            service_data={
                "0000fd3d-0000-1000-8000-00805f9b34fb": svc,
            },
        )
        out = decode_switchbot_advertisement("CE:2A:82:06:62:3D", "", adv)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["model"], "switchbot-meter")
        self.assertAlmostEqual(out["temperature_c"], 28.6, places=1)
        self.assertAlmostEqual(out["humidity"], 50.0, places=1)

    def test_meter_outdoor_live_capture(self) -> None:
        """Payload captured from D5:3A:44:06:3D:91 on 2026-08-19."""
        mfg = bytes.fromhex("d53a44063d910d0e019a2c00")
        svc = bytes.fromhex("77c0e4")
        adv = _adv(
            mfg={0x0969: mfg},
            service_data={
                "0000fd3d-0000-1000-8000-00805f9b34fb": svc,
            },
        )
        out = decode_switchbot_advertisement("D5:3A:44:06:3D:91", "", adv)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["model"], "switchbot-meter-outdoor")
        self.assertAlmostEqual(out["temperature_c"], 26.1, places=1)
        self.assertAlmostEqual(out["humidity"], 44.0, places=1)

    def test_temp_hum_block(self) -> None:
        parsed = decode_temp_humidity(bytes.fromhex("059a38"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertAlmostEqual(parsed[0], 26.5, places=1)
        self.assertEqual(parsed[1], 56.0)

    def test_type_cache_across_split_advertisement(self) -> None:
        svc = bytes.fromhex("69c0e4059a38")
        adv_type = _adv(
            service_data={
                "0000fd3d-0000-1000-8000-00805f9b34fb": svc,
            },
        )
        addr = "EC:6F:05:C6:28:6D"
        self.assertEqual(resolve_meter_type(addr, adv_type), ord("i"))
        self.assertEqual(meter_model_for_type(ord("i")), "switchbot-meter-plus")

        mfg = bytes.fromhex("ec6f05c6286d050f059a38")
        adv_mfg = _adv(mfg={0x0969: mfg})
        self.assertEqual(resolve_meter_type(addr, adv_mfg), ord("i"))
        out = decode_switchbot_advertisement(addr, "", adv_mfg)
        self.assertIsNotNone(out)

    def test_decode_advertisement_integration(self) -> None:
        mfg = bytes.fromhex("ec6f05c6286d050f059a38")
        svc = bytes.fromhex("69c0e4059a38")
        adv = _adv(
            mfg={0x0969: mfg},
            service_data={
                "0000fd3d-0000-1000-8000-00805f9b34fb": svc,
            },
        )
        reading = decode_advertisement("EC:6F:05:C6:28:6D", "", adv)
        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.model, "switchbot-meter-plus")
        self.assertEqual(reading.address, "EC:6F:05:C6:28:6D")


if __name__ == "__main__":
    unittest.main()
