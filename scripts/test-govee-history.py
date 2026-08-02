#!/usr/bin/env python3
"""Download a short window of onboard history from a Govee H5075 via GATT.

Uses govee_charts.history_gatt helpers (same path as the backfill worker).

Usage:
  venv/bin/python scripts/test-govee-history.py --name SDB --minutes 30
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from govee_charts.history_gatt import download_history  # noqa: E402


def resolve_address(address: str | None, name: str | None) -> tuple[str, str]:
    import sqlite3

    if address:
        return address.strip().upper(), address.strip().upper()
    if not name:
        raise SystemExit("Provide a BLE address or --name")
    db = ROOT / "data" / "readings.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT address, name FROM devices
        WHERE lower(name) = lower(?) OR lower(name) LIKE lower(?)
        ORDER BY CASE WHEN lower(name)=lower(?) THEN 0 ELSE 1 END, last_seen DESC
        LIMIT 1
        """,
        (name.strip(), f"%{name.strip()}%", name.strip()),
    ).fetchone()
    if row is None:
        raise SystemExit(f"No device matching {name!r}")
    return str(row["address"]).upper(), str(row["name"])


async def download(address: str, label: str, start_min: int, end_min: int, timeout: float) -> int:
    print(f"Device {label} ({address})")
    print(f"Request history minutes-ago {start_min} → {end_min}")
    result = await download_history(
        address,
        start_min=start_min,
        end_min=end_min,
        timeout=timeout,
    )
    if result.error and not result.samples:
        print(f"Failed: {result.error}")
        return 2 if "not found" in result.error else 1

    print(
        f"Notifications: {result.notifications} · duration {result.duration_s:.1f}s"
        + (f" · battery {result.battery}%" if result.battery is not None else "")
        + (f" · RSSI {result.rssi} dBm" if result.rssi is not None else "")
    )
    if result.error:
        print(f"Note: {result.error}")
    print(f"Decoded samples: {len(result.samples)}")
    if not result.samples:
        return 1

    print(f"{'Local time':<20} {'ago':>6}  {'Temp':>7}  {'Hum':>7}")
    for sample in result.samples[:40]:
        ts = datetime.fromtimestamp(sample.ts)
        print(
            f"{ts.strftime('%Y-%m-%d %H:%M'):<20} {sample.minutes_ago:5d}m  "
            f"{sample.temperature_c:6.1f}°C  {sample.humidity:5.1f}%"
        )
    if len(result.samples) > 40:
        print(f"… ({len(result.samples) - 40} more)")

    temps = [s.temperature_c for s in result.samples]
    print(
        f"\nRange: {min(temps):.1f}–{max(temps):.1f} °C over "
        f"{result.samples[0].minutes_ago - result.samples[-1].minutes_ago + 1} "
        f"requested minutes covered."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", nargs="?", help="BLE MAC")
    parser.add_argument("--name", help="Device name from readings.db")
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="How far back to start (minutes ago, default 30)",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=1,
        help="End offset minutes ago (default 1)",
    )
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()
    address, label = resolve_address(args.address, args.name)
    try:
        return asyncio.run(
            download(address, label, args.minutes, args.end, args.timeout)
        )
    except Exception as exc:
        print(f"History download failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
