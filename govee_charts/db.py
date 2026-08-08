"""SQLite persistence for devices and readings."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta, timezone
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
from govee_charts.federation import source_bucket_sql

_HEARTBEAT_LOCK_RETRIES = 3
_HEARTBEAT_LOCK_BACKOFF_S = 0.05


def is_db_locked(exc: BaseException) -> bool:
    """True when SQLite reports a transient lock / busy condition."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit: avoid long-lived read transactions that freeze the WAL
        # snapshot for this connection and block checkpoints for peers.
        self._db = await aiosqlite.connect(self.path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=15000")
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

            CREATE TABLE IF NOT EXISTS readings_rollup (
                address TEXT NOT NULL,
                bucket_start REAL NOT NULL,
                bucket_secs INTEGER NOT NULL,
                temp_avg REAL NOT NULL,
                temp_min REAL NOT NULL,
                temp_max REAL NOT NULL,
                hum_avg REAL NOT NULL,
                hum_min REAL NOT NULL,
                hum_max REAL NOT NULL,
                n INTEGER NOT NULL,
                source TEXT,
                PRIMARY KEY (address, bucket_start, bucket_secs),
                FOREIGN KEY (address) REFERENCES devices(address)
            );

            CREATE INDEX IF NOT EXISTS idx_readings_rollup_address_start
                ON readings_rollup(address, bucket_start);

            CREATE TABLE IF NOT EXISTS compaction_state (
                address TEXT PRIMARY KEY,
                policy TEXT NOT NULL DEFAULT 'none',
                last_run_ts REAL,
                last_saved_bytes INTEGER,
                last_raw_deleted INTEGER,
                updated_at REAL NOT NULL,
                FOREIGN KEY (address) REFERENCES devices(address)
            );

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
                enabled INTEGER NOT NULL DEFAULT 0,
                gatt_enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS runtime_state (
                component TEXT PRIMARY KEY,
                heartbeat_ts REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS db_size_daily (
                day TEXT PRIMARY KEY,
                db_bytes INTEGER NOT NULL,
                wal_bytes INTEGER NOT NULL,
                total_bytes INTEGER NOT NULL,
                readings_count INTEGER,
                recorded_at REAL NOT NULL
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
        if "height_cm" not in device_cols:
            await self.db.execute(
                "ALTER TABLE devices ADD COLUMN height_cm REAL"
            )
        if "label" not in device_cols:
            await self.db.execute(
                "ALTER TABLE devices ADD COLUMN label TEXT"
            )

        # One-shot: only dedupe when the unique index is not present yet.
        # Re-running this DELETE on a large readings table makes every startup slow.
        index_rows = await (
            await self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='idx_readings_address_ts_unique'"
            )
        ).fetchall()
        if not index_rows:
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
        if state_cols and "gatt_enabled" not in state_cols:
            # Default on: allow GATT after federation pull unless the UI opts out.
            await self.db.execute(
                "ALTER TABLE backfill_state ADD COLUMN gatt_enabled "
                "INTEGER NOT NULL DEFAULT 1"
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
        await self.db.execute(
            """
            INSERT OR IGNORE INTO readings_rollup
                (address, bucket_start, bucket_secs,
                 temp_avg, temp_min, temp_max,
                 hum_avg, hum_min, hum_max, n, source)
            SELECT ?, bucket_start, bucket_secs,
                   temp_avg, temp_min, temp_max,
                   hum_avg, hum_min, hum_max, n, source
            FROM readings_rollup WHERE address = ?
            """,
            (new_address, old_address),
        )
        await self.db.execute(
            "DELETE FROM readings_rollup WHERE address = ?", (old_address,)
        )
        await self.db.execute(
            """
            INSERT OR IGNORE INTO compaction_state
                (address, policy, last_run_ts, last_saved_bytes,
                 last_raw_deleted, updated_at)
            SELECT ?, policy, last_run_ts, last_saved_bytes,
                   last_raw_deleted, updated_at
            FROM compaction_state WHERE address = ?
            """,
            (new_address, old_address),
        )
        await self.db.execute(
            "DELETE FROM compaction_state WHERE address = ?", (old_address,)
        )
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

    def wal_path(self) -> Path:
        return Path(f"{self.path}-wal")

    def wal_size_bytes(self) -> int:
        """Return on-disk WAL size, or 0 if absent."""
        try:
            return self.wal_path().stat().st_size
        except OSError:
            return 0

    async def checkpoint_wal(self, mode: str = "PASSIVE") -> tuple[int, int, int]:
        """Run PRAGMA wal_checkpoint; returns (busy, log, checkpointed)."""
        mode_u = str(mode or "PASSIVE").strip().upper()
        if mode_u not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError(f"Invalid wal_checkpoint mode: {mode}")
        cursor = await self.db.execute(f"PRAGMA wal_checkpoint({mode_u})")
        row = await cursor.fetchone()
        if row is None:
            return (0, 0, 0)
        return (int(row[0]), int(row[1]), int(row[2]))

    async def touch_runtime_heartbeat(self, component: str) -> None:
        """Upsert the latest heartbeat timestamp for a runtime component."""
        key = str(component).strip().lower()
        last_exc: BaseException | None = None
        for attempt in range(_HEARTBEAT_LOCK_RETRIES):
            ts = time.time()
            try:
                await self.db.execute(
                    """
                    INSERT INTO runtime_state (component, heartbeat_ts)
                    VALUES (?, ?)
                    ON CONFLICT(component) DO UPDATE SET
                        heartbeat_ts = excluded.heartbeat_ts
                    """,
                    (key, ts),
                )
                await self.db.commit()
                return
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if not is_db_locked(exc) or attempt + 1 >= _HEARTBEAT_LOCK_RETRIES:
                    raise
                await asyncio.sleep(_HEARTBEAT_LOCK_BACKOFF_S * (attempt + 1))
        if last_exc is not None:
            raise last_exc

    async def get_runtime_heartbeat(self, component: str) -> float | None:
        """Return last heartbeat timestamp for a runtime component."""
        cursor = await self.db.execute(
            "SELECT heartbeat_ts FROM runtime_state WHERE component = ?",
            (str(component).strip().lower(),),
        )
        row = await cursor.fetchone()
        return float(row[0]) if row else None

    @staticmethod
    def utc_day(ts: float | None = None) -> str:
        """UTC calendar day as YYYY-MM-DD."""
        when = float(ts) if ts is not None else time.time()
        return datetime.fromtimestamp(when, tz=timezone.utc).strftime("%Y-%m-%d")

    def db_file_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    async def has_db_size_day(self, day: str) -> bool:
        cursor = await self.db.execute(
            "SELECT 1 FROM db_size_daily WHERE day = ? LIMIT 1",
            (day,),
        )
        return await cursor.fetchone() is not None

    async def record_db_size_snapshot(self) -> dict[str, Any]:
        """Upsert today's UTC DB/WAL size snapshot."""
        day = self.utc_day()
        db_bytes = self.db_file_bytes()
        wal_bytes = self.wal_size_bytes()
        total_bytes = db_bytes + wal_bytes
        cursor = await self.db.execute("SELECT COUNT(*) FROM readings")
        row = await cursor.fetchone()
        readings_count = int(row[0] or 0) if row else 0
        recorded_at = time.time()
        await self.db.execute(
            """
            INSERT INTO db_size_daily
                (day, db_bytes, wal_bytes, total_bytes, readings_count, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                db_bytes = excluded.db_bytes,
                wal_bytes = excluded.wal_bytes,
                total_bytes = excluded.total_bytes,
                readings_count = excluded.readings_count,
                recorded_at = excluded.recorded_at
            """,
            (day, db_bytes, wal_bytes, total_bytes, readings_count, recorded_at),
        )
        await self.db.commit()
        return {
            "day": day,
            "db_bytes": db_bytes,
            "wal_bytes": wal_bytes,
            "total_bytes": total_bytes,
            "readings_count": readings_count,
            "recorded_at": recorded_at,
        }

    async def list_db_size_daily(self, *, limit: int = 365) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 2000))
        cursor = await self.db.execute(
            """
            SELECT day, db_bytes, wal_bytes, total_bytes, readings_count, recorded_at
            FROM db_size_daily
            ORDER BY day ASC
            LIMIT ?
            """,
            (lim,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "day": str(r[0]),
                "db_bytes": int(r[1]),
                "wal_bytes": int(r[2]),
                "total_bytes": int(r[3]),
                "readings_count": int(r[4]) if r[4] is not None else None,
                "recorded_at": float(r[5]),
            }
            for r in rows
        ]

    _TABLE_NOTES: dict[str, str] = {
        "devices": "BLE / HA device registry",
        "readings": "Temperature / humidity samples",
        "door_events": "Contact open/close events",
        "door_sensors": "Door sensor metadata",
        "hvac_events": "Climate state history",
        "power_samples": "AC power (W) samples",
        "energy_samples": "Energy (kWh) samples",
        "backfill_jobs": "GATT / federation backfill queue",
        "backfill_state": "Per-device backfill settings",
        "runtime_state": "Process heartbeats",
        "db_size_daily": "Daily SQLite size snapshots",
        "readings_rollup": "Compacted min/max/avg buckets",
        "compaction_state": "Per-device compaction policy",
    }

    async def _table_bytes_from_dbstat(self) -> dict[str, int] | None:
        """Map each user table to bytes used (table pages + its indexes).

        Uses SQLite's ``dbstat`` virtual table when available. Returns
        ``None`` if dbstat is unavailable on this build.
        """
        try:
            size_cur = await self.db.execute(
                """
                SELECT name, SUM(pgsize) AS bytes
                FROM dbstat
                GROUP BY name
                """
            )
            size_by_object: dict[str, int] = {
                str(row[0]): int(row[1] or 0)
                for row in await size_cur.fetchall()
                if row[0] is not None
            }
        except Exception:
            return None

        idx_cur = await self.db.execute(
            """
            SELECT name, tbl_name FROM sqlite_master
            WHERE type = 'index' AND tbl_name IS NOT NULL
            """
        )
        index_to_table = {
            str(row[0]): str(row[1])
            for row in await idx_cur.fetchall()
            if row[0] and row[1]
        }

        names_cur = await self.db.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        )
        table_names = [str(r[0]) for r in await names_cur.fetchall()]
        out: dict[str, int] = {name: size_by_object.get(name, 0) for name in table_names}
        for idx_name, tbl_name in index_to_table.items():
            if tbl_name in out:
                out[tbl_name] += size_by_object.get(idx_name, 0)
        return out

    async def inventory_stats(self, node_id: str) -> dict[str, Any]:
        """Row counts per table + readings provenance breakdown."""
        page_row = await (
            await self.db.execute("PRAGMA page_count")
        ).fetchone()
        page_size_row = await (
            await self.db.execute("PRAGMA page_size")
        ).fetchone()
        page_count = int(page_row[0] or 0) if page_row else 0
        page_size = int(page_size_row[0] or 0) if page_size_row else 0
        logical_bytes = page_count * page_size

        names_cur = await self.db.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name COLLATE NOCASE
            """
        )
        table_names = [str(r[0]) for r in await names_cur.fetchall()]
        bytes_by_table = await self._table_bytes_from_dbstat()
        size_source = "dbstat" if bytes_by_table is not None else None
        tables: list[dict[str, Any]] = []
        for name in table_names:
            # Table names come from sqlite_master only (not user input).
            count_cur = await self.db.execute(f'SELECT COUNT(*) FROM "{name}"')
            crow = await count_cur.fetchone()
            rows_n = int(crow[0] or 0) if crow else 0
            bytes_n: int | None = None
            pct: float | None = None
            if bytes_by_table is not None:
                bytes_n = int(bytes_by_table.get(name, 0))
                pct = (
                    (100.0 * bytes_n / logical_bytes)
                    if logical_bytes > 0
                    else 0.0
                )
            tables.append(
                {
                    "name": name,
                    "rows": rows_n,
                    "bytes": bytes_n,
                    "pct": pct,
                    "note": self._TABLE_NOTES.get(name, ""),
                }
            )
        # Largest consumers first when sizes are known.
        if size_source:
            tables.sort(
                key=lambda t: (
                    -(t["bytes"] if t["bytes"] is not None else -1),
                    str(t["name"]).lower(),
                )
            )

        bucket_sql = source_bucket_sql("source")
        src_cur = await self.db.execute(
            f"""
            SELECT {bucket_sql} AS bucket, COUNT(*) AS n
            FROM readings
            GROUP BY bucket
            """,
            (str(node_id).strip(),),
        )
        readings_by_source = {
            "direct": 0,
            "backfill": 0,
            "federation": 0,
            "other": 0,
        }
        for row in await src_cur.fetchall():
            key = str(row[0] or "other")
            if key not in readings_by_source:
                key = "other"
            readings_by_source[key] = int(row[1] or 0)

        db_bytes = self.db_file_bytes()
        wal_bytes = self.wal_size_bytes()
        attributed = (
            sum(int(t["bytes"] or 0) for t in tables) if size_source else None
        )
        return {
            "tables": tables,
            "readings_by_source": readings_by_source,
            "size_source": size_source,
            "db_file": {
                "path": str(self.path),
                "db_bytes": db_bytes,
                "wal_bytes": wal_bytes,
                "total_bytes": db_bytes + wal_bytes,
                "logical_bytes": logical_bytes,
                "page_count": page_count,
                "page_size": page_size,
                "attributed_bytes": attributed,
            },
        }

    async def sensor_storage_stats(
        self,
        *,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Per-device readings footprint, age mix, and compaction policy."""
        from govee_charts.compaction import (
            AGE_BUCKET_DEFS,
            estimate_bytes_after_policy,
            policy_catalog,
        )

        bytes_by_table = await self._table_bytes_from_dbstat()
        readings_bytes = int((bytes_by_table or {}).get("readings") or 0)
        rollup_table_bytes = int((bytes_by_table or {}).get("readings_rollup") or 0)

        count_cur = await self.db.execute("SELECT COUNT(*) FROM readings")
        total_raw = int((await count_cur.fetchone())[0] or 0)
        bytes_per_raw = (
            (readings_bytes / total_raw) if total_raw > 0 and readings_bytes > 0 else 120.0
        )

        roll_count_cur = await self.db.execute("SELECT COUNT(*) FROM readings_rollup")
        total_rollups = int((await roll_count_cur.fetchone())[0] or 0)
        bytes_per_rollup = (
            (rollup_table_bytes / total_rollups)
            if total_rollups > 0 and rollup_table_bytes > 0
            else 200.0
        )

        now = time.time()
        # Single pass: counts per address × age bucket.
        age_case_parts: list[str] = []
        for key, lo, hi in AGE_BUCKET_DEFS:
            lo_ts = now - (hi or 1e9) * 86400.0
            hi_ts = now - lo * 86400.0
            if hi is None:
                age_case_parts.append(
                    f"WHEN ts < {hi_ts!r} THEN {key!r}"
                )
            else:
                age_case_parts.append(
                    f"WHEN ts >= {lo_ts!r} AND ts < {hi_ts!r} THEN {key!r}"
                )
        age_case = "CASE " + " ".join(age_case_parts) + " ELSE '365d+' END"

        age_cur = await self.db.execute(
            f"""
            SELECT address, {age_case} AS age_key, COUNT(*) AS n
            FROM readings
            GROUP BY address, age_key
            """
        )
        age_by_addr: dict[str, dict[str, int]] = {}
        samples_by_addr: dict[str, int] = {}
        for row in await age_cur.fetchall():
            addr = str(row[0]).upper()
            key = str(row[1])
            n = int(row[2] or 0)
            age_by_addr.setdefault(addr, {})[key] = n
            samples_by_addr[addr] = samples_by_addr.get(addr, 0) + n

        roll_cur = await self.db.execute(
            """
            SELECT address, COUNT(*) AS n, COALESCE(SUM(n), 0) AS samples
            FROM readings_rollup
            GROUP BY address
            """
        )
        rollup_by_addr: dict[str, dict[str, int]] = {}
        for row in await roll_cur.fetchall():
            addr = str(row[0]).upper()
            rollup_by_addr[addr] = {
                "rows": int(row[1] or 0),
                "samples": int(row[2] or 0),
            }

        pol_cur = await self.db.execute(
            "SELECT address, policy, last_run_ts, last_saved_bytes FROM compaction_state"
        )
        policy_by_addr = {
            str(row[0]).upper(): {
                "policy": str(row[1] or "none"),
                "last_run_ts": float(row[2]) if row[2] is not None else None,
                "last_saved_bytes": int(row[3]) if row[3] is not None else None,
            }
            for row in await pol_cur.fetchall()
        }

        devices = await self.list_devices(include_stats=False)
        label_map = {str(k).upper(): str(v) for k, v in (labels or {}).items()}
        sensors: list[dict[str, Any]] = []
        readings_store_bytes = readings_bytes + rollup_table_bytes

        for device in devices:
            addr = str(device["address"]).upper()
            raw_n = int(samples_by_addr.get(addr, 0))
            roll_info = rollup_by_addr.get(addr, {"rows": 0, "samples": 0})
            raw_bytes = int(round(raw_n * bytes_per_raw))
            roll_bytes = int(round(int(roll_info["rows"]) * bytes_per_rollup))
            bytes_est = raw_bytes + roll_bytes
            age_counts = age_by_addr.get(addr, {})
            age_buckets: list[dict[str, Any]] = []
            for key, _lo, _hi in AGE_BUCKET_DEFS:
                n = int(age_counts.get(key, 0))
                b = int(round(n * bytes_per_raw))
                age_buckets.append(
                    {
                        "key": key,
                        "samples": n,
                        "bytes": b,
                        "pct": (100.0 * n / raw_n) if raw_n > 0 else 0.0,
                    }
                )
            pol = policy_by_addr.get(addr, {})
            policy = str(pol.get("policy") or "none")
            name = label_map.get(addr) or str(device.get("name") or addr)
            sensors.append(
                {
                    "address": addr,
                    "name": name,
                    "model": device.get("model"),
                    "samples": raw_n,
                    "rollup_rows": int(roll_info["rows"]),
                    "rollup_samples": int(roll_info["samples"]),
                    "bytes_est": bytes_est,
                    "pct": (
                        (100.0 * bytes_est / readings_store_bytes)
                        if readings_store_bytes > 0
                        else 0.0
                    ),
                    "age_buckets": age_buckets,
                    "policy": policy,
                    "bytes_after_est": estimate_bytes_after_policy(
                        policy=policy,
                        age_buckets=age_buckets,
                        bytes_per_raw=bytes_per_raw,
                        rollup_bytes=roll_bytes,
                    ),
                    "last_run_ts": pol.get("last_run_ts"),
                    "last_saved_bytes": pol.get("last_saved_bytes"),
                }
            )

        sensors.sort(
            key=lambda s: (-int(s["bytes_est"]), str(s["name"]).lower(), s["address"])
        )
        return {
            "readings_bytes": readings_bytes,
            "rollup_bytes": rollup_table_bytes,
            "readings_store_bytes": readings_store_bytes,
            "total_raw_samples": total_raw,
            "bytes_per_raw": bytes_per_raw,
            "policies": policy_catalog(),
            "sensors": sensors,
        }

    async def list_compaction_states(self) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT address, policy, last_run_ts, last_saved_bytes,
                   last_raw_deleted, updated_at
            FROM compaction_state
            ORDER BY address
            """
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_compaction_state(self, address: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT address, policy, last_run_ts, last_saved_bytes,
                   last_raw_deleted, updated_at
            FROM compaction_state
            WHERE address = ?
            """,
            (address.upper(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def set_compaction_policy(
        self,
        address: str,
        policy: str,
    ) -> dict[str, Any] | None:
        from govee_charts.compaction import normalize_policy

        address_u = address.upper()
        device = await self.get_device(address_u)
        if device is None:
            return None
        policy_n = normalize_policy(policy)
        now = time.time()
        await self.db.execute(
            """
            INSERT INTO compaction_state
                (address, policy, last_run_ts, last_saved_bytes,
                 last_raw_deleted, updated_at)
            VALUES (?, ?, NULL, NULL, NULL, ?)
            ON CONFLICT(address) DO UPDATE SET
                policy = excluded.policy,
                updated_at = excluded.updated_at
            """,
            (address_u, policy_n, now),
        )
        await self.db.commit()
        state = await self.get_compaction_state(address_u)
        assert state is not None
        return state

    async def preview_compaction(
        self,
        address: str,
        *,
        labels: dict[str, str] | None = None,
        now: float | None = None,
        chunk_size: int = 50_000,
    ) -> dict[str, Any] | None:
        """Dry-run every compaction policy for one device (no writes)."""
        from govee_charts.compaction import (
            COMPACTION_POLICIES,
            POLICY_LABELS,
            _BYTES_PER_ROLLUP,
            normalize_policy,
        )

        address_u = address.upper()
        device = await self.get_device(address_u)
        if device is None:
            return None

        t_now = float(now if now is not None else time.time())
        bytes_by_table = await self._table_bytes_from_dbstat()
        readings_bytes = int((bytes_by_table or {}).get("readings") or 0)
        total_cur = await self.db.execute("SELECT COUNT(*) FROM readings")
        total_raw_all = int((await total_cur.fetchone())[0] or 0)
        bytes_per_raw = (
            (readings_bytes / total_raw_all)
            if total_raw_all > 0 and readings_bytes > 0
            else 120.0
        )

        count_cur = await self.db.execute(
            "SELECT COUNT(*) FROM readings WHERE address = ?",
            (address_u,),
        )
        raw_samples = int((await count_cur.fetchone())[0] or 0)
        roll_cur = await self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(n), 0) FROM readings_rollup WHERE address = ?",
            (address_u,),
        )
        roll_row = await roll_cur.fetchone()
        rollup_rows = int(roll_row[0] or 0) if roll_row else 0
        current_bytes = int(round(raw_samples * bytes_per_raw + rollup_rows * _BYTES_PER_ROLLUP))

        label_map = {str(k).upper(): str(v) for k, v in (labels or {}).items()}
        name = label_map.get(address_u) or str(device.get("name") or address_u)

        policies_out: list[dict[str, Any]] = []
        for policy_key in COMPACTION_POLICIES:
            policy = normalize_policy(policy_key)
            if policy == "none":
                policies_out.append(
                    {
                        "policy": policy,
                        "label": POLICY_LABELS[policy],
                        "raw_kept": raw_samples,
                        "raw_deleted": 0,
                        "rollups": 0,
                        "bytes_after_est": current_bytes,
                        "bytes_saved_est": 0,
                        "pct_saved": 0.0,
                        "details": {
                            "kind": "none",
                            "note": "No compaction — keep all raw samples",
                        },
                    }
                )
                continue

            if policy == "adaptive":
                report = await self._preview_adaptive(
                    address_u,
                    t_now=t_now,
                    raw_samples=raw_samples,
                    bytes_per_raw=bytes_per_raw,
                    rollup_rows=rollup_rows,
                    chunk_size=chunk_size,
                )
            else:
                report = await self._preview_tiers(
                    address_u,
                    policy,
                    t_now=t_now,
                    raw_samples=raw_samples,
                    bytes_per_raw=bytes_per_raw,
                    rollup_rows=rollup_rows,
                )
            report["policy"] = policy
            report["label"] = POLICY_LABELS[policy]
            policies_out.append(report)

        return {
            "address": address_u,
            "name": name,
            "bytes_per_raw": bytes_per_raw,
            "current": {
                "raw_samples": raw_samples,
                "rollup_rows": rollup_rows,
                "bytes_est": current_bytes,
            },
            "policies": policies_out,
            "dry_run": True,
        }

    async def _preview_tiers(
        self,
        address_u: str,
        policy: str,
        *,
        t_now: float,
        raw_samples: int,
        bytes_per_raw: float,
        rollup_rows: int,
    ) -> dict[str, Any]:
        from govee_charts.compaction import POLICY_TIERS, _BYTES_PER_ROLLUP

        tiers = POLICY_TIERS[policy]
        tier_details: list[dict[str, Any]] = []
        raw_deleted = 0
        rollups = 0
        for older_days, younger_days, bucket_secs in tiers.tiers:
            older_ts = t_now - float(older_days) * 86400.0
            younger_ts = (
                0.0
                if younger_days is None
                else t_now - float(younger_days) * 86400.0
            )
            win_start = float(younger_ts)
            win_end = float(older_ts)
            if win_end <= win_start:
                continue
            win_cur = await self.db.execute(
                """
                SELECT COUNT(*) FROM readings
                WHERE address = ? AND ts >= ? AND ts < ?
                """,
                (address_u, win_start, win_end),
            )
            raw_in_window = int((await win_cur.fetchone())[0] or 0)
            # Closed buckets only: bucket_end <= win_end
            # bucket_start = floor(ts/b)*b, keep if bucket_start + b <= win_end
            # <=> ts < win_end - (ts % b) ... simpler: count via group by
            agg_cur = await self.db.execute(
                """
                SELECT
                    CAST(ts / ? AS INTEGER) * ? AS bucket_start,
                    COUNT(*) AS n
                FROM readings
                WHERE address = ? AND ts >= ? AND ts < ?
                GROUP BY bucket_start
                """,
                (float(bucket_secs), float(bucket_secs), address_u, win_start, win_end),
            )
            closed_rollups = 0
            closed_samples = 0
            incomplete_samples = 0
            for brow in await agg_cur.fetchall():
                b_start = float(brow[0])
                n = int(brow[1] or 0)
                if b_start + float(bucket_secs) <= win_end:
                    closed_rollups += 1
                    closed_samples += n
                else:
                    incomplete_samples += n
            raw_deleted += closed_samples
            rollups += closed_rollups
            tier_details.append(
                {
                    "older_than_days": older_days,
                    "younger_than_days": younger_days,
                    "bucket_secs": int(bucket_secs),
                    "raw_in_window": raw_in_window,
                    "rollups": closed_rollups,
                    "raw_compacted": closed_samples,
                    "raw_kept_incomplete_bucket": incomplete_samples,
                }
            )

        raw_kept = max(0, raw_samples - raw_deleted)
        bytes_after = int(
            round(raw_kept * bytes_per_raw + (rollup_rows + rollups) * _BYTES_PER_ROLLUP)
        )
        current_bytes = int(round(raw_samples * bytes_per_raw + rollup_rows * _BYTES_PER_ROLLUP))
        saved = max(0, current_bytes - bytes_after)
        return {
            "raw_kept": raw_kept,
            "raw_deleted": raw_deleted,
            "rollups": rollups,
            "bytes_after_est": bytes_after,
            "bytes_saved_est": saved,
            "pct_saved": (100.0 * saved / current_bytes) if current_bytes > 0 else 0.0,
            "details": {
                "kind": "tiers",
                "raw_days": tiers.raw_days,
                "tiers": tier_details,
            },
        }

    async def _preview_adaptive(
        self,
        address_u: str,
        *,
        t_now: float,
        raw_samples: int,
        bytes_per_raw: float,
        rollup_rows: int,
        chunk_size: int = 50_000,
    ) -> dict[str, Any]:
        from govee_charts.compaction import (
            ADAPTIVE_PARAMS,
            AdaptiveSegmenter,
            _BYTES_PER_ROLLUP,
            summarize_adaptive_segments,
        )

        params = ADAPTIVE_PARAMS
        win_end = t_now - float(params.raw_days) * 86400.0
        hot_cur = await self.db.execute(
            """
            SELECT COUNT(*) FROM readings
            WHERE address = ? AND ts >= ?
            """,
            (address_u, win_end),
        )
        samples_hot = int((await hot_cur.fetchone())[0] or 0)
        old_cur = await self.db.execute(
            """
            SELECT COUNT(*) FROM readings
            WHERE address = ? AND ts < ?
            """,
            (address_u, win_end),
        )
        samples_old = int((await old_cur.fetchone())[0] or 0)

        segmenter = AdaptiveSegmenter(params)
        # Keyset pagination by ts for stable streaming.
        cursor_ts = -1.0
        while True:
            cur = await self.db.execute(
                """
                SELECT ts, temperature_c, humidity
                FROM readings
                WHERE address = ? AND ts < ? AND ts > ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                (address_u, win_end, cursor_ts, int(chunk_size)),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            if not rows:
                break
            segmenter.feed(rows)
            cursor_ts = float(rows[-1]["ts"])
            if len(rows) < chunk_size:
                break
            await asyncio.sleep(0)

        segments = segmenter.finish()
        summary = summarize_adaptive_segments(
            segments, samples_in_window=samples_old
        )
        raw_deleted = int(summary["samples_rolled"])
        rollups = int(summary["stable_segments"])
        raw_kept = samples_hot + int(summary["samples_kept_volatile"])
        bytes_after = int(
            round(raw_kept * bytes_per_raw + (rollup_rows + rollups) * _BYTES_PER_ROLLUP)
        )
        current_bytes = int(round(raw_samples * bytes_per_raw + rollup_rows * _BYTES_PER_ROLLUP))
        saved = max(0, current_bytes - bytes_after)
        return {
            "raw_kept": raw_kept,
            "raw_deleted": raw_deleted,
            "rollups": rollups,
            "bytes_after_est": bytes_after,
            "bytes_saved_est": saved,
            "pct_saved": (100.0 * saved / current_bytes) if current_bytes > 0 else 0.0,
            "details": {
                "kind": "adaptive",
                "raw_days": params.raw_days,
                "temp_epsilon_c": params.temp_epsilon_c,
                "min_stable_samples": params.min_stable_samples,
                "min_stable_secs": params.min_stable_secs,
                "samples_hot_raw": samples_hot,
                "samples_old_window": samples_old,
                **summary,
            },
        }

    async def compact_device(
        self,
        address: str,
        policy: str,
        *,
        max_delete: int = 50_000,
        now: float | None = None,
    ) -> dict[str, int]:
        """Roll up raw readings for one device according to ``policy``.

        Fixed-tier policies use closed time buckets. ``adaptive`` merges flat
        temperature stretches (min/max/avg) and keeps swinging periods raw.
        Returns counts of upserted rollups and deleted raw rows.
        """
        from govee_charts.compaction import POLICY_TIERS, normalize_policy

        address_u = address.upper()
        policy_n = normalize_policy(policy)
        if policy_n == "none":
            return {"rollups_upserted": 0, "raw_deleted": 0, "saved_bytes_est": 0}
        if policy_n == "adaptive":
            return await self._compact_device_adaptive(
                address_u, max_delete=max_delete, now=now
            )

        tiers = POLICY_TIERS[policy_n]
        t_now = float(now if now is not None else time.time())
        rollups_upserted = 0
        raw_deleted = 0
        remaining = max(1, int(max_delete))

        for older_days, younger_days, bucket_secs in tiers.tiers:
            if remaining <= 0:
                break
            # Age window: [older_days, younger_days) → ts in (now-younger, now-older]
            older_ts = t_now - float(older_days) * 86400.0
            if younger_days is None:
                younger_ts = 0.0
            else:
                younger_ts = t_now - float(younger_days) * 86400.0
            # Only closed buckets fully older than older_ts boundary...
            # Window of raw timestamps to compact:
            # ts >= younger_ts AND ts < older_ts, and bucket fully closed:
            # floor(ts/bucket)*bucket + bucket <= older_ts  (approx: ts < older_ts)
            win_start = float(younger_ts)
            win_end = float(older_ts)
            if win_end <= win_start:
                continue

            # Cap how many buckets we process this pass via remaining deletes.
            agg_cur = await self.db.execute(
                """
                SELECT
                    CAST(ts / ? AS INTEGER) * ? AS bucket_start,
                    COUNT(*) AS n,
                    AVG(temperature_c) AS temp_avg,
                    MIN(temperature_c) AS temp_min,
                    MAX(temperature_c) AS temp_max,
                    AVG(humidity) AS hum_avg,
                    MIN(humidity) AS hum_min,
                    MAX(humidity) AS hum_max
                FROM readings
                WHERE address = ?
                  AND ts >= ?
                  AND ts < ?
                GROUP BY bucket_start
                ORDER BY bucket_start ASC
                """,
                (
                    float(bucket_secs),
                    float(bucket_secs),
                    address_u,
                    win_start,
                    win_end,
                ),
            )
            buckets = await agg_cur.fetchall()
            if not buckets:
                continue

            deleted_this_tier = 0
            for brow in buckets:
                if remaining <= 0:
                    break
                b_start = float(brow[0])
                b_end = b_start + float(bucket_secs)
                # Skip incomplete trailing bucket still inside the window edge.
                if b_end > win_end:
                    continue
                n = int(brow[1] or 0)
                if n <= 0:
                    continue
                await self.db.execute(
                    """
                    INSERT INTO readings_rollup (
                        address, bucket_start, bucket_secs,
                        temp_avg, temp_min, temp_max,
                        hum_avg, hum_min, hum_max, n, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(address, bucket_start, bucket_secs) DO UPDATE SET
                        temp_avg = excluded.temp_avg,
                        temp_min = excluded.temp_min,
                        temp_max = excluded.temp_max,
                        hum_avg = excluded.hum_avg,
                        hum_min = excluded.hum_min,
                        hum_max = excluded.hum_max,
                        n = excluded.n,
                        source = excluded.source
                    """,
                    (
                        address_u,
                        b_start,
                        int(bucket_secs),
                        float(brow[2]),
                        float(brow[3]),
                        float(brow[4]),
                        float(brow[5]),
                        float(brow[6]),
                        float(brow[7]),
                        n,
                        "compact",
                    ),
                )
                rollups_upserted += 1
                del_cur = await self.db.execute(
                    """
                    DELETE FROM readings
                    WHERE address = ? AND ts >= ? AND ts < ?
                    """,
                    (address_u, b_start, b_end),
                )
                deleted_n = int(del_cur.rowcount or 0)
                raw_deleted += deleted_n
                deleted_this_tier += deleted_n
                remaining -= deleted_n

            # Coarsen existing finer rollups that fall in this age window.
            if remaining > 0:
                fine_cur = await self.db.execute(
                    """
                    SELECT
                        CAST(bucket_start / ? AS INTEGER) * ? AS new_start,
                        SUM(n) AS n,
                        SUM(temp_avg * n) / SUM(n) AS temp_avg,
                        MIN(temp_min) AS temp_min,
                        MAX(temp_max) AS temp_max,
                        SUM(hum_avg * n) / SUM(n) AS hum_avg,
                        MIN(hum_min) AS hum_min,
                        MAX(hum_max) AS hum_max
                    FROM readings_rollup
                    WHERE address = ?
                      AND bucket_secs < ?
                      AND bucket_start >= ?
                      AND bucket_start < ?
                    GROUP BY new_start
                    """,
                    (
                        float(bucket_secs),
                        float(bucket_secs),
                        address_u,
                        int(bucket_secs),
                        win_start,
                        win_end,
                    ),
                )
                for frow in await fine_cur.fetchall():
                    new_start = float(frow[0])
                    new_end = new_start + float(bucket_secs)
                    if new_end > win_end:
                        continue
                    n_fine = int(frow[1] or 0)
                    if n_fine <= 0:
                        continue
                    existing = await (
                        await self.db.execute(
                            """
                            SELECT n, temp_avg, temp_min, temp_max,
                                   hum_avg, hum_min, hum_max
                            FROM readings_rollup
                            WHERE address = ? AND bucket_start = ? AND bucket_secs = ?
                            """,
                            (address_u, new_start, int(bucket_secs)),
                        )
                    ).fetchone()
                    if existing is not None:
                        n_old = int(existing[0] or 0)
                        n_tot = n_old + n_fine
                        temp_avg = (
                            (float(existing[1]) * n_old + float(frow[2]) * n_fine)
                            / n_tot
                        )
                        hum_avg = (
                            (float(existing[4]) * n_old + float(frow[5]) * n_fine)
                            / n_tot
                        )
                        temp_min = min(float(existing[2]), float(frow[3]))
                        temp_max = max(float(existing[3]), float(frow[4]))
                        hum_min = min(float(existing[5]), float(frow[6]))
                        hum_max = max(float(existing[6]), float(frow[7]))
                    else:
                        n_tot = n_fine
                        temp_avg = float(frow[2])
                        temp_min = float(frow[3])
                        temp_max = float(frow[4])
                        hum_avg = float(frow[5])
                        hum_min = float(frow[6])
                        hum_max = float(frow[7])
                    await self.db.execute(
                        """
                        INSERT INTO readings_rollup (
                            address, bucket_start, bucket_secs,
                            temp_avg, temp_min, temp_max,
                            hum_avg, hum_min, hum_max, n, source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(address, bucket_start, bucket_secs) DO UPDATE SET
                            temp_avg = excluded.temp_avg,
                            temp_min = excluded.temp_min,
                            temp_max = excluded.temp_max,
                            hum_avg = excluded.hum_avg,
                            hum_min = excluded.hum_min,
                            hum_max = excluded.hum_max,
                            n = excluded.n,
                            source = excluded.source
                        """,
                        (
                            address_u,
                            new_start,
                            int(bucket_secs),
                            temp_avg,
                            temp_min,
                            temp_max,
                            hum_avg,
                            hum_min,
                            hum_max,
                            n_tot,
                            "compact",
                        ),
                    )
                    rollups_upserted += 1
                    await self.db.execute(
                        """
                        DELETE FROM readings_rollup
                        WHERE address = ?
                          AND bucket_secs < ?
                          AND bucket_start >= ?
                          AND bucket_start < ?
                        """,
                        (address_u, int(bucket_secs), new_start, new_end),
                    )

        saved_est = int(raw_deleted * 120)
        await self._touch_compaction_run(
            address_u, policy_n, t_now, saved_est, raw_deleted
        )
        return {
            "rollups_upserted": rollups_upserted,
            "raw_deleted": raw_deleted,
            "saved_bytes_est": saved_est,
        }

    async def _touch_compaction_run(
        self,
        address_u: str,
        policy_n: str,
        t_now: float,
        saved_est: int,
        raw_deleted: int,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO compaction_state
                (address, policy, last_run_ts, last_saved_bytes,
                 last_raw_deleted, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                policy = excluded.policy,
                last_run_ts = excluded.last_run_ts,
                last_saved_bytes = COALESCE(compaction_state.last_saved_bytes, 0)
                    + excluded.last_saved_bytes,
                last_raw_deleted = excluded.last_raw_deleted,
                updated_at = excluded.updated_at
            """,
            (address_u, policy_n, t_now, saved_est, raw_deleted, t_now),
        )
        await self.db.commit()

    async def _compact_device_adaptive(
        self,
        address_u: str,
        *,
        max_delete: int = 50_000,
        now: float | None = None,
    ) -> dict[str, int]:
        from govee_charts.compaction import ADAPTIVE_PARAMS, find_stable_segments

        params = ADAPTIVE_PARAMS
        t_now = float(now if now is not None else time.time())
        win_end = t_now - float(params.raw_days) * 86400.0
        win_start = 0.0
        if win_end <= win_start:
            return {"rollups_upserted": 0, "raw_deleted": 0, "saved_bytes_est": 0}

        limit = max(1, int(max_delete))
        # One extra row detects truncation — then skip flushing a trailing
        # open segment that may still grow on the next pass.
        cur = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity
            FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (address_u, win_start, win_end, limit + 1),
        )
        fetched = [dict(row) for row in await cur.fetchall()]
        truncated = len(fetched) > limit
        rows = fetched[:limit]
        if not rows:
            await self._touch_compaction_run(address_u, "adaptive", t_now, 0, 0)
            return {"rollups_upserted": 0, "raw_deleted": 0, "saved_bytes_est": 0}

        segments = find_stable_segments(
            rows, params, flush_trailing=not truncated
        )
        rollups_upserted = 0
        raw_deleted = 0
        for seg in segments:
            b_secs = seg.bucket_secs
            await self.db.execute(
                """
                INSERT INTO readings_rollup (
                    address, bucket_start, bucket_secs,
                    temp_avg, temp_min, temp_max,
                    hum_avg, hum_min, hum_max, n, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address, bucket_start, bucket_secs) DO UPDATE SET
                    temp_avg = excluded.temp_avg,
                    temp_min = excluded.temp_min,
                    temp_max = excluded.temp_max,
                    hum_avg = excluded.hum_avg,
                    hum_min = excluded.hum_min,
                    hum_max = excluded.hum_max,
                    n = excluded.n,
                    source = excluded.source
                """,
                (
                    address_u,
                    float(seg.start_ts),
                    int(b_secs),
                    float(seg.temp_avg),
                    float(seg.temp_min),
                    float(seg.temp_max),
                    float(seg.hum_avg),
                    float(seg.hum_min),
                    float(seg.hum_max),
                    int(seg.n),
                    "compact/adaptive",
                ),
            )
            rollups_upserted += 1
            del_cur = await self.db.execute(
                """
                DELETE FROM readings
                WHERE address = ? AND ts >= ? AND ts <= ?
                """,
                (address_u, float(seg.start_ts), float(seg.end_ts)),
            )
            raw_deleted += int(del_cur.rowcount or 0)

        saved_est = int(raw_deleted * 120)
        await self._touch_compaction_run(
            address_u, "adaptive", t_now, saved_est, raw_deleted
        )
        return {
            "rollups_upserted": rollups_upserted,
            "raw_deleted": raw_deleted,
            "saved_bytes_est": saved_est,
        }

    async def device_source_series(
        self,
        addresses: list[str],
        start_ts: float,
        end_ts: float,
        node_id: str,
        *,
        grain: str = "day",
    ) -> list[dict[str, Any]]:
        """Sample counts by provenance for one or more devices.

        ``grain`` is ``day`` (UTC calendar day) or ``hour`` (UTC hour buckets).
        Counts are summed across all ``addresses``.
        """
        addrs = sorted({str(a).strip().upper() for a in addresses if str(a).strip()})
        if not addrs:
            return []
        grain_l = str(grain or "day").strip().lower()
        if grain_l not in ("day", "hour"):
            raise ValueError("grain must be 'day' or 'hour'")

        if grain_l == "hour":
            # SQLite: floor to hour as unix epoch, then format.
            period_sql = (
                "strftime('%Y-%m-%dT%H:00:00Z', "
                "CAST(ts / 3600 AS INTEGER) * 3600, 'unixepoch')"
            )
        else:
            period_sql = "strftime('%Y-%m-%d', ts, 'unixepoch')"

        bucket_sql = source_bucket_sql("source")
        placeholders = ",".join("?" for _ in addrs)
        cursor = await self.db.execute(
            f"""
            SELECT
                {period_sql} AS period,
                {bucket_sql} AS bucket,
                COUNT(*) AS n
            FROM readings
            WHERE address IN ({placeholders})
              AND ts >= ? AND ts < ?
            GROUP BY period, bucket
            ORDER BY period ASC
            """,
            (str(node_id).strip(), *addrs, float(start_ts), float(end_ts)),
        )
        by_period: dict[str, dict[str, int]] = {}
        for row in await cursor.fetchall():
            period = str(row[0])
            bucket = str(row[1] or "other")
            if bucket not in ("direct", "backfill", "federation", "other"):
                bucket = "other"
            entry = by_period.setdefault(
                period,
                {"direct": 0, "backfill": 0, "federation": 0, "other": 0},
            )
            entry[bucket] = int(row[2] or 0)

        out: list[dict[str, Any]] = []
        empty = {"direct": 0, "backfill": 0, "federation": 0, "other": 0}
        start = datetime.fromtimestamp(float(start_ts), tz=timezone.utc)
        end = datetime.fromtimestamp(
            max(float(start_ts), float(end_ts) - 1e-6), tz=timezone.utc
        )
        if grain_l == "hour":
            cur = start.replace(minute=0, second=0, microsecond=0)
            step = timedelta(hours=1)
            while cur <= end:
                key = cur.strftime("%Y-%m-%dT%H:00:00Z")
                out.append({"t": key, **by_period.get(key, empty)})
                cur = cur + step
        else:
            cur_d = start.date()
            end_d = end.date()
            while cur_d <= end_d:
                key = cur_d.isoformat()
                out.append({"t": key, **by_period.get(key, empty)})
                cur_d = cur_d + timedelta(days=1)
        return out

    async def device_source_daily(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
        node_id: str,
    ) -> list[dict[str, Any]]:
        """Daily sample counts by provenance for one device (compat wrapper)."""
        series = await self.device_source_series(
            [address], start_ts, end_ts, node_id, grain="day"
        )
        return [{"day": row["t"], **{k: row[k] for k in ("direct", "backfill", "federation", "other")}} for row in series]

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
        deleted = int(cursor.rowcount or 0)
        roll_cur = await self.db.execute(
            "DELETE FROM readings_rollup WHERE bucket_start < ?",
            (cutoff,),
        )
        deleted += int(roll_cur.rowcount or 0)
        await self.db.commit()
        return deleted

    async def list_devices(self, *, include_stats: bool = True) -> list[dict[str, Any]]:
        # ~120 B/row incl. indexes — rough SQLite footprint for one readings row.
        bytes_per_reading = 120
        if include_stats:
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
                    d.height_cm,
                    d.label,
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
        else:
            # Fast path for frequent polls (backfill UI): skip full-table aggregates.
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
                    d.height_cm,
                    d.label,
                    d.room,
                    r.temperature_c,
                    r.humidity,
                    r.battery,
                    r.rssi,
                    r.ts AS last_reading_ts,
                    r.source AS last_source,
                    0 AS sample_count,
                    NULL AS oldest_ts,
                    NULL AS newest_ts
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
                d.height_cm,
                d.label,
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
        height_cm: float | None | object = ...,
        room: str | None | object = ...,
        label: str | None | object = ...,
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
        if height_cm is not ...:
            fields.append("height_cm = ?")
            values.append(height_cm)
        if room is not ...:
            fields.append("room = ?")
            values.append(room)
        if label is not ...:
            fields.append("label = ?")
            values.append(label)
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

        devices = await self.list_devices(include_stats=False)
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

        Merges raw samples with compacted rollups (avg as the series value).
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

        address_u = address.upper()
        cursor = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity, battery, rssi, source
            FROM readings
            WHERE address = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (address_u, start, end),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        roll_cur = await self.db.execute(
            """
            SELECT
                bucket_start + (bucket_secs / 2.0) AS ts,
                temp_avg AS temperature_c,
                hum_avg AS humidity,
                temp_min,
                temp_max,
                hum_min,
                hum_max,
                n,
                bucket_secs,
                source
            FROM readings_rollup
            WHERE address = ?
              AND bucket_start + bucket_secs >= ?
              AND bucket_start <= ?
            ORDER BY bucket_start ASC
            """,
            (address_u, start, end),
        )
        for row in await roll_cur.fetchall():
            item = dict(row)
            item["battery"] = None
            item["rssi"] = None
            item["rollup"] = True
            rows.append(item)
        rows.sort(key=lambda r: float(r["ts"]))
        return _downsample_readings(rows, max_points=max(100, int(max_points)))

    async def recent_readings(
        self,
        address: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Latest readings for one device (no time window or downsampling)."""
        lim = max(1, min(int(limit), 100))
        cursor = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity, battery, rssi, source
            FROM readings
            WHERE address = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (address.upper(), lim),
        )
        return [dict(row) for row in await cursor.fetchall()]

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

        Combines raw readings and compacted rollups (weighted by sample count).
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
            period_expr = "strftime('%Y-%m-%d', {ts}, 'unixepoch', 'localtime')"
        elif key == "week":
            # ISO week-year + week number (Monday-based).
            period_expr = (
                "printf('%s-W%02d', "
                "strftime('%G', {ts}, 'unixepoch', 'localtime'), "
                "CAST(strftime('%V', {ts}, 'unixepoch', 'localtime') AS INTEGER))"
            )
        else:
            period_expr = "strftime('%Y-%m', {ts}, 'unixepoch', 'localtime')"

        raw_period = period_expr.format(ts="ts")
        roll_period = period_expr.format(ts="bucket_start + (bucket_secs / 2.0)")

        cursor = await self.db.execute(
            f"""
            SELECT
                {raw_period} AS period,
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
        merged: dict[str, dict[str, Any]] = {}
        for row in await cursor.fetchall():
            period = str(row[0])
            n = int(row[1] or 0)
            merged[period] = {
                "period": period,
                "count": n,
                "temp_sum": float(row[2] or 0) * n,
                "temp_min": float(row[3]) if row[3] is not None else None,
                "temp_max": float(row[4]) if row[4] is not None else None,
                "hum_sum": float(row[5] or 0) * n,
                "hum_min": float(row[6]) if row[6] is not None else None,
                "hum_max": float(row[7]) if row[7] is not None else None,
                "ts_min": float(row[8]) if row[8] is not None else None,
                "ts_max": float(row[9]) if row[9] is not None else None,
            }

        roll_cur = await self.db.execute(
            f"""
            SELECT
                {roll_period} AS period,
                SUM(n) AS n,
                SUM(temp_avg * n) / SUM(n) AS temp_avg,
                MIN(temp_min) AS temp_min,
                MAX(temp_max) AS temp_max,
                SUM(hum_avg * n) / SUM(n) AS hum_avg,
                MIN(hum_min) AS hum_min,
                MAX(hum_max) AS hum_max,
                MIN(bucket_start) AS ts_min,
                MAX(bucket_start + bucket_secs) AS ts_max
            FROM readings_rollup
            WHERE address = ?
              AND bucket_start + bucket_secs > ?
              AND bucket_start < ?
            GROUP BY period
            ORDER BY period ASC
            """,
            (address, start_ts, end_ts),
        )
        for row in await roll_cur.fetchall():
            period = str(row[0])
            n = int(row[1] or 0)
            if n <= 0:
                continue
            entry = merged.get(period)
            if entry is None:
                merged[period] = {
                    "period": period,
                    "count": n,
                    "temp_sum": float(row[2] or 0) * n,
                    "temp_min": float(row[3]) if row[3] is not None else None,
                    "temp_max": float(row[4]) if row[4] is not None else None,
                    "hum_sum": float(row[5] or 0) * n,
                    "hum_min": float(row[6]) if row[6] is not None else None,
                    "hum_max": float(row[7]) if row[7] is not None else None,
                    "ts_min": float(row[8]) if row[8] is not None else None,
                    "ts_max": float(row[9]) if row[9] is not None else None,
                }
                continue
            entry["count"] += n
            entry["temp_sum"] += float(row[2] or 0) * n
            entry["hum_sum"] += float(row[5] or 0) * n
            for field, val, op in (
                ("temp_min", row[3], min),
                ("temp_max", row[4], max),
                ("hum_min", row[6], min),
                ("hum_max", row[7], max),
                ("ts_min", row[8], min),
                ("ts_max", row[9], max),
            ):
                if val is None:
                    continue
                fv = float(val)
                cur = entry[field]
                entry[field] = fv if cur is None else op(cur, fv)

        out: list[dict[str, Any]] = []
        for period in sorted(merged.keys()):
            e = merged[period]
            n = int(e["count"])
            out.append(
                {
                    "period": period,
                    "count": n,
                    "temperature_c": {
                        "avg": round(e["temp_sum"] / n, 2) if n else None,
                        "min": round(e["temp_min"], 2)
                        if e["temp_min"] is not None
                        else None,
                        "max": round(e["temp_max"], 2)
                        if e["temp_max"] is not None
                        else None,
                    },
                    "humidity": {
                        "avg": round(e["hum_sum"] / n, 2) if n else None,
                        "min": round(e["hum_min"], 2)
                        if e["hum_min"] is not None
                        else None,
                        "max": round(e["hum_max"], 2)
                        if e["hum_max"] is not None
                        else None,
                    },
                    "range": {
                        "start": e["ts_min"],
                        "end": e["ts_max"],
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
        # Prefer Ring MQTT UUID rows over HA recorder mirrors of the same Ring
        # contact (binary_sensor.porte_cuisine, …). Keep distinct HA devices
        # such as Tuya door_sensor_* even when the display name matches.
        import unicodedata

        def _norm_name(value: str) -> str:
            text = unicodedata.normalize("NFKD", value or "")
            text = "".join(c for c in text if not unicodedata.combining(c))
            text = text.replace("'", " ").replace("'", " ")
            return " ".join(text.lower().split())

        def _is_ha_ring_mirror(sensor_id: str) -> bool:
            sid = str(sensor_id or "")
            if not sid.startswith("binary_sensor."):
                return False
            slug = sid.removeprefix("binary_sensor.")
            if slug.startswith("door_sensor") or "konyks" in slug:
                return False
            return slug.startswith(("porte_", "fenetre_", "fenêtre_", "window_"))

        def _is_distinct_ha(sensor_id: str) -> bool:
            sid = str(sensor_id or "")
            if not sid.startswith("binary_sensor."):
                return False
            slug = sid.removeprefix("binary_sensor.")
            return slug.startswith("door_sensor") or "konyks" in slug

        def _dedupe_key(row: dict[str, Any]) -> str:
            sid = str(row.get("sensor_id") or "")
            name_key = _norm_name(str(row.get("name") or "")) or sid
            if _is_distinct_ha(sid):
                return f"id:{sid}"
            return f"name:{name_key}"

        by_key: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = _dedupe_key(row)
            prev = by_key.get(key)
            if prev is None:
                by_key[key] = row
                continue
            if key.startswith("name:"):
                prev_is_mirror = _is_ha_ring_mirror(str(prev.get("sensor_id") or ""))
                cur_is_mirror = _is_ha_ring_mirror(str(row.get("sensor_id") or ""))
                if prev_is_mirror and not cur_is_mirror:
                    by_key[key] = row
                    continue
                if cur_is_mirror and not prev_is_mirror:
                    continue
            if float(row.get("ts") or 0) > float(prev.get("ts") or 0):
                by_key[key] = row
        return sorted(
            by_key.values(),
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

        def _is_ha_ring_mirror(sensor_id: str) -> bool:
            sid = str(sensor_id or "")
            if not sid.startswith("binary_sensor."):
                return False
            slug = sid.removeprefix("binary_sensor.")
            if slug.startswith("door_sensor") or "konyks" in slug:
                return False
            return slug.startswith(("porte_", "fenetre_", "fenêtre_", "window_"))

        def _is_distinct_ha(sensor_id: str) -> bool:
            sid = str(sensor_id or "")
            if not sid.startswith("binary_sensor."):
                return False
            slug = sid.removeprefix("binary_sensor.")
            return slug.startswith("door_sensor") or "konyks" in slug

        def _stream_key(row: dict[str, Any]) -> str:
            sid = str(row.get("sensor_id") or "")
            name_key = _norm_name(str(row.get("name") or "")) or sid
            if _is_distinct_ha(sid):
                return f"id:{sid}"
            return f"name:{name_key}"

        by_name: dict[str, list[dict[str, Any]]] = {}
        kinds_by_name: dict[str, str] = {}
        for row in rows:
            key = _stream_key(row)
            sid = str(row.get("sensor_id") or "")
            is_ha_mirror = _is_ha_ring_mirror(sid)
            kind = str(row.get("kind") or "").lower()
            if key not in by_name:
                by_name[key] = []
                kinds_by_name[key] = kind
            # Prefer Ring UUID stream over HA recorder mirrors of the same Ring contact.
            if is_ha_mirror and by_name[key] and not _is_ha_ring_mirror(
                str(by_name[key][0].get("sensor_id") or "")
            ):
                continue
            if (not is_ha_mirror) and by_name[key] and _is_ha_ring_mirror(
                str(by_name[key][0].get("sensor_id") or "")
            ):
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

    async def reading_values_by_minute(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
    ) -> dict[int, tuple[float, float, float]]:
        """Map unix-minute index → (ts, temperature_c, humidity) in [start_ts, end_ts)."""
        cursor = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (address.upper(), float(start_ts), float(end_ts)),
        )
        out: dict[int, tuple[float, float, float]] = {}
        for row in await cursor.fetchall():
            ts = float(row[0])
            minute = int(ts // 60)
            out[minute] = (ts, float(row[1]), float(row[2]))
        return out

    async def reading_rows_in_range(
        self,
        address: str,
        start_ts: float,
        end_ts: float,
    ) -> list[tuple[float, float, float, str | None]]:
        """All readings in [start_ts, end_ts) as (ts, temp, humidity, source)."""
        cursor = await self.db.execute(
            """
            SELECT ts, temperature_c, humidity, source FROM readings
            WHERE address = ? AND ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (address.upper(), float(start_ts), float(end_ts)),
        )
        return [
            (
                float(row[0]),
                float(row[1]),
                float(row[2]),
                str(row[3]) if row[3] is not None else None,
            )
            for row in await cursor.fetchall()
        ]

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
            name = (
                str(device.get("label") or "").strip()
                or labels.get(addr)
                or str(device.get("name") or addr)
            )
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

    async def recent_backfill_jobs_for_address(
        self,
        address: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Most recently updated backfill jobs for one sensor."""
        limit = max(1, min(int(limit), 50))
        cursor = await self.db.execute(
            """
            SELECT id, address, phase, window_start, window_end, status,
                   priority, samples_done, samples_expected, error, updated_at
            FROM backfill_jobs
            WHERE address = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (address.upper(), limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

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
                MIN(priority) AS priority,
                (
                    SELECT b2.phase
                    FROM backfill_jobs b2
                    WHERE b2.address = backfill_jobs.address
                      AND b2.status IN ('pending', 'deferred')
                    ORDER BY b2.priority ASC, b2.window_end DESC, b2.id ASC
                    LIMIT 1
                ) AS phase
            FROM backfill_jobs
            WHERE status IN ('pending', 'deferred')
            GROUP BY address
            """
        )
        rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "address": str(row[0]).upper(),
                    "jobs": int(row[1]),
                    "samples_expected": int(row[2]),
                    "priority": int(row[3]),
                    "phase": str(row[4] or "hour"),
                }
            )
        return out

    async def local_rssi_map(self, node_id: str) -> dict[str, int]:
        """Latest RSSI from readings produced by this node (not peer ingest)."""
        node_id = str(node_id).strip()
        gatt = f"{node_id}/gatt"
        # Prefer indexed per-address lookups over a full-table GROUP BY on source.
        cursor = await self.db.execute("SELECT address FROM devices")
        addresses = [str(row[0]).upper() for row in await cursor.fetchall() if row[0]]
        out: dict[str, int] = {}
        for address in addresses:
            cur = await self.db.execute(
                """
                SELECT rssi FROM readings
                WHERE address = ?
                  AND rssi IS NOT NULL
                  AND (source = ? OR source = ?)
                ORDER BY ts DESC
                LIMIT 1
                """,
                (address, node_id, gatt),
            )
            row = await cur.fetchone()
            if not row:
                continue
            try:
                out[address] = int(row[0])
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
                   last_battery, COALESCE(enabled, 0) AS enabled,
                   COALESCE(gatt_enabled, 1) AS gatt_enabled
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
        out["gatt_enabled"] = bool(int(out.get("gatt_enabled") if out.get("gatt_enabled") is not None else 1))
        return out

    async def list_backfill_enabled(self) -> set[str]:
        """Addresses opted in for history backfill."""
        cursor = await self.db.execute(
            """
            SELECT address FROM backfill_state
            WHERE COALESCE(enabled, 0) = 1
            """
        )
        return {str(row[0]).upper() for row in await cursor.fetchall()}

    async def list_backfill_flags(self) -> dict[str, dict[str, bool]]:
        """address -> {enabled, gatt_enabled} for known backfill_state rows."""
        cursor = await self.db.execute(
            """
            SELECT address,
                   COALESCE(enabled, 0) AS enabled,
                   COALESCE(gatt_enabled, 1) AS gatt_enabled
            FROM backfill_state
            """
        )
        out: dict[str, dict[str, bool]] = {}
        for row in await cursor.fetchall():
            addr = str(row[0]).upper()
            out[addr] = {
                "enabled": bool(int(row[1] or 0)),
                "gatt_enabled": bool(
                    int(row[2] if row[2] is not None else 1)
                ),
            }
        return out

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

    async def is_backfill_gatt_enabled(self, address: str) -> bool:
        """Whether remaining gaps may use GATT after federation pull (default true)."""
        cursor = await self.db.execute(
            """
            SELECT COALESCE(gatt_enabled, 1) FROM backfill_state
            WHERE address = ?
            """,
            (address.upper(),),
        )
        row = await cursor.fetchone()
        if not row:
            return True
        return bool(int(row[0] if row[0] is not None else 1))

    async def set_backfill_enabled(self, address: str, enabled: bool) -> bool:
        """Persist opt-in flag. Returns the stored enabled value."""
        flags = await self.set_backfill_flags(address, enabled=enabled)
        return flags["enabled"]

    async def set_backfill_flags(
        self,
        address: str,
        *,
        enabled: bool | None = None,
        gatt_enabled: bool | None = None,
    ) -> dict[str, bool]:
        """Persist opt-in and/or GATT flags. Returns stored values."""
        if enabled is None and gatt_enabled is None:
            raise ValueError("enabled or gatt_enabled required")
        address = address.upper()
        existing = await self.get_backfill_state(address)
        en = (
            bool(enabled)
            if enabled is not None
            else bool((existing or {}).get("enabled"))
        )
        gatt = (
            bool(gatt_enabled)
            if gatt_enabled is not None
            else (
                True
                if existing is None
                else bool((existing or {}).get("gatt_enabled", True))
            )
        )
        await self.db.execute(
            """
            INSERT INTO backfill_state
                (address, last_success_ts, last_attempt_ts, last_rssi,
                 last_battery, enabled, gatt_enabled)
            VALUES (?, NULL, NULL, NULL, NULL, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                enabled = excluded.enabled,
                gatt_enabled = excluded.gatt_enabled
            """,
            (address, 1 if en else 0, 1 if gatt else 0),
        )
        await self.db.commit()
        return {"enabled": en, "gatt_enabled": gatt}

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
        gatt_enabled = (
            1
            if existing is None or (existing or {}).get("gatt_enabled", True)
            else 0
        )
        await self.db.execute(
            """
            INSERT INTO backfill_state
                (address, last_success_ts, last_attempt_ts, last_rssi,
                 last_battery, enabled, gatt_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                last_success_ts = excluded.last_success_ts,
                last_attempt_ts = excluded.last_attempt_ts,
                last_rssi = COALESCE(excluded.last_rssi, backfill_state.last_rssi),
                last_battery = COALESCE(excluded.last_battery, backfill_state.last_battery),
                enabled = backfill_state.enabled,
                gatt_enabled = backfill_state.gatt_enabled
            """,
            (address, success_ts, attempt, rssi, battery, enabled, gatt_enabled),
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
        overwrite: bool = False,
        eps_temp: float = 0.05,
        eps_hum: float = 0.05,
    ) -> dict[str, int]:
        """
        Bulk insert GATT/CSV history samples. samples: (ts, temp, humidity).

        Returns ``{"inserted": n, "overwritten": m}``.
        With ``overwrite=False`` (default), existing minutes are skipped
        (``INSERT OR IGNORE`` on exact ``ts``).
        With ``overwrite=True``, conflicting minutes are updated in place (matched
        by unix minute even if the stored ``ts`` is not minute-aligned);
        ``overwritten`` counts minutes whose temp/humidity changed beyond epsilon.
        """
        address = address.upper()
        if not samples:
            return {"inserted": 0, "overwritten": 0}
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

        # Deduplicate by minute (last sample wins); keep sample ts for inserts.
        by_minute: dict[int, tuple[float, float, float]] = {}
        for ts, temp, hum in samples:
            minute = int(float(ts) // 60)
            by_minute[minute] = (float(ts), float(temp), float(hum))

        floored = [float(m * 60) for m in by_minute]
        win_start = min(first_ts, min(floored)) - 1.0
        win_end = max(last_ts, max(floored)) + 61.0

        if not overwrite:
            before = await self.reading_exact_minutes(address, win_start, win_end)
            await self.db.executemany(
                """
                INSERT OR IGNORE INTO readings
                    (address, ts, temperature_c, humidity, battery, rssi, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (address, ts, temp, hum, int(battery), rssi, source)
                    for ts, temp, hum in by_minute.values()
                ],
            )
            await self.db.commit()
            after = await self.reading_exact_minutes(address, win_start, win_end)
            return {
                "inserted": max(0, len(after) - len(before)),
                "overwritten": 0,
            }

        before_values = await self.reading_values_by_minute(address, win_start, win_end)
        inserted = 0
        overwritten = 0
        insert_rows: list[tuple] = []
        for minute, (ts, temp, hum) in by_minute.items():
            old = before_values.get(minute)
            if old is None:
                inserted += 1
                insert_rows.append(
                    (address, ts, temp, hum, int(battery), rssi, source)
                )
            else:
                old_ts, old_temp, old_hum = old
                if abs(old_temp - temp) > eps_temp or abs(old_hum - hum) > eps_hum:
                    overwritten += 1
                await self.db.execute(
                    """
                    UPDATE readings
                    SET temperature_c = ?, humidity = ?, battery = ?, rssi = ?, source = ?
                    WHERE address = ? AND ts = ?
                    """,
                    (temp, hum, int(battery), rssi, source, address, old_ts),
                )

        if insert_rows:
            await self.db.executemany(
                """
                INSERT INTO readings
                    (address, ts, temperature_c, humidity, battery, rssi, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
        await self.db.commit()
        return {"inserted": inserted, "overwritten": overwritten}

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

