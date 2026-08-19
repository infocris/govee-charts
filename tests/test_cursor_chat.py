"""Map chat stream: do not glue thinking + answer; keep the last message."""

from __future__ import annotations

import unittest

from govee_charts.cursor_chat import _delta_from_assistant, _prefer_last_message


class DeltaFromAssistantTests(unittest.TestCase):
    def test_growing_partial_emits_suffix_only(self):
        pieces: list[str] = []
        delta, replace = _delta_from_assistant(pieces, "La question est un test")
        self.assertEqual(delta, "La question est un test")
        self.assertFalse(replace)
        delta, replace = _delta_from_assistant(
            pieces, "La question est un test du conseil climatique : je m"
        )
        self.assertEqual(delta, " du conseil climatique : je m")
        self.assertFalse(replace)
        # Typographic apostrophe (U+2019) must stay in the suffix, not reset.
        full = "La question est un test du conseil climatique : je m\u2019appuie"
        delta, replace = _delta_from_assistant(pieces, full)
        self.assertEqual(delta, "\u2019appuie")
        self.assertFalse(replace)
        self.assertEqual("".join(pieces), full)

    def test_new_message_after_tools_replaces(self):
        pieces: list[str] = []
        _delta_from_assistant(
            pieces,
            "La question est un test du conseil climatique : je m\u2019appuie.",
        )
        answer = "**Conseil v2 :** garder la fenêtre du séjour ouverte."
        delta, replace = _delta_from_assistant(pieces, answer)
        self.assertTrue(replace)
        self.assertEqual(delta, answer)
        self.assertEqual("".join(pieces), answer)

    def test_shorter_snapshot_is_ignored(self):
        pieces: list[str] = []
        long = "Hello world, this is a long sentence"
        _delta_from_assistant(pieces, long)
        delta, replace = _delta_from_assistant(pieces, "Hello world")
        self.assertIsNone(delta)
        self.assertFalse(replace)
        self.assertEqual("".join(pieces), long)

    def test_duplicate_event_is_ignored(self):
        pieces: list[str] = []
        text = "Same text"
        _delta_from_assistant(pieces, text)
        delta, replace = _delta_from_assistant(pieces, text)
        self.assertIsNone(delta)
        self.assertFalse(replace)


class PreferLastMessageTests(unittest.TestCase):
    def test_concatenated_result_keeps_last_turn(self):
        thinking = "La question est un test du conseil climatique : je m\u2019appuie."
        answer = "**Conseil v2 :** garder la fenêtre du séjour ouverte."
        result = thinking + answer
        self.assertEqual(_prefer_last_message(answer, result), answer)

    def test_result_can_extend_last_message(self):
        last = "Hello"
        self.assertEqual(_prefer_last_message(last, "Hello world"), "Hello world")

    def test_empty_last_uses_result(self):
        self.assertEqual(_prefer_last_message("", "only result"), "only result")


if __name__ == "__main__":
    unittest.main()
