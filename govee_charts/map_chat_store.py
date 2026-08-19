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
            CREATE TABLE IF NOT EXISTS map_chat_sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                custom_title TEXT
            );
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
    ) -> dict[str, Any]:
        sid = (session_id or "").strip() or "unknown"
        if isinstance(snapshot, str):
            snap_text = snapshot
        else:
            snap_text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        banner_text = None
        if banner is not None:
            banner_text = json.dumps(banner, ensure_ascii=False, separators=(",", ":"))
        created_at = time.time()
        await self.db.execute(
            """
            INSERT INTO map_chat_sessions (session_id, created_at, updated_at, custom_title)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (sid, created_at, created_at),
        )
        cur = await self.db.execute(
            """
            INSERT INTO map_chat_exchanges (
                session_id, created_at, user_message, assistant_message,
                error, model, snapshot_json, banner_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                created_at,
                (user_message or "").strip(),
                (assistant_message or "").strip() or None,
                (error or "").strip() or None,
                (model or "").strip() or None,
                snap_text,
                banner_text,
            ),
        )
        return {
            "id": int(cur.lastrowid or 0),
            "session_id": sid,
            "created_at": created_at,
        }

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
        """Recent chat sessions with preview and optional custom title."""
        lim = max(1, min(int(limit), 100))
        cur = await self.db.execute(
            """
            SELECT
                e1.session_id,
                COALESCE(s.created_at, MIN(e1.created_at)) AS started_at,
                COALESCE(s.updated_at, MAX(e1.created_at)) AS updated_at,
                COUNT(*) AS turn_count,
                s.custom_title AS title,
                (
                    SELECT user_message
                    FROM map_chat_exchanges AS e2
                    WHERE e2.session_id = e1.session_id
                    ORDER BY e2.created_at ASC, e2.id ASC
                    LIMIT 1
                ) AS first_message
            FROM map_chat_exchanges AS e1
            LEFT JOIN map_chat_sessions AS s
                ON s.session_id = e1.session_id
            WHERE e1.session_id != '' AND e1.session_id != 'unknown'
            GROUP BY e1.session_id
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
                    "title": str(row["title"] or "").strip() or None,
                    "preview": preview,
                }
            )
        return out

    async def rename_session(
        self, session_id: str, title: str | None
    ) -> dict[str, Any] | None:
        sid = (session_id or "").strip()
        if not sid or sid == "unknown":
            return None
        cur = await self.db.execute(
            "SELECT 1 FROM map_chat_exchanges WHERE session_id = ? LIMIT 1",
            (sid,),
        )
        if await cur.fetchone() is None:
            return None
        now = time.time()
        clean_title = str(title or "").strip()[:120] or None
        await self.db.execute(
            """
            INSERT INTO map_chat_sessions (session_id, created_at, updated_at, custom_title)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                custom_title = excluded.custom_title
            """,
            (sid, now, now, clean_title),
        )
        cur = await self.db.execute(
            """
            SELECT
                e1.session_id,
                COALESCE(s.created_at, MIN(e1.created_at)) AS started_at,
                COALESCE(s.updated_at, MAX(e1.created_at)) AS updated_at,
                COUNT(*) AS turn_count,
                s.custom_title AS title,
                (
                    SELECT user_message
                    FROM map_chat_exchanges AS e2
                    WHERE e2.session_id = e1.session_id
                    ORDER BY e2.created_at ASC, e2.id ASC
                    LIMIT 1
                ) AS first_message
            FROM map_chat_exchanges AS e1
            LEFT JOIN map_chat_sessions AS s
                ON s.session_id = e1.session_id
            WHERE e1.session_id = ?
            GROUP BY e1.session_id
            LIMIT 1
            """,
            (sid,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        preview = str(row["first_message"] or "").strip().replace("\n", " ")
        if len(preview) > 72:
            preview = preview[:71] + "…"
        return {
            "session_id": row["session_id"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "turn_count": int(row["turn_count"] or 0),
            "title": str(row["title"] or "").strip() or None,
            "preview": preview,
        }

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
