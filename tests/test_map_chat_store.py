from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from govee_charts.map_chat_store import MapChatStore


class MapChatStoreSessionTitleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MapChatStore(Path(self._tmp.name) / "map_chat.db")
        await self.store.connect()
        self.addAsyncCleanup(self.store.close)

    async def test_list_sessions_uses_custom_title_when_present(self):
        await self.store.add_exchange(
            session_id="abc123",
            user_message="How is the bedroom doing tonight?",
            assistant_message="Cooler than the living room.",
            error=None,
            model="auto",
            snapshot={"rooms": []},
            banner=None,
        )

        sessions = await self.store.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0]["title"])
        self.assertIn("bedroom", sessions[0]["preview"].lower())

        renamed = await self.store.rename_session("abc123", "Bedroom evening")
        self.assertIsNotNone(renamed)
        self.assertEqual(renamed["title"], "Bedroom evening")

        sessions = await self.store.list_sessions()
        self.assertEqual(sessions[0]["title"], "Bedroom evening")
        self.assertIn("bedroom", sessions[0]["preview"].lower())

    async def test_rename_session_can_clear_custom_title(self):
        await self.store.add_exchange(
            session_id="clear-me",
            user_message="Need a short title",
            assistant_message="Sure.",
            error=None,
            model="auto",
            snapshot={"rooms": []},
            banner=None,
        )

        await self.store.rename_session("clear-me", "Temporary title")
        cleared = await self.store.rename_session("clear-me", "   ")

        self.assertIsNotNone(cleared)
        self.assertIsNone(cleared["title"])


if __name__ == "__main__":
    unittest.main()
