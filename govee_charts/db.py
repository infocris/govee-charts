"""SQLite persistence for devices and readings."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

from govee_charts.address import (
    is_ble_mac,
    mac_address_suffix,
    name_mac_suffix,
    register_mac,
)
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
        await self._merge_alias_devices()
        await self._db.commit()

    async def _migrate(self) -> None:
        reading_cols = {
            row[1]
            for row in await (
                await self.db.execute("PRAGMA table_info(readings)")
            ).fetchall()
        }
        if "source" not in reading_cols:
            await self.db.execute("ALTER TABLE readings ADD COLUMN source TEXT")

        device_cols = {
            row[1]
            for row in await (
                await self.db.execute("PRAGMA table_info(devices)")
            ).fetchall()
        }
        for col in ("zone", "height", "room"):
            if col not in device_cols:
                await self.db.execute(
                    f"ALTER TABLE devices ADD COLUMN {col} TEXT"
                )

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

    async def _merge_alias_devices(self) -> None:
        """Merge UUID / alias device rows onto canonical BLE MAC addresses."""
        cursor = await self.db.execute("SELECT address, name FROM devices")
        rows = await cursor.fetchall()

        suffix_to_mac: dict[str, str] = {}
        for row in rows:
            addr = str(row[0]).upper()
            if not is_ble_mac(addr):
                continue
            try:
                suffix_to_mac[mac_address_suffix(addr)] = addr
            except ValueError:
                continue

        for row in rows:
            addr = str(row[0]).upper()
            name = str(row[1] or "")
            if is_ble_mac(addr):
                continue
            suffix = name_mac_suffix(name)
            if suffix and suffix in suffix_to_mac:
                await self._rekey_device(addr, suffix_to_mac[suffix])

    async def _rekey_device(self, old_address: str, new_address: str) -> None:
        old_address = old_address.upper()
        new_address = new_address.upper()
        if old_address == new_address:
            return

        cursor = await self.db.execute(
            "SELECT name, model, first_seen, last_seen FROM devices WHERE address = ?",
            (old_address,),
        )
        old_row = await cursor.fetchone()
        if old_row is None:
            return

        await self.db.execute(
            """
            INSERT INTO devices (address, name, model, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                last_seen = MAX(devices.last_seen, excluded.last_seen),
                first_seen = MIN(devices.first_seen, excluded.first_seen)
            """,
            (new_address, old_row[0], old_row[1], old_row[2], old_row[3]),
        )
        await self.db.execute(
            """
            INSERT OR IGNORE INTO readings
                (address, ts, temperature_c, humidity, battery, rssi, source)
            SELECT ?, ts, temperature_c, humidity, battery, rssi, source
            FROM readings WHERE address = ?
            """,
            (new_address, old_address),
        )
        await self.db.execute("DELETE FROM readings WHERE address = ?", (old_address,))
        await self.db.execute("DELETE FROM devices WHERE address = ?", (old_address,))

    async def suffix_map_from_devices(self) -> dict[str, str]:
        """Build suffix → MAC map from devices already stored with real MACs."""
        cursor = await self.db.execute("SELECT address FROM devices")
        rows = await cursor.fetchall()
        result: dict[str, str] = {}
        for row in rows:
            addr = str(row[0]).upper()
            register_mac(result, addr)
        return result

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
                d.zone,
                d.height,
                d.room,
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

    async def get_device(self, address: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT
                d.address,
                d.name,
                d.model,
                d.first_seen,
                d.last_seen,
                d.zone,
                d.height,
                d.room,
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
            WHERE d.address = ?
            """,
            (address.upper(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_device_categories(
        self,
        address: str,
        *,
        zone: str | None | object = ...,
        height: str | None | object = ...,
        room: str | None | object = ...,
    ) -> dict[str, Any] | None:
        """Update category fields. Ellipsis means leave unchanged."""
        device = await self.get_device(address)
        if device is None:
            return None

        fields: list[str] = []
        values: list[Any] = []
        if zone is not ...:
            fields.append("zone = ?")
            values.append(zone)
        if height is not ...:
            fields.append("height = ?")
            values.append(height)
        if room is not ...:
            fields.append("room = ?")
            values.append(room)
        if not fields:
            return device

        values.append(address.upper())
        await self.db.execute(
            f"UPDATE devices SET {', '.join(fields)} WHERE address = ?",
            values,
        )
        await self.db.commit()
        return await self.get_device(address)

    async def seed_categories_from_names(self) -> int:
        """Infer categories for devices that still have all category fields empty."""
        from govee_charts.categories import infer_from_label

        devices = await self.list_devices()
        updated = 0
        for device in devices:
            if device.get("zone") or device.get("height") or device.get("room"):
                continue
            inferred = infer_from_label(str(device.get("name") or ""))
            if not any(inferred.values()):
                continue
            await self.update_device_categories(
                device["address"],
                zone=inferred["zone"],
                height=inferred["height"],
                room=inferred["room"],
            )
            updated += 1
        return updated

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
