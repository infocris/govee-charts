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

            CREATE TABLE IF NOT EXISTS door_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id TEXT NOT NULL,
                name TEXT NOT NULL,
                state TEXT NOT NULL,
                ts REAL NOT NULL,
                source TEXT,
                UNIQUE(sensor_id, ts, state)
            );

            CREATE INDEX IF NOT EXISTS idx_door_events_sensor_ts
                ON door_events(sensor_id, ts);

            CREATE TABLE IF NOT EXISTS door_sensors (
                sensor_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                room TEXT,
                kind TEXT,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS hvac_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                state TEXT NOT NULL,
                hvac_mode TEXT,
                current_temp_c REAL,
                target_temp_c REAL,
                fan_mode TEXT,
                ts REAL NOT NULL,
                source TEXT,
                UNIQUE(entity_id, ts)
            );

            CREATE INDEX IF NOT EXISTS idx_hvac_events_entity_ts
                ON hvac_events(entity_id, ts);

            CREATE TABLE IF NOT EXISTS power_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                watts REAL NOT NULL,
                ts REAL NOT NULL,
                source TEXT,
                UNIQUE(entity_id, ts)
            );

            CREATE INDEX IF NOT EXISTS idx_power_samples_entity_ts
                ON power_samples(entity_id, ts);
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

    async def insert_door_event(
        self,
        *,
        sensor_id: str,
        name: str,
        state: str,
        ts: float | None = None,
        source: str = "mqtt",
    ) -> bool:
        """
        Record a door/window contact change.
        state must be 'open' or 'closed'. Returns True if a new row was inserted.
        """
        state = state.lower().strip()
        if state not in ("open", "closed"):
            raise ValueError("door state must be open or closed")
        sensor_id = str(sensor_id).strip()
        name = (name or sensor_id).strip() or sensor_id
        when = float(ts if ts is not None else time.time())
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO door_events (sensor_id, name, state, ts, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sensor_id, name, state, when, source),
        )
        await self.ensure_door_sensor(sensor_id=sensor_id, name=name)
        await self.db.commit()
        return cursor.rowcount > 0

    async def ensure_door_sensor(
        self,
        *,
        sensor_id: str,
        name: str,
    ) -> None:
        """Create door_sensors row if missing; infer kind/room only when unset."""
        from govee_charts.categories import infer_contact_from_label

        sensor_id = str(sensor_id).strip()
        name = (name or sensor_id).strip() or sensor_id
        now = time.time()
        cursor = await self.db.execute(
            "SELECT sensor_id, name, room, kind FROM door_sensors WHERE sensor_id = ?",
            (sensor_id,),
        )
        row = await cursor.fetchone()
        inferred = infer_contact_from_label(name)
        if row is None:
            await self.db.execute(
                """
                INSERT INTO door_sensors (sensor_id, name, room, kind, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    sensor_id,
                    name,
                    inferred.get("room"),
                    inferred.get("kind"),
                    now,
                ),
            )
            return

        # Refresh name if we learned a friendlier one; fill empty room/kind only.
        updates: list[str] = []
        values: list[Any] = []
        existing_name = str(row["name"] or "")
        if name and (
            not existing_name
            or existing_name == sensor_id
            or (
                len(name) > len(existing_name)
                and not name.startswith("binary_sensor.")
            )
        ):
            updates.append("name = ?")
            values.append(name)
        if row["room"] is None and inferred.get("room"):
            updates.append("room = ?")
            values.append(inferred["room"])
        if row["kind"] is None and inferred.get("kind"):
            updates.append("kind = ?")
            values.append(inferred["kind"])
        if updates:
            updates.append("updated_at = ?")
            values.append(now)
            values.append(sensor_id)
            await self.db.execute(
                f"UPDATE door_sensors SET {', '.join(updates)} WHERE sensor_id = ?",
                values,
            )

    async def update_door_sensor(
        self,
        sensor_id: str,
        *,
        room: str | None | object = ...,
        kind: str | None | object = ...,
        name: str | None | object = ...,
    ) -> dict[str, Any] | None:
        """Update door metadata. Ellipsis means leave unchanged."""
        sensor_id = str(sensor_id).strip()
        cursor = await self.db.execute(
            "SELECT sensor_id, name, room, kind, updated_at FROM door_sensors WHERE sensor_id = ?",
            (sensor_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            # Allow PATCH before an event if sensor_id is known from events
            ev = await self.db.execute(
                """
                SELECT name FROM door_events
                WHERE sensor_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (sensor_id,),
            )
            ev_row = await ev.fetchone()
            if ev_row is None:
                return None
            await self.ensure_door_sensor(
                sensor_id=sensor_id, name=str(ev_row["name"] or sensor_id)
            )
            cursor = await self.db.execute(
                "SELECT sensor_id, name, room, kind, updated_at FROM door_sensors WHERE sensor_id = ?",
                (sensor_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None

        fields: list[str] = []
        values: list[Any] = []
        if room is not ...:
            fields.append("room = ?")
            values.append(room)
        if kind is not ...:
            fields.append("kind = ?")
            values.append(kind)
        if name is not ...:
            fields.append("name = ?")
            values.append(name if name else row["name"])
        if not fields:
            return await self.get_door_sensor(sensor_id)

        fields.append("updated_at = ?")
        values.append(time.time())
        values.append(sensor_id)
        await self.db.execute(
            f"UPDATE door_sensors SET {', '.join(fields)} WHERE sensor_id = ?",
            values,
        )
        await self.db.commit()
        return await self.get_door_sensor(sensor_id)

    async def get_door_sensor(self, sensor_id: str) -> dict[str, Any] | None:
        sensors = await self.list_door_sensors()
        for s in sensors:
            if s.get("sensor_id") == sensor_id:
                return s
        return None

    async def list_door_sensors(self) -> list[dict[str, Any]]:
        """Latest state per door/window sensor (deduped by display name)."""
        cursor = await self.db.execute(
            """
            SELECT
                e.sensor_id,
                COALESCE(m.name, e.name) AS name,
                e.state,
                e.ts,
                e.source,
                m.room,
                m.kind
            FROM door_events e
            INNER JOIN (
                SELECT sensor_id, MAX(ts) AS max_ts
                FROM door_events
                GROUP BY sensor_id
            ) latest ON e.sensor_id = latest.sensor_id AND e.ts = latest.max_ts
            LEFT JOIN door_sensors m ON m.sensor_id = e.sensor_id
            ORDER BY e.ts DESC
            """
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        # Prefer Ring MQTT UUID rows over HA entity_id imports when names match.
        import unicodedata

        def _norm_name(value: str) -> str:
            text = unicodedata.normalize("NFKD", value or "")
            text = "".join(c for c in text if not unicodedata.combining(c))
            text = text.replace("'", " ").replace("'", " ")
            return " ".join(text.lower().split())

        by_name: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = _norm_name(str(row.get("name") or ""))
            if not key:
                key = str(row.get("sensor_id") or "")
            prev = by_name.get(key)
            if prev is None:
                by_name[key] = row
                continue
            prev_is_ha = str(prev.get("sensor_id") or "").startswith("binary_sensor.")
            cur_is_ha = str(row.get("sensor_id") or "").startswith("binary_sensor.")
            if prev_is_ha and not cur_is_ha:
                by_name[key] = row
            elif float(row.get("ts") or 0) > float(prev.get("ts") or 0) and not (
                cur_is_ha and not prev_is_ha
            ):
                by_name[key] = row
        return sorted(
            by_name.values(),
            key=lambda r: (
                str(r.get("name") or "").lower(),
                str(r.get("sensor_id") or ""),
            ),
        )

    async def door_history(
        self,
        *,
        hours: float = 168.0,
        sensor_id: str | None = None,
    ) -> list[dict[str, Any]]:
        since = time.time() - hours * 3600.0
        if sensor_id:
            cursor = await self.db.execute(
                """
                SELECT sensor_id, name, state, ts, source
                FROM door_events
                WHERE sensor_id = ? AND ts >= ?
                ORDER BY ts ASC
                """,
                (sensor_id, since),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT sensor_id, name, state, ts, source
                FROM door_events
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (since,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def prune_door_events(self, retention_days: float) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400.0
        cursor = await self.db.execute(
            "DELETE FROM door_events WHERE ts < ?",
            (cutoff,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def backfill_door_sensors(self) -> int:
        """Ensure door_sensors rows exist for every sensor_id seen in events."""
        cursor = await self.db.execute(
            """
            SELECT sensor_id, name FROM door_events e
            WHERE ts = (
                SELECT MAX(ts) FROM door_events e2 WHERE e2.sensor_id = e.sensor_id
            )
            """
        )
        rows = await cursor.fetchall()
        created = 0
        for row in rows:
            before = await self.db.execute(
                "SELECT 1 FROM door_sensors WHERE sensor_id = ?",
                (row["sensor_id"],),
            )
            existed = await before.fetchone()
            await self.ensure_door_sensor(
                sensor_id=str(row["sensor_id"]),
                name=str(row["name"] or row["sensor_id"]),
            )
            if existed is None:
                created += 1
        await self.db.commit()
        return created

    async def insert_hvac_event(
        self,
        *,
        entity_id: str,
        state: str,
        hvac_mode: str | None = None,
        current_temp_c: float | None = None,
        target_temp_c: float | None = None,
        fan_mode: str | None = None,
        ts: float | None = None,
        source: str = "ha",
    ) -> bool:
        """Record an HVAC / climate state sample. Returns True if inserted."""
        entity_id = str(entity_id).strip()
        state = str(state or "").strip()
        if not entity_id or not state:
            return False
        when = float(ts if ts is not None else time.time())
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO hvac_events (
                entity_id, state, hvac_mode, current_temp_c, target_temp_c,
                fan_mode, ts, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                state,
                hvac_mode,
                current_temp_c,
                target_temp_c,
                fan_mode,
                when,
                source,
            ),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def latest_hvac(self, entity_id: str | None = None) -> dict[str, Any] | None:
        if entity_id:
            cursor = await self.db.execute(
                """
                SELECT entity_id, state, hvac_mode, current_temp_c, target_temp_c,
                       fan_mode, ts, source
                FROM hvac_events
                WHERE entity_id = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (entity_id,),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT entity_id, state, hvac_mode, current_temp_c, target_temp_c,
                       fan_mode, ts, source
                FROM hvac_events
                ORDER BY ts DESC
                LIMIT 1
                """
            )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def hvac_history(
        self,
        *,
        hours: float = 168.0,
        entity_id: str | None = None,
    ) -> list[dict[str, Any]]:
        since = time.time() - hours * 3600.0
        if entity_id:
            cursor = await self.db.execute(
                """
                SELECT entity_id, state, hvac_mode, current_temp_c, target_temp_c,
                       fan_mode, ts, source
                FROM hvac_events
                WHERE entity_id = ? AND ts >= ?
                ORDER BY ts ASC
                """,
                (entity_id, since),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT entity_id, state, hvac_mode, current_temp_c, target_temp_c,
                       fan_mode, ts, source
                FROM hvac_events
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (since,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def prune_hvac_events(self, retention_days: float) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400.0
        cursor = await self.db.execute(
            "DELETE FROM hvac_events WHERE ts < ?",
            (cutoff,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def insert_power_sample(
        self,
        *,
        entity_id: str,
        watts: float,
        ts: float | None = None,
        source: str = "ha",
    ) -> bool:
        """Record a power sample in watts. Returns True if inserted."""
        entity_id = str(entity_id).strip()
        if not entity_id:
            return False
        when = float(ts if ts is not None else time.time())
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO power_samples (entity_id, watts, ts, source)
            VALUES (?, ?, ?, ?)
            """,
            (entity_id, float(watts), when, source),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def latest_power(self, entity_id: str | None = None) -> dict[str, Any] | None:
        if entity_id:
            cursor = await self.db.execute(
                """
                SELECT entity_id, watts, ts, source
                FROM power_samples
                WHERE entity_id = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (entity_id,),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT entity_id, watts, ts, source
                FROM power_samples
                ORDER BY ts DESC
                LIMIT 1
                """
            )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def power_history(
        self,
        *,
        hours: float = 168.0,
        entity_id: str | None = None,
    ) -> list[dict[str, Any]]:
        since = time.time() - hours * 3600.0
        if entity_id:
            cursor = await self.db.execute(
                """
                SELECT entity_id, watts, ts, source
                FROM power_samples
                WHERE entity_id = ? AND ts >= ?
                ORDER BY ts ASC
                """,
                (entity_id, since),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT entity_id, watts, ts, source
                FROM power_samples
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (since,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def prune_power_samples(self, retention_days: float) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400.0
        cursor = await self.db.execute(
            "DELETE FROM power_samples WHERE ts < ?",
            (cutoff,),
        )
        await self.db.commit()
        return cursor.rowcount
