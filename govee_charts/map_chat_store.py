"""Separate SQLite store for Map Cursor chat history + request context."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite


class MapChatStore:
    """Persists chat turns outside readings.db (sensor snapshot + advice banner)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("MapChatStore is not connected")
        return self._db

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS map_chat_exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                user_message TEXT NOT NULL,
                assistant_message TEXT,
                error TEXT,
                model TEXT,
                snapshot_json TEXT NOT NULL,
                banner_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_map_chat_session_created
                ON map_chat_exchanges(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_map_chat_created
                ON map_chat_exchanges(created_at);
            """
        )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def add_exchange(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_message: str | None,
        error: str | None,
        model: str | None,
        snapshot: dict[str, Any] | str,
        banner: dict[str, Any] | None,
    ) -> int:
        sid = (session_id or "").strip() or "unknown"
        if isinstance(snapshot, str):
            snap_text = snapshot
        else:
            snap_text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        banner_text = None
        if banner is not None:
            banner_text = json.dumps(banner, ensure_ascii=False, separators=(",", ":"))
        cur = await self.db.execute(
            """
            INSERT INTO map_chat_exchanges (
                session_id, created_at, user_message, assistant_message,
                error, model, snapshot_json, banner_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                time.time(),
                (user_message or "").strip(),
                (assistant_message or "").strip() or None,
                (error or "").strip() or None,
                (model or "").strip() or None,
                snap_text,
                banner_text,
            ),
        )
        return int(cur.lastrowid or 0)

    async def list_exchanges(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        include_snapshot: bool = False,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 200))
        sid = (session_id or "").strip()
        if sid:
            cur = await self.db.execute(
                """
                SELECT id, session_id, created_at, user_message, assistant_message,
                       error, model, snapshot_json, banner_json
                FROM map_chat_exchanges
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (sid, lim),
            )
        else:
            cur = await self.db.execute(
                """
                SELECT id, session_id, created_at, user_message, assistant_message,
                       error, model, snapshot_json, banner_json
                FROM map_chat_exchanges
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (lim,),
            )
        rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = self._row_to_dict(row, include_snapshot=include_snapshot)
            out.append(item)
        if not sid:
            out.reverse()
        return out

    async def get_exchange(self, exchange_id: int) -> dict[str, Any] | None:
        cur = await self.db.execute(
            """
            SELECT id, session_id, created_at, user_message, assistant_message,
                   error, model, snapshot_json, banner_json
            FROM map_chat_exchanges
            WHERE id = ?
            """,
            (int(exchange_id),),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, include_snapshot=True)

    async def list_sessions(self, *, limit: int = 40) -> list[dict[str, Any]]:
        """Recent chat sessions with preview of the first user message."""
        lim = max(1, min(int(limit), 100))
        cur = await self.db.execute(
            """
            SELECT
                session_id,
                MIN(created_at) AS started_at,
                MAX(created_at) AS updated_at,
                COUNT(*) AS turn_count,
                (
                    SELECT user_message
                    FROM map_chat_exchanges AS e2
                    WHERE e2.session_id = e1.session_id
                    ORDER BY e2.created_at ASC, e2.id ASC
                    LIMIT 1
                ) AS first_message
            FROM map_chat_exchanges AS e1
            WHERE session_id != '' AND session_id != 'unknown'
            GROUP BY session_id
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (lim,),
        )
        rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            preview = str(row["first_message"] or "").strip().replace("\n", " ")
            if len(preview) > 72:
                preview = preview[:71] + "…"
            out.append(
                {
                    "session_id": row["session_id"],
                    "started_at": row["started_at"],
                    "updated_at": row["updated_at"],
                    "turn_count": int(row["turn_count"] or 0),
                    "preview": preview,
                }
            )
        return out

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row, *, include_snapshot: bool) -> dict[str, Any]:
        banner = None
        raw_banner = row["banner_json"]
        if raw_banner:
            try:
                banner = json.loads(raw_banner)
            except json.JSONDecodeError:
                banner = {"raw": raw_banner}
        item: dict[str, Any] = {
            "id": row["id"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "user_message": row["user_message"],
            "assistant_message": row["assistant_message"],
            "error": row["error"],
            "model": row["model"],
            "banner": banner,
        }
        if include_snapshot:
            snap = row["snapshot_json"]
            try:
                item["snapshot"] = json.loads(snap) if snap else None
            except json.JSONDecodeError:
                item["snapshot"] = {"raw": snap}
        else:
            item["has_snapshot"] = bool(row["snapshot_json"])
        return item
