"""memtrim helpers must be safe on every platform."""

from __future__ import annotations

import sys

from govee_charts import memtrim


def test_limit_and_trim_are_safe(monkeypatch):
    monkeypatch.delenv("MALLOC_ARENA_MAX", raising=False)
    applied = memtrim.limit_malloc_arenas()
    started = memtrim.start_malloc_trim(interval_s=3600)
    if sys.platform.startswith("linux"):
        assert applied and started
    else:
        assert not applied and not started


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "4")
    assert memtrim.limit_malloc_arenas() is False
