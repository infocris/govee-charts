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


if __name__ == "__main__":
    unittest.main()
