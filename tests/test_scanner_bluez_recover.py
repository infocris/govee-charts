"""BlueZ recovery only fires past the dead-cycle threshold, and is rate-limited."""

from __future__ import annotations

import asyncio
import sys

from govee_charts import scanner as scanner_mod
from govee_charts.scanner import GoveeScanner


def _scanner(after: int, cmd: list[str]) -> GoveeScanner:
    return GoveeScanner(None, bluez_recover_after=after, bluez_recover_command=cmd)


def test_threshold_and_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner_mod.asyncio, "sleep", _no_sleep)
    marker = tmp_path / "ran"
    s = _scanner(2, [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x')"])

    async def go() -> list[bool]:
        return [
            await s._maybe_recover_bluez("hci0", 1),
            await s._maybe_recover_bluez("hci0", 2),
            # Second call inside the min interval is skipped.
            await s._maybe_recover_bluez("hci0", 5),
        ]

    assert asyncio.run(go()) == [False, True, False]
    assert marker.read_text() == "x"


def test_disabled_and_failing_command(monkeypatch):
    monkeypatch.setattr(scanner_mod.asyncio, "sleep", _no_sleep)
    assert asyncio.run(_scanner(0, ["false"])._maybe_recover_bluez("hci0", 99)) is False
    # A failing command still counts as an attempt (counter resets, no tight loop).
    assert asyncio.run(_scanner(1, ["false"])._maybe_recover_bluez("hci0", 1)) is True
    assert (
        asyncio.run(_scanner(1, ["/nonexistent/cmd"])._maybe_recover_bluez("hci0", 1))
        is True
    )


async def _no_sleep(_delay: float) -> None:
    return None


def test_scanner_kwargs_do_not_share_adapter():
    # bleak 3.x mutates its default ``bluez={}``; each scanner needs its own dict.
    a = scanner_mod._scanner_kwargs("hci0", "active")
    b = scanner_mod._scanner_kwargs("hci1", "active")
    assert a["bluez"] == {"adapter": "hci0"}
    assert b["bluez"] == {"adapter": "hci1"}
    assert a["bluez"] is not b["bluez"]
