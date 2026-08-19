from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from govee_charts.db import Database
from govee_charts.decode import Reading


class BleDiscoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "readings.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)

    def _reading(self, address: str = "AA:BB:CC:DD:EE:01") -> Reading:
        return Reading(
            temperature_c=21.5,
            humidity=44.0,
            battery=88,
            address=address,
            name="GVH5075_EE01",
            model="h5075",
            rssi=-62,
        )

    async def test_list_ble_discover_candidates_marks_unknown(self) -> None:
        await self.db.upsert_ble_nearby(self._reading())
        rows = await self.db.list_ble_discover_candidates(since_ts=time.time() - 60)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["unknown"])

        await self.db.create_device("AA:BB:CC:DD:EE:01", label="Known")
        rows = await self.db.list_ble_discover_candidates(since_ts=time.time() - 60)
        self.assertEqual(len(rows), 0)
        rows = await self.db.list_ble_discover_candidates(
            since_ts=time.time() - 60, include_known=True
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["unknown"])

    async def test_discover_request_pending_until_done(self) -> None:
        await self.db.request_ble_discover()
        self.assertTrue(await self.db.ble_discover_scan_pending())
        self.assertTrue(await self.db.take_ble_discover_request())
        self.assertFalse(await self.db.take_ble_discover_request())
        await self.db.mark_ble_discover_done()
        self.assertFalse(await self.db.ble_discover_scan_pending())


if __name__ == "__main__":
    unittest.main()
