#!/usr/bin/env python3
"""One-shot GATT probe for a Govee thermo-hygrometer (H5075 / H5179).

Connects, lists services/characteristics, and checks for the known
history request/response UUIDs used by community reverse-engineering.

Usage:
  venv/bin/python scripts/test-govee-gatt.py A4:C1:38:EF:88:94
  venv/bin/python scripts/test-govee-gatt.py --name "Cuisine hôte"
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from bleak import BleakClient, BleakScanner

ROOT = Path(__file__).resolve().parent.parent

# Community-documented Govee "Intel Rocks" service characteristics.
HISTORY_KEEPALIVE_UUID = "494e5445-4c4c-495f-524f-434b535f2011"
HISTORY_REQUEST_UUID = "494e5445-4c4c-495f-524f-434b535f2012"
HISTORY_RESPONSE_UUID = "494e5445-4c4c-495f-524f-434b535f2013"

INTERESTING = {
    HISTORY_KEEPALIVE_UUID.lower(): "history keepalive / control (…2011)",
    HISTORY_REQUEST_UUID.lower(): "history request (…2012)",
    HISTORY_RESPONSE_UUID.lower(): "history response / notifications (…2013)",
}


def resolve_address(address: str | None, name: str | None) -> str:
    if address:
        return address.strip().upper()
    if not name:
        raise SystemExit("Provide a BLE address or --name")
    db_path = ROOT / "data" / "readings.db"
    if not db_path.exists():
        raise SystemExit(f"No database at {db_path}; pass a BLE address instead")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT address, name FROM devices
        WHERE lower(name) = lower(?)
        ORDER BY last_seen DESC LIMIT 1
        """,
        (name.strip(),),
    ).fetchone()
    if row is None:
        row = con.execute(
            """
            SELECT address, name FROM devices
            WHERE lower(name) LIKE lower(?)
            ORDER BY last_seen DESC LIMIT 1
            """,
            (f"%{name.strip()}%",),
        ).fetchone()
    if row is None:
        raise SystemExit(f"No device matching name {name!r}")
    print(f"Resolved {row['name']!r} → {row['address']}")
    return str(row["address"]).upper()


async def probe(address: str, timeout: float) -> int:
    print(f"Scanning for {address} (timeout {timeout:.0f}s)…")
    device = await BleakScanner.find_device_by_address(address, timeout=timeout)
    if device is None:
        print("Device not found in scan (out of range, or busy?).")
        return 2

    print(f"Found {device.name!r} — connecting…")
    async with BleakClient(device, timeout=timeout) as client:
        print(f"Connected: {client.is_connected}")
        # bleak ≥0.22 exposes services after connect; older needs get_services().
        services = getattr(client, "services", None)
        if services is None and hasattr(client, "get_services"):
            services = await client.get_services()

        found_interesting = []
        print("\nGATT services:")
        for service in services:
            print(f"  [{service.uuid}] {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                note = INTERESTING.get(char.uuid.lower(), "")
                mark = f"  ← {note}" if note else ""
                print(f"    char {char.uuid}  props=[{props}]{mark}")
                if note:
                    found_interesting.append(note)

        print()
        if found_interesting:
            print("History-related characteristics present:")
            for note in found_interesting:
                print(f"  • {note}")
            print(
                "Active history download looks feasible on this device "
                "(request on …2012, notifications on …2013)."
            )
            return 0

        print(
            "Connected OK, but the usual history UUIDs (…2011/2012/2013) "
            "were not found. Firmware may differ, or history needs pairing."
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", nargs="?", help="BLE MAC (e.g. A4:C1:38:EF:88:94)")
    parser.add_argument("--name", help="Friendly name from data/readings.db")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    address = resolve_address(args.address, args.name)
    try:
        return asyncio.run(probe(address, args.timeout))
    except Exception as exc:
        print(f"GATT probe failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
