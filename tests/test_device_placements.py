from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from govee_charts.db import Database
from govee_charts.decode import Reading


class DevicePlacementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "readings.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)

    async def _seed_device(
        self,
        address: str = "AA:BB:CC:DD:EE:FF",
        *,
        label: str | None = "Bedroom",
        room: str | None = "bedroom",
        ts: float | None = None,
    ) -> None:
        when = float(ts if ts is not None else time.time())
        reading = Reading(
            temperature_c=20.0,
            humidity=50.0,
            battery=90,
            address=address,
            name="GVH5075_EEFF",
            model="h5075",
            rssi=-60,
        )
        await self.db.upsert_reading(reading, "GVH5075_EEFF", ts=when)
        await self.db.update_device_categories(
            address, label=label, room=room, zone="interior", height="mid"
        )

    async def test_migration_creates_open_placement(self) -> None:
        await self._seed_device()
        placements = await self.db.list_placements("AA:BB:CC:DD:EE:FF")
        self.assertEqual(len(placements), 1)
        self.assertIsNone(placements[0]["valid_until"])
        self.assertEqual(placements[0]["room"], "bedroom")

    async def test_resolve_placement_is_retroactive(self) -> None:
        t0 = time.time() - 7200
        await self._seed_device(ts=t0)
        split_at = time.time() - 3600
        await self.db.add_placement(
            "AA:BB:CC:DD:EE:FF",
            effective_from=split_at,
            room="kitchen",
            label="Kitchen",
        )
        old = await self.db.resolve_placement("AA:BB:CC:DD:EE:FF", t0 + 10)
        new = await self.db.resolve_placement("AA:BB:CC:DD:EE:FF", time.time())
        self.assertIsNotNone(old)
        self.assertIsNotNone(new)
        assert old is not None and new is not None
        self.assertEqual(old["room"], "bedroom")
        self.assertEqual(new["room"], "kitchen")

    async def test_update_current_placement_via_categories(self) -> None:
        await self._seed_device(label="Old name")
        updated = await self.db.update_device_categories(
            "AA:BB:CC:DD:EE:FF", label="New name"
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["label"], "New name")
        current = await self.db.get_current_placement("AA:BB:CC:DD:EE:FF")
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current["label"], "New name")

    async def test_overlapping_placement_patch_rejected(self) -> None:
        await self._seed_device()
        placements = await self.db.list_placements("AA:BB:CC:DD:EE:FF")
        pid = placements[0]["id"]
        with self.assertRaises(ValueError):
            await self.db.update_placement(
                pid,
                valid_from=time.time() + 3600,
                valid_until=time.time() - 3600,
            )

    async def test_list_room_chart_sensors_former(self) -> None:
        t0 = time.time() - 7200
        await self._seed_device(ts=t0)
        split_at = time.time() - 3600
        await self.db.add_placement(
            "AA:BB:CC:DD:EE:FF",
            effective_from=split_at,
            room="kitchen",
            label="Kitchen",
        )
        now = time.time()
        bedroom_only = await self.db.list_room_chart_sensors(
            "bedroom",
            since=now - 7200,
            until=now,
            include_former=False,
        )
        self.assertEqual(len(bedroom_only), 0)
        bedroom_former = await self.db.list_room_chart_sensors(
            "bedroom",
            since=now - 7200,
            until=now,
            include_former=True,
        )
        self.assertEqual(len(bedroom_former), 1)
        self.assertTrue(bedroom_former[0]["former"])
        self.assertLess(bedroom_former[0]["chart_until"], split_at + 1)
        kitchen_current = await self.db.list_room_chart_sensors(
            "kitchen",
            since=now - 7200,
            until=now,
            include_former=False,
        )
        self.assertEqual(len(kitchen_current), 1)
        self.assertTrue(kitchen_current[0]["current"])

    async def test_list_room_chart_sensors_includes_exterior(self) -> None:
        t0 = time.time() - 7200
        await self._seed_device(ts=t0, room="kitchen")
        await self.db.update_device_categories(
            "AA:BB:CC:DD:EE:FF",
            zone="exterior",
            height="high",
            label="Cuisine Ext Haut",
            room="kitchen",
        )
        split_at = time.time() - 3600
        await self.db.add_placement(
            "AA:BB:CC:DD:EE:FF",
            effective_from=split_at,
            room="bedroom",
            zone="interior",
            label="Bedroom",
        )
        now = time.time()
        kitchen_former = await self.db.list_room_chart_sensors(
            "kitchen",
            since=now - 7200,
            until=now,
            include_former=True,
        )
        self.assertEqual(len(kitchen_former), 1)
        self.assertEqual(kitchen_former[0].get("zone"), "exterior")
        self.assertTrue(kitchen_former[0]["former"])

    async def test_plan_position_on_placement(self) -> None:
        await self._seed_device(room="kitchen")
        placement = await self.db.get_current_placement("AA:BB:CC:DD:EE:FF")
        self.assertIsNotNone(placement)
        assert placement is not None
        updated = await self.db.update_placement(
            placement["id"],
            plan_wall="n",
            plan_u=0.25,
            plan_v=0.1,
        )
        assert updated is not None
        self.assertEqual(updated["plan_wall"], "n")
        self.assertAlmostEqual(updated["plan_u"], 0.25)
        device = await self.db.get_device("AA:BB:CC:DD:EE:FF")
        assert device is not None
        self.assertEqual(device["plan_wall"], "n")


if __name__ == "__main__":
    unittest.main()
