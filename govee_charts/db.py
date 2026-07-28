"""SQLite persistence for devices and readings."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

from govee_charts.decode import Reading


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                address TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                model TEXT NOT NULL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                ts REAL NOT NULL,
                temperature_c REAL NOT NULL,
                humidity REAL NOT NULL,
                battery INTEGER NOT NULL,
                rssi INTEGER,
                source TEXT,
                FOREIGN KEY (address) REFERENCES devices(address)
            );

            CREATE INDEX IF NOT EXISTS idx_readings_address_ts
                ON readings(address, ts);
            """
        )
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        cols = {
            row[1]
            for row in await (
                await self.db.execute("PRAGMA table_info(readings)")
            ).fetchall()
        }
        if "source" not in cols:
            await self.db.execute("ALTER TABLE readings ADD COLUMN source TEXT")
        # Deduplicate before creating unique index (keep lowest id)
        await self.db.execute(
            """
            DELETE FROM readings
            WHERE id NOT IN (
                SELECT MIN(id) FROM readings GROUP BY address, ts
            )
            """
        )
        await self.db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_address_ts_unique
                ON readings(address, ts)
            """
        )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected")
        return self._db

    async def upsert_reading(
        self,
        reading: Reading,
        display_name: str,
        *,
        ts: float | None = None,
        source: str | None = None,
    ) -> bool:
        """Insert a reading. Returns False if the (address, ts) already exists."""
        now = time.time()
        sample_ts = float(ts) if ts is not None else now
        await self.db.execute(
            """
            INSERT INTO devices (address, name, model, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                name = excluded.name,
                model = excluded.model,
                last_seen = MAX(devices.last_seen, excluded.last_seen)
            """,
            (reading.address, display_name, reading.model, sample_ts, sample_ts),
        )
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO readings
                (address, ts, temperature_c, humidity, battery, rssi, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading.address,
                sample_ts,
                reading.temperature_c,
                reading.humidity,
                reading.battery,
                reading.rssi,
                source,
            ),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def prune(self, retention_days: float) -> int:
        cutoff = time.time() - retention_days * 86400.0
        cursor = await self.db.execute(
            "DELETE FROM readings WHERE ts < ?",
            (cutoff,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def list_devices(self) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT
                d.address,
                d.name,
                d.model,
                d.first_seen,
                d.last_seen,
                r.temperature_c,
                r.humidity,
                r.battery,
                r.rssi,
                r.ts AS last_reading_ts,
                r.source AS last_source
            FROM devices d
            LEFT JOIN readings r ON r.id = (
                SELECT id FROM readings
                WHERE address = d.address
                ORDER BY ts DESC
                LIMIT 1
            )
            ORDER BY d.name COLLATE NOCASE, d.address
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def history(
        self,
        address: str,
        hours: float,
    ) -> list[dict[str, Any]]:
        since = time.time() - hours * 3600.0
        cursor = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity, battery, rssi, source
            FROM readings
            WHERE address = ? AND ts >= ?
            ORDER BY ts ASC
            """,
            (address.upper(), since),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
