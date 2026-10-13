"""Regression: leaked aiosqlite cursors must not finalize on the wrong thread."""

from __future__ import annotations

import asyncio
import gc
import tempfile
import unittest
from pathlib import Path

from govee_charts.db import Database, ensure_aiosqlite_cursor_thread_safety


class AiosqliteCursorGcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "readings.db")
        await self.db.connect()
        await self.db.db.execute(
            "INSERT INTO devices(address, name, model, first_seen, last_seen) "
            "VALUES(?, ?, ?, ?, ?)",
            ("AA:BB:CC:DD:EE:FF", "test", "H5075", 1.0, 1.0),
        )
        for i in range(200):
            await self.db.db.execute(
                "INSERT INTO readings(address, ts, temperature_c, humidity, battery, rssi) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                ("AA:BB:CC:DD:EE:FF", float(i), 20.0, 50.0, 100, -60),
            )
        await self.db.db.commit()

    async def asyncTearDown(self) -> None:
        await self.db.db.close()
        self._tmp.cleanup()

    def test_patch_installs_once(self) -> None:
        ensure_aiosqlite_cursor_thread_safety()
        ensure_aiosqlite_cursor_thread_safety()
        import aiosqlite

        self.assertTrue(getattr(aiosqlite.Cursor, "_govee_threadsafe_del", False))

    async def test_leaked_cursors_gc_during_queries(self) -> None:
        """Stress the bug that SIGSEGV'd launchd: GC finalize vs worker step."""

        async def leak_reads(n: int) -> None:
            for _ in range(n):
                cursor = await self.db.db.execute(
                    "SELECT ts, temperature_c FROM readings WHERE address = ?",
                    ("AA:BB:CC:DD:EE:FF",),
                )
                await cursor.fetchall()
                # Deliberately do not close — matches production call sites.

        async def churn() -> None:
            for _ in range(40):
                await leak_reads(5)
                gc.collect()
                await asyncio.sleep(0)

        await asyncio.gather(churn(), churn(), churn())
        gc.collect()
        # Drain any queued finalizers on the aiosqlite worker.
        await self.db.db.execute("SELECT 1")
        row = await (await self.db.db.execute("SELECT COUNT(*) FROM readings")).fetchone()
        self.assertEqual(int(row[0]), 200)


if __name__ == "__main__":
    unittest.main()
