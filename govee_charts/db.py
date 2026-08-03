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
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
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

            CREATE TABLE IF NOT EXISTS energy_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                value_kwh REAL NOT NULL,
                ts REAL NOT NULL,
                source TEXT,
                UNIQUE(entity_id, ts)
            );

            CREATE INDEX IF NOT EXISTS idx_energy_samples_entity_ts
                ON energy_samples(entity_id, ts);

            CREATE TABLE IF NOT EXISTS backfill_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                phase TEXT NOT NULL,
                window_start REAL NOT NULL,
                window_end REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL,
                samples_done INTEGER NOT NULL DEFAULT 0,
                samples_expected INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                updated_at REAL NOT NULL,
                UNIQUE(address, phase, window_start, window_end)
            );

            CREATE INDEX IF NOT EXISTS idx_backfill_jobs_status_pri
                ON backfill_jobs(status, priority, window_end DESC);

            CREATE TABLE IF NOT EXISTS backfill_state (
                address TEXT PRIMARY KEY,
                last_success_ts REAL,
                last_attempt_ts REAL,
                last_rssi INTEGER,
                last_battery INTEGER,
                enabled INTEGER NOT NULL DEFAULT 0
            );
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

        state_cols = {
            row[1]
            for row in await (
                await self.db.execute("PRAGMA table_info(backfill_state)")
            ).fetchall()
        }
        if state_cols and "enabled" not in state_cols:
            # Opt-in default: existing rows stay disabled until selected in the UI.
            await self.db.execute(
                "ALTER TABLE backfill_state ADD COLUMN enabled INTEGER NOT NULL DEFAULT 0"
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
        # ~120 B/row incl. indexes — rough SQLite footprint for one readings row.
        bytes_per_reading = 120
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
                r.source AS last_source,
                COALESCE(s.sample_count, 0) AS sample_count,
                s.oldest_ts,
                s.newest_ts
            FROM devices d
            LEFT JOIN readings r ON r.id = (
                SELECT id FROM readings
                WHERE address = d.address
                ORDER BY ts DESC
                LIMIT 1
            )
            LEFT JOIN (
                SELECT
                    address,
                    COUNT(*) AS sample_count,
                    MIN(ts) AS oldest_ts,
                    MAX(ts) AS newest_ts
                FROM readings
                GROUP BY address
            ) s ON s.address = d.address
            ORDER BY d.name COLLATE NOCASE, d.address
            """
        )
        rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            n = int(item.get("sample_count") or 0)
            item["sample_count"] = n
            item["storage_bytes_est"] = n * bytes_per_reading
            out.append(item)
        return out

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
        hours: float | None = 24.0,
        *,
        since: float | None = None,
        until: float | None = None,
        max_points: int = 5000,
    ) -> list[dict[str, Any]]:
        """
        Return readings in [since, until] (or last `hours` ending now).

        Downsamples to at most max_points buckets (mean temp/humidity) when denser.
        """
        now = time.time()
        if since is not None and until is not None:
            start = float(since)
            end = float(until)
        else:
            h = float(hours if hours is not None else 24.0)
            end = now
            start = end - h * 3600.0
        if end < start:
            start, end = end, start

        cursor = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity, battery, rssi, source
            FROM readings
            WHERE address = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (address.upper(), start, end),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        return _downsample_readings(rows, max_points=max(100, int(max_points)))

    async def history_aggregate(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
        *,
        bucket: str = "day",
    ) -> list[dict[str, Any]]:
        """
        Aggregate temperature/humidity by calendar day, week, or month (local time).

        Returns rows with avg/min/max for both metrics plus sample count.
        """
        address = address.upper()
        start_ts = float(start_ts)
        end_ts = float(end_ts)
        if end_ts <= start_ts:
            return []

        key = (bucket or "day").lower().strip()
        if key not in ("day", "week", "month"):
            raise ValueError("bucket must be day, week, or month")

        if key == "day":
            period_expr = "strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime')"
        elif key == "week":
            # ISO week-year + week number (Monday-based).
            period_expr = (
                "printf('%s-W%02d', "
                "strftime('%G', ts, 'unixepoch', 'localtime'), "
                "CAST(strftime('%V', ts, 'unixepoch', 'localtime') AS INTEGER))"
            )
        else:
            period_expr = "strftime('%Y-%m', ts, 'unixepoch', 'localtime')"

        cursor = await self.db.execute(
            f"""
            SELECT
                {period_expr} AS period,
                COUNT(*) AS n,
                AVG(temperature_c) AS temp_avg,
                MIN(temperature_c) AS temp_min,
                MAX(temperature_c) AS temp_max,
                AVG(humidity) AS hum_avg,
                MIN(humidity) AS hum_min,
                MAX(humidity) AS hum_max,
                MIN(ts) AS ts_min,
                MAX(ts) AS ts_max
            FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            GROUP BY period
            ORDER BY period ASC
            """,
            (address, start_ts, end_ts),
        )
        rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "period": str(row[0]),
                    "count": int(row[1] or 0),
                    "temperature_c": {
                        "avg": round(float(row[2]), 2) if row[2] is not None else None,
                        "min": round(float(row[3]), 2) if row[3] is not None else None,
                        "max": round(float(row[4]), 2) if row[4] is not None else None,
                    },
                    "humidity": {
                        "avg": round(float(row[5]), 2) if row[5] is not None else None,
                        "min": round(float(row[6]), 2) if row[6] is not None else None,
                        "max": round(float(row[7]), 2) if row[7] is not None else None,
                    },
                    "range": {
                        "start": float(row[8]) if row[8] is not None else None,
                        "end": float(row[9]) if row[9] is not None else None,
                    },
                }
            )
        return out

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

    async def room_contact_timeline(
        self,
        room: str,
        *,
        hours: float = 168.0,
    ) -> list[tuple[float, str]]:
        """
        Debounced open/closed timeline for a room's exterior openings.

        Prefers `window` contacts; falls back to `door`. Dedupes HA entity_id
        vs Ring UUID by normalized name (same rule as list_door_sensors).
        Returns sorted (ts, state) change points ('open' / 'closed').
        """
        room = (room or "").strip().lower()
        if not room:
            return []

        since = time.time() - hours * 3600.0
        cursor = await self.db.execute(
            """
            SELECT
                e.sensor_id,
                COALESCE(m.name, e.name) AS name,
                e.state,
                e.ts,
                COALESCE(m.kind, '') AS kind
            FROM door_events e
            LEFT JOIN door_sensors m ON m.sensor_id = e.sensor_id
            WHERE e.ts >= ?
              AND lower(COALESCE(m.room, '')) = ?
            ORDER BY e.ts ASC
            """,
            (since, room),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        if not rows:
            return []

        import unicodedata

        def _norm_name(value: str) -> str:
            text = unicodedata.normalize("NFKD", value or "")
            text = "".join(c for c in text if not unicodedata.combining(c))
            text = text.replace("'", " ").replace("'", " ")
            return " ".join(text.lower().split())

        by_name: dict[str, list[dict[str, Any]]] = {}
        kinds_by_name: dict[str, str] = {}
        for row in rows:
            key = _norm_name(str(row.get("name") or "")) or str(
                row.get("sensor_id") or ""
            )
            sid = str(row.get("sensor_id") or "")
            is_ha = sid.startswith("binary_sensor.")
            kind = str(row.get("kind") or "").lower()
            prev_kind = kinds_by_name.get(key)
            if key not in by_name:
                by_name[key] = []
                kinds_by_name[key] = kind
            # Prefer Ring UUID stream over HA import for the same label.
            if is_ha and by_name[key] and not str(
                by_name[key][0].get("sensor_id") or ""
            ).startswith("binary_sensor."):
                continue
            if not is_ha and by_name[key] and str(
                by_name[key][0].get("sensor_id") or ""
            ).startswith("binary_sensor."):
                by_name[key] = []
                kinds_by_name[key] = kind
            by_name[key].append(row)
            if kind:
                kinds_by_name[key] = kind

        prefer_windows = any(k == "window" for k in kinds_by_name.values())
        selected: list[list[dict[str, Any]]] = []
        for key, events in by_name.items():
            kind = kinds_by_name.get(key) or ""
            if prefer_windows and kind not in ("window", ""):
                continue
            if not prefer_windows and kind not in ("door", "window", ""):
                continue
            selected.append(events)

        if not selected:
            return []

        # Per-contact debounce, then OR across contacts (any open → open).
        dwell_s = 120.0

        def _debounce(events: list[dict[str, Any]]) -> list[tuple[float, str]]:
            pts: list[tuple[float, str]] = []
            for ev in events:
                ts = float(ev["ts"])
                st = str(ev["state"]).lower().strip()
                if st not in ("open", "closed"):
                    continue
                if not pts:
                    pts.append((ts, st))
                    continue
                prev_ts, prev_st = pts[-1]
                if st == prev_st:
                    continue
                if ts - prev_ts < dwell_s:
                    if len(pts) >= 2:
                        pts.pop()
                        if pts[-1][1] == st:
                            continue
                        pts.append((ts, st))
                    else:
                        pts[-1] = (ts, st)
                else:
                    pts.append((ts, st))
            return pts

        per_contact = [_debounce(evs) for evs in selected]
        per_contact = [p for p in per_contact if p]
        if not per_contact:
            return []

        change_ts = sorted({ts for series in per_contact for ts, _ in series})

        def _state_at(series: list[tuple[float, str]], ts: float) -> str:
            state = series[0][1]
            for et, st in series:
                if et <= ts:
                    state = st
                else:
                    break
            return state

        combined: list[tuple[float, str]] = []
        for ts in change_ts:
            any_open = any(_state_at(series, ts) == "open" for series in per_contact)
            state = "open" if any_open else "closed"
            if not combined or combined[-1][1] != state:
                combined.append((ts, state))
        return combined

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

    async def insert_energy_sample(
        self,
        *,
        entity_id: str,
        value_kwh: float,
        ts: float | None = None,
        source: str = "ha",
    ) -> bool:
        """Record an energy meter reading in kWh. Returns True if inserted."""
        entity_id = str(entity_id).strip()
        if not entity_id:
            return False
        when = float(ts if ts is not None else time.time())
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO energy_samples (entity_id, value_kwh, ts, source)
            VALUES (?, ?, ?, ?)
            """,
            (entity_id, float(value_kwh), when, source),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def latest_energy(
        self, entity_id: str | None = None
    ) -> dict[str, Any] | None:
        if entity_id:
            cursor = await self.db.execute(
                """
                SELECT entity_id, value_kwh, ts, source
                FROM energy_samples
                WHERE entity_id = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (entity_id,),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT entity_id, value_kwh, ts, source
                FROM energy_samples
                ORDER BY ts DESC
                LIMIT 1
                """
            )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def energy_history(
        self,
        *,
        hours: float = 168.0,
        entity_id: str | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        start = float(since) if since is not None else time.time() - hours * 3600.0
        if entity_id:
            cursor = await self.db.execute(
                """
                SELECT entity_id, value_kwh, ts, source
                FROM energy_samples
                WHERE entity_id = ? AND ts >= ?
                ORDER BY ts ASC
                """,
                (entity_id, start),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT entity_id, value_kwh, ts, source
                FROM energy_samples
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (start,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def energy_at_or_before(
        self, entity_id: str, ts: float
    ) -> dict[str, Any] | None:
        """Latest sample at or before ts (for cumulative meter deltas)."""
        cursor = await self.db.execute(
            """
            SELECT entity_id, value_kwh, ts, source
            FROM energy_samples
            WHERE entity_id = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (entity_id, float(ts)),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def energy_at_or_after(
        self, entity_id: str, ts: float
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT entity_id, value_kwh, ts, source
            FROM energy_samples
            WHERE entity_id = ? AND ts >= ?
            ORDER BY ts ASC
            LIMIT 1
            """,
            (entity_id, float(ts)),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def prune_energy_samples(self, retention_days: float) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400.0
        cursor = await self.db.execute(
            "DELETE FROM energy_samples WHERE ts < ?",
            (cutoff,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def last_battery(self, address: str) -> int | None:
        cursor = await self.db.execute(
            """
            SELECT battery FROM readings
            WHERE address = ? AND battery IS NOT NULL
            ORDER BY ts DESC
            LIMIT 1
            """,
            (address.upper(),),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            batt = int(row[0])
        except (TypeError, ValueError):
            return None
        return batt if 0 <= batt <= 100 else None

    async def reading_minutes(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
        *,
        cover_seconds: float = 75.0,
    ) -> set[int]:
        """
        Return unix-minute indexes covered by readings near [start_ts, end_ts).

        Each reading covers neighbouring minutes within cover_seconds so sparse
        live ads (e.g. every 90s) are not treated as endless one-minute GATT gaps.
        """
        pad = max(0.0, float(cover_seconds))
        cursor = await self.db.execute(
            """
            SELECT ts
            FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            """,
            (address.upper(), float(start_ts) - pad, float(end_ts) + pad),
        )
        rows = await cursor.fetchall()
        covered: set[int] = set()
        start_m = int(start_ts // 60)
        end_m = int(end_ts // 60)
        if end_m <= start_m:
            return covered
        for row in rows:
            ts = float(row[0])
            lo = int((ts - pad) // 60)
            hi = int((ts + pad) // 60)
            for m in range(max(start_m, lo), min(end_m, hi + 1)):
                covered.add(m)
        return covered

    async def reading_exact_minutes(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
    ) -> set[int]:
        """Unix-minute indexes that have an exact reading in [start_ts, end_ts)."""
        cursor = await self.db.execute(
            """
            SELECT ts FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            """,
            (address.upper(), float(start_ts), float(end_ts)),
        )
        return {int(float(row[0]) // 60) for row in await cursor.fetchall()}

    async def coverage_report(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
        *,
        cover_seconds: float = 75.0,
        exact: bool = False,
    ) -> dict[str, Any]:
        """
        Classify [start_ts, end_ts) into full / partial / missing segments.

        Soft cover (default) uses reading_minutes; exact uses exact sample minutes.
        """
        address = address.upper()
        start_ts = float(start_ts)
        end_ts = float(end_ts)
        if end_ts <= start_ts:
            return empty_coverage_report(start_ts, end_ts)

        if exact:
            covered = await self.reading_exact_minutes(address, start_ts, end_ts)
        else:
            covered = await self.reading_minutes(
                address, start_ts, end_ts, cover_seconds=cover_seconds
            )

        report = coverage_from_minute_set(covered, start_ts, end_ts)
        stats = await self.reading_range_stats(address, start_ts, end_ts)
        report["samples"] = stats.get("samples_in_range") or 0
        report["sources"] = stats.get("sources") or {}
        return report

    async def coverage_overview(
        self,
        start_ts: float,
        end_ts: float,
        *,
        cover_seconds: float = 75.0,
        labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Coverage segments for every device in [start_ts, end_ts).

        Loads timestamps once, then soft-covers per address (same 75s rule).
        """
        start_ts = float(start_ts)
        end_ts = float(end_ts)
        labels = labels or {}
        devices = await self.list_devices()
        if end_ts <= start_ts or not devices:
            return []

        pad = max(0.0, float(cover_seconds))
        cursor = await self.db.execute(
            """
            SELECT address, ts
            FROM readings
            WHERE ts >= ? AND ts < ?
            """,
            (start_ts - pad, end_ts + pad),
        )
        by_addr: dict[str, list[float]] = {}
        for row in await cursor.fetchall():
            addr = str(row[0] or "").upper()
            if not addr:
                continue
            by_addr.setdefault(addr, []).append(float(row[1]))

        start_m = int(start_ts // 60)
        end_m = int(end_ts // 60)
        out: list[dict[str, Any]] = []
        for device in devices:
            addr = str(device.get("address") or "").upper()
            if not addr:
                continue
            name = labels.get(addr) or str(device.get("name") or addr)
            stamps = by_addr.get(addr) or []
            covered: set[int] = set()
            samples_in_range = 0
            for ts in stamps:
                if start_ts <= ts < end_ts:
                    samples_in_range += 1
                lo = int((ts - pad) // 60)
                hi = int((ts + pad) // 60)
                for m in range(max(start_m, lo), min(end_m, hi + 1)):
                    covered.add(m)
            report = coverage_from_minute_set(covered, start_ts, end_ts)
            out.append(
                {
                    "address": addr,
                    "name": name,
                    "coverage_pct": report["coverage_pct"],
                    "bucket": report["bucket"],
                    "segments": report["segments"],
                    "counts": report.get("counts") or {},
                    "samples": samples_in_range,
                    "range": report["range"],
                }
            )
        out.sort(key=lambda r: str(r.get("name") or r.get("address") or "").lower())
        return out

    async def reading_range_stats(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
    ) -> dict[str, Any]:
        """Aggregate existing readings in a time window for CSV import compare."""
        address = address.upper()
        cursor = await self.db.execute(
            """
            SELECT
                COUNT(*) AS n,
                MIN(ts), MAX(ts),
                MIN(temperature_c), MAX(temperature_c),
                MIN(humidity), MAX(humidity)
            FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            """,
            (address, float(start_ts), float(end_ts)),
        )
        row = await cursor.fetchone()
        n = int(row[0] or 0) if row else 0
        if not n:
            return {
                "samples_in_range": 0,
                "range": {"start": None, "end": None},
                "temp": {"min": None, "max": None},
                "humidity": {"min": None, "max": None},
                "sources": {},
            }
        src_cur = await self.db.execute(
            """
            SELECT COALESCE(source, 'unknown') AS src, COUNT(*) AS n
            FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            GROUP BY src
            ORDER BY n DESC
            """,
            (address, float(start_ts), float(end_ts)),
        )
        sources = {str(r[0]): int(r[1]) for r in await src_cur.fetchall()}
        return {
            "samples_in_range": n,
            "range": {
                "start": float(row[1]) if row[1] is not None else None,
                "end": float(row[2]) + 60.0 if row[2] is not None else None,
            },
            "temp": {
                "min": float(row[3]) if row[3] is not None else None,
                "max": float(row[4]) if row[4] is not None else None,
            },
            "humidity": {
                "min": float(row[5]) if row[5] is not None else None,
                "max": float(row[6]) if row[6] is not None else None,
            },
            "sources": sources,
        }

    async def clear_open_backfill_jobs(self) -> int:
        """Drop pending/deferred jobs so gap refresh can rebuild a clean queue."""
        cursor = await self.db.execute(
            """
            DELETE FROM backfill_jobs
            WHERE status IN ('pending', 'deferred')
            """
        )
        await self.db.commit()
        return cursor.rowcount

    async def clear_open_backfill_jobs_except(
        self, enabled_addresses: set[str] | list[str]
    ) -> int:
        """Drop pending/deferred jobs for addresses not in the enabled set."""
        enabled = {str(a).upper() for a in enabled_addresses if a}
        if not enabled:
            return await self.clear_open_backfill_jobs()
        placeholders = ",".join("?" for _ in enabled)
        cursor = await self.db.execute(
            f"""
            DELETE FROM backfill_jobs
            WHERE status IN ('pending', 'deferred')
              AND address NOT IN ({placeholders})
            """,
            tuple(enabled),
        )
        await self.db.commit()
        return cursor.rowcount

    async def cancel_open_backfill_jobs(self, address: str) -> int:
        """Remove pending/deferred and cancel running jobs for one address."""
        address = address.upper()
        now = time.time()
        cursor = await self.db.execute(
            """
            DELETE FROM backfill_jobs
            WHERE address = ? AND status IN ('pending', 'deferred')
            """,
            (address,),
        )
        deleted = int(cursor.rowcount or 0)
        cursor = await self.db.execute(
            """
            UPDATE backfill_jobs
            SET status = 'cancelled',
                error = 'disabled by user',
                updated_at = ?
            WHERE address = ? AND status = 'running'
            """,
            (now, address),
        )
        await self.db.commit()
        return deleted + int(cursor.rowcount or 0)

    async def recent_gatt_readings(self, limit: int = 100) -> list[dict[str, Any]]:
        """Newest GATT-recovered rows by insert id (recovery order proxy)."""
        limit = max(1, min(int(limit), 500))
        cursor = await self.db.execute(
            """
            SELECT
                r.id,
                r.address,
                COALESCE(d.name, r.address) AS name,
                r.ts,
                r.temperature_c,
                r.humidity,
                r.battery,
                r.rssi,
                r.source
            FROM readings r
            LEFT JOIN devices d ON d.address = r.address
            WHERE r.source LIKE '%/gatt'
               OR r.source = 'gatt-history'
               OR lower(COALESCE(r.source, '')) LIKE '%gatt%'
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def recent_backfill_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recently updated backfill jobs, excluding still-pending ones."""
        limit = max(1, min(int(limit), 200))
        cursor = await self.db.execute(
            """
            SELECT id, address, phase, window_start, window_end, status,
                   priority, samples_done, samples_expected, error, updated_at
            FROM backfill_jobs
            WHERE status != 'pending'
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def reset_running_backfill_jobs(self) -> int:
        """Mark interrupted running jobs as pending again (startup recovery)."""
        now = time.time()
        cursor = await self.db.execute(
            """
            UPDATE backfill_jobs
            SET status = 'pending', error = NULL, updated_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def commit(self) -> None:
        await self.db.commit()

    async def enqueue_backfill_job(
        self,
        *,
        address: str,
        phase: str,
        window_start: float,
        window_end: float,
        priority: int,
        samples_expected: int,
        commit: bool = True,
    ) -> int | None:
        """Insert a pending job if that window is not already queued/done recently."""
        address = address.upper()
        now = time.time()
        cursor = await self.db.execute(
            """
            INSERT OR IGNORE INTO backfill_jobs
                (address, phase, window_start, window_end, status, priority,
                 samples_done, samples_expected, error, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, 0, ?, NULL, ?)
            """,
            (
                address,
                phase,
                float(window_start),
                float(window_end),
                int(priority),
                int(samples_expected),
                now,
            ),
        )
        if cursor.rowcount <= 0:
            # Row already exists (pending/running/deferred/failed/done). Do not
            # reopen failed/deferred here — the worker promotes deferred after
            # backoff, and failed/done windows stay closed.
            if commit:
                await self.db.commit()
            return None
        if commit:
            await self.db.commit()
        cursor = await self.db.execute(
            """
            SELECT id FROM backfill_jobs
            WHERE address = ? AND phase = ? AND window_start = ? AND window_end = ?
            """,
            (address, phase, float(window_start), float(window_end)),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else None

    async def list_backfill_jobs(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            cursor = await self.db.execute(
                f"""
                SELECT id, address, phase, window_start, window_end, status,
                       priority, samples_done, samples_expected, error, updated_at
                FROM backfill_jobs
                WHERE status IN ({placeholders})
                ORDER BY priority ASC, window_end DESC, id ASC
                LIMIT ?
                """,
                (*statuses, int(limit)),
            )
        else:
            cursor = await self.db.execute(
                """
                SELECT id, address, phase, window_start, window_end, status,
                       priority, samples_done, samples_expected, error, updated_at
                FROM backfill_jobs
                ORDER BY priority ASC, window_end DESC, id ASC
                LIMIT ?
                """,
                (int(limit),),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def summarize_backfill_queue(self) -> list[dict[str, Any]]:
        """Aggregate all pending/deferred jobs per device (no row limit)."""
        cursor = await self.db.execute(
            """
            SELECT
                address,
                COUNT(*) AS jobs,
                COALESCE(SUM(samples_expected), 0) AS samples_expected,
                MIN(priority) AS priority
            FROM backfill_jobs
            WHERE status IN ('pending', 'deferred')
            GROUP BY address
            """
        )
        rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            addr = str(row[0]).upper()
            pri = int(row[3])
            phase_cur = await self.db.execute(
                """
                SELECT phase FROM backfill_jobs
                WHERE address = ? AND status IN ('pending', 'deferred')
                ORDER BY priority ASC, window_end DESC, id ASC
                LIMIT 1
                """,
                (addr,),
            )
            phase_row = await phase_cur.fetchone()
            out.append(
                {
                    "address": addr,
                    "jobs": int(row[1]),
                    "samples_expected": int(row[2]),
                    "priority": pri,
                    "phase": str(phase_row[0]) if phase_row else "hour",
                }
            )
        return out

    async def local_rssi_map(self, node_id: str) -> dict[str, int]:
        """Latest RSSI from readings produced by this node (not peer ingest)."""
        node_id = str(node_id).strip()
        gatt = f"{node_id}/gatt"
        cursor = await self.db.execute(
            """
            SELECT r.address, r.rssi
            FROM readings r
            INNER JOIN (
                SELECT address, MAX(ts) AS mts
                FROM readings
                WHERE source = ? OR source = ?
                GROUP BY address
            ) latest
              ON latest.address = r.address AND latest.mts = r.ts
            WHERE r.rssi IS NOT NULL
            """,
            (node_id, gatt),
        )
        out: dict[str, int] = {}
        for row in await cursor.fetchall():
            try:
                out[str(row[0]).upper()] = int(row[1])
            except (TypeError, ValueError):
                continue
        cursor = await self.db.execute(
            """
            SELECT address, last_rssi FROM backfill_state
            WHERE last_rssi IS NOT NULL
            """
        )
        for row in await cursor.fetchall():
            addr = str(row[0]).upper()
            if addr in out:
                continue
            try:
                out[addr] = int(row[1])
            except (TypeError, ValueError):
                continue
        return out

    async def get_backfill_job(self, job_id: int) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT id, address, phase, window_start, window_end, status,
                   priority, samples_done, samples_expected, error, updated_at
            FROM backfill_jobs
            WHERE id = ?
            """,
            (int(job_id),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_backfill_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        samples_done: int | None = None,
        samples_expected: int | None = None,
        error: str | None | object = ...,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if samples_done is not None:
            fields.append("samples_done = ?")
            values.append(int(samples_done))
        if samples_expected is not None:
            fields.append("samples_expected = ?")
            values.append(int(samples_expected))
        if error is not ...:
            fields.append("error = ?")
            values.append(error)
        values.append(int(job_id))
        await self.db.execute(
            f"UPDATE backfill_jobs SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await self.db.commit()

    async def backfill_job_counts(self) -> dict[str, int]:
        cursor = await self.db.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM backfill_jobs
            GROUP BY status
            """
        )
        rows = await cursor.fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    async def get_backfill_state(self, address: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT address, last_success_ts, last_attempt_ts, last_rssi,
                   last_battery, COALESCE(enabled, 0) AS enabled
            FROM backfill_state
            WHERE address = ?
            """,
            (address.upper(),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        out = dict(row)
        out["enabled"] = bool(int(out.get("enabled") or 0))
        return out

    async def list_backfill_enabled(self) -> set[str]:
        """Addresses opted in for GATT history backfill."""
        cursor = await self.db.execute(
            """
            SELECT address FROM backfill_state
            WHERE COALESCE(enabled, 0) = 1
            """
        )
        return {str(row[0]).upper() for row in await cursor.fetchall()}

    async def is_backfill_enabled(self, address: str) -> bool:
        cursor = await self.db.execute(
            """
            SELECT COALESCE(enabled, 0) FROM backfill_state
            WHERE address = ?
            """,
            (address.upper(),),
        )
        row = await cursor.fetchone()
        return bool(row and int(row[0] or 0) == 1)

    async def set_backfill_enabled(self, address: str, enabled: bool) -> bool:
        """Persist opt-in flag. Returns the stored enabled value."""
        address = address.upper()
        flag = 1 if enabled else 0
        await self.db.execute(
            """
            INSERT INTO backfill_state
                (address, last_success_ts, last_attempt_ts, last_rssi,
                 last_battery, enabled)
            VALUES (?, NULL, NULL, NULL, NULL, ?)
            ON CONFLICT(address) DO UPDATE SET
                enabled = excluded.enabled
            """,
            (address, flag),
        )
        await self.db.commit()
        return bool(flag)

    async def upsert_backfill_state(
        self,
        address: str,
        *,
        last_success_ts: float | None = None,
        last_attempt_ts: float | None = None,
        last_rssi: int | None = None,
        last_battery: int | None = None,
        success: bool = False,
    ) -> None:
        address = address.upper()
        now = time.time()
        attempt = last_attempt_ts if last_attempt_ts is not None else now
        existing = await self.get_backfill_state(address)
        success_ts = (
            last_success_ts
            if last_success_ts is not None
            else (now if success else (existing or {}).get("last_success_ts"))
        )
        rssi = last_rssi if last_rssi is not None else (existing or {}).get("last_rssi")
        battery = (
            last_battery
            if last_battery is not None
            else (existing or {}).get("last_battery")
        )
        enabled = 1 if (existing or {}).get("enabled") else 0
        await self.db.execute(
            """
            INSERT INTO backfill_state
                (address, last_success_ts, last_attempt_ts, last_rssi,
                 last_battery, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                last_success_ts = excluded.last_success_ts,
                last_attempt_ts = excluded.last_attempt_ts,
                last_rssi = COALESCE(excluded.last_rssi, backfill_state.last_rssi),
                last_battery = COALESCE(excluded.last_battery, backfill_state.last_battery),
                enabled = backfill_state.enabled
            """,
            (address, success_ts, attempt, rssi, battery, enabled),
        )
        await self.db.commit()

    async def insert_gatt_readings(
        self,
        *,
        address: str,
        display_name: str,
        model: str,
        samples: list[tuple[float, float, float]],
        battery: int,
        rssi: int | None,
        source: str = "local/gatt",
    ) -> int:
        """Bulk INSERT OR IGNORE GATT history samples. samples: (ts, temp, humidity)."""
        address = address.upper()
        if not samples:
            return 0
        now = time.time()
        first_ts = min(ts for ts, _, _ in samples)
        last_ts = max(ts for ts, _, _ in samples)
        await self.db.execute(
            """
            INSERT INTO devices (address, name, model, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                name = excluded.name,
                model = excluded.model,
                last_seen = MAX(devices.last_seen, excluded.last_seen),
                first_seen = MIN(devices.first_seen, excluded.first_seen)
            """,
            (address, display_name, model, first_ts, max(last_ts, now)),
        )
        before = await self.reading_minutes(
            address,
            min(ts for ts, _, _ in samples) - 1.0,
            max(ts for ts, _, _ in samples) + 61.0,
        )
        await self.db.executemany(
            """
            INSERT OR IGNORE INTO readings
                (address, ts, temperature_c, humidity, battery, rssi, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (address, float(ts), float(temp), float(hum), int(battery), rssi, source)
                for ts, temp, hum in samples
            ],
        )
        await self.db.commit()
        after = await self.reading_minutes(
            address,
            min(ts for ts, _, _ in samples) - 1.0,
            max(ts for ts, _, _ in samples) + 61.0,
        )
        return max(0, len(after) - len(before))


COVERAGE_FULL_THRESHOLD = 0.90


def empty_coverage_report(start_ts: float, end_ts: float) -> dict[str, Any]:
    return {
        "range": {"start": float(start_ts), "end": float(end_ts)},
        "bucket": "day",
        "coverage_pct": 0.0,
        "segments": [],
        "samples": 0,
        "sources": {},
        "counts": {"full": 0, "partial": 0, "missing": 0},
    }


def coverage_from_minute_set(
    covered: set[int],
    start_ts: float,
    end_ts: float,
) -> dict[str, Any]:
    """
    Bucket [start_ts, end_ts) and merge contiguous same-status runs.

    Hour buckets when the window is ≤ 14 days; otherwise day buckets.
    """
    start_ts = float(start_ts)
    end_ts = float(end_ts)
    if end_ts <= start_ts:
        return empty_coverage_report(start_ts, end_ts)

    span = end_ts - start_ts
    bucket = "hour" if span <= 14 * 86400.0 else "day"
    bucket_secs = 3600 if bucket == "hour" else 86400
    start_m = int(start_ts // 60)
    end_m = int(end_ts // 60)
    if end_m <= start_m:
        return empty_coverage_report(start_ts, end_ts)

    # Align bucket edges to UTC hour/day for stable bars.
    start_bucket = int(start_ts // bucket_secs) * bucket_secs
    buckets: list[dict[str, Any]] = []
    cursor = float(start_bucket)
    while cursor < end_ts:
        b_start = max(cursor, start_ts)
        b_end = min(cursor + bucket_secs, end_ts)
        lo = int(b_start // 60)
        hi = int(b_end // 60)
        expected = max(0, hi - lo)
        if expected <= 0:
            cursor += bucket_secs
            continue
        hit = sum(1 for m in range(lo, hi) if m in covered)
        density = hit / float(expected)
        if density <= 0.0:
            status = "missing"
        elif density >= COVERAGE_FULL_THRESHOLD:
            status = "full"
        else:
            status = "partial"
        buckets.append(
            {
                "start": b_start,
                "end": b_end,
                "status": status,
                "density": round(density, 4),
                "samples": hit,
                "expected": expected,
            }
        )
        cursor += bucket_secs

    segments: list[dict[str, Any]] = []
    for b in buckets:
        if (
            segments
            and segments[-1]["status"] == b["status"]
            and abs(float(segments[-1]["end"]) - float(b["start"])) < 1.0
        ):
            prev = segments[-1]
            prev["end"] = b["end"]
            prev_expected = int(prev.get("expected") or 0) + int(b["expected"])
            prev_samples = int(prev.get("samples") or 0) + int(b["samples"])
            prev["expected"] = prev_expected
            prev["samples"] = prev_samples
            prev["density"] = (
                round(prev_samples / float(prev_expected), 4) if prev_expected else 0.0
            )
        else:
            segments.append(dict(b))

    total_expected = end_m - start_m
    total_hit = sum(1 for m in range(start_m, end_m) if m in covered)
    coverage_pct = (
        round(100.0 * total_hit / float(total_expected), 1) if total_expected else 0.0
    )
    counts = {"full": 0, "partial": 0, "missing": 0}
    for seg in segments:
        counts[str(seg["status"])] = counts.get(str(seg["status"]), 0) + 1

    return {
        "range": {"start": start_ts, "end": end_ts},
        "bucket": bucket,
        "coverage_pct": coverage_pct,
        "segments": segments,
        "samples": total_hit,
        "sources": {},
        "counts": counts,
    }


def _downsample_readings(
    rows: list[dict[str, Any]],
    *,
    max_points: int,
) -> list[dict[str, Any]]:
    """Average temp/humidity into equal-time buckets when too many points."""
    n = len(rows)
    if n <= max_points or max_points < 2:
        return rows
    t0 = float(rows[0]["ts"])
    t1 = float(rows[-1]["ts"])
    span = max(t1 - t0, 1e-6)
    bucket_w = span / float(max_points)
    out: list[dict[str, Any]] = []
    bi = 0
    bucket: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal bucket
        if not bucket:
            return
        temps = [float(r["temperature_c"]) for r in bucket if r.get("temperature_c") is not None]
        hums = [float(r["humidity"]) for r in bucket if r.get("humidity") is not None]
        mid = bucket[len(bucket) // 2]
        last = bucket[-1]
        out.append(
            {
                "ts": float(mid["ts"]),
                "temperature_c": (sum(temps) / len(temps)) if temps else None,
                "humidity": (sum(hums) / len(hums)) if hums else None,
                "battery": last.get("battery"),
                "rssi": last.get("rssi"),
                "source": last.get("source"),
            }
        )
        bucket = []

    for row in rows:
        ts = float(row["ts"])
        idx = min(max_points - 1, int((ts - t0) / bucket_w))
        if idx != bi and bucket:
            flush()
            bi = idx
        bucket.append(row)
    flush()
    return out

