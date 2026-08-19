from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from govee_charts.db import Database
from govee_charts.decode import Reading


class DeviceCrudTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "readings.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)

    async def test_manual_create_and_list(self) -> None:
        device = await self.db.create_device(
            "11:22:33:44:55:66",
            model="h5075",
            label="Manual",
            room="living",
        )
        self.assertEqual(device["address"], "11:22:33:44:55:66")
        self.assertEqual(device["label"], "Manual")
        listed = await self.db.list_devices(include_stats=False)
        self.assertEqual(len(listed), 1)

    async def test_archive_hides_from_default_list(self) -> None:
        await self.db.create_device("11:22:33:44:55:66", label="To archive")
        archived = await self.db.archive_device("11:22:33:44:55:66")
        self.assertIsNotNone(archived)
        assert archived is not None
        self.assertIsNotNone(archived.get("archived_at"))
        active = await self.db.list_devices(include_stats=False)
        self.assertEqual(len(active), 0)
        all_devices = await self.db.list_devices(
            include_stats=False, include_archived=True
        )
        self.assertEqual(len(all_devices), 1)

    async def test_purge_removes_device_and_readings(self) -> None:
        await self.db.create_device("11:22:33:44:55:66", label="Purge me")
        reading = Reading(
            temperature_c=21.0,
            humidity=45.0,
            battery=80,
            address="11:22:33:44:55:66",
            name="GVH5075_5566",
            model="h5075",
            rssi=-70,
        )
        await self.db.upsert_reading(reading, "GVH5075_5566")
        ok = await self.db.purge_device("11:22:33:44:55:66")
        self.assertTrue(ok)
        self.assertIsNone(
            await self.db.get_device("11:22:33:44:55:66", include_archived=True)
        )
        history = await self.db.history("11:22:33:44:55:66", hours=24)
        self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
