"""Pull readings from peers running in BLE collector mode.

A collector node only scans BLE and never pushes to the federation. Full nodes
therefore poll each collector's ``/api/devices`` + ``/api/history`` and insert
the collector's own samples (``source = node_id`` or ``node_id/…``) locally.
Pulled samples keep the collector's provenance and are never re-published.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from govee_charts.address import is_federated_device_address
from govee_charts.db import Database
from govee_charts.federation import PeerPublisher
from govee_charts.federation_store import MODE_COLLECTOR, normalize_mode

logger = logging.getLogger(__name__)

# Re-read a few minutes before the cursor in case the collector inserted late.
OVERLAP_SECONDS = 300.0
MAX_POINTS = 50_000


@dataclass(frozen=True)
class CollectorPullConfig:
    interval_s: float = 60.0
    lookback_hours: float = 72.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> CollectorPullConfig:
        raw = raw or {}
        return cls(
            interval_s=max(
                10.0, float(raw.get("collector_pull_seconds") or 60.0)
            ),
            lookback_hours=max(
                1.0, float(raw.get("collector_pull_lookback_hours") or 72.0)
            ),
        )


def collector_samples(
    points: list[dict[str, Any]],
    *,
    peer_node_id: str,
    since: float,
    fallback_battery: int = 0,
) -> list[tuple[float, float, float, int, int | None, str]]:
    """Keep the collector's own raw samples newer than ``since``."""
    prefix = f"{peer_node_id}/"
    rows: list[tuple[float, float, float, int, int | None, str]] = []
    for p in points:
        if p.get("rollup"):
            continue
        src = str(p.get("source") or "").strip()
        if src != peer_node_id and not src.startswith(prefix):
            # Readings the collector itself ingested from others: no re-forward.
            continue
        try:
            ts = float(p["ts"])
            temp = float(p["temperature_c"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts <= since:
            continue
        try:
            hum = float(p.get("humidity")) if p.get("humidity") is not None else 0.0
        except (TypeError, ValueError):
            hum = 0.0
        try:
            batt = int(p["battery"]) if p.get("battery") is not None else fallback_battery
        except (TypeError, ValueError):
            batt = fallback_battery
        try:
            rssi = int(p["rssi"]) if p.get("rssi") is not None else None
        except (TypeError, ValueError):
            rssi = None
        rows.append((ts, temp, hum, batt, rssi, src))
    return rows


@dataclass
class CollectorPullService:
    db: Database
    publisher: PeerPublisher
    cfg: CollectorPullConfig
    node_id: str = "local"
    # (peer node_id, address) → newest pulled ts
    _cursors: dict[tuple[str, str], float] = field(default_factory=dict)

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info(
            "Collector pull started (every %.0fs, lookback %.0fh)",
            self.cfg.interval_s,
            self.cfg.lookback_hours,
        )
        while not stop_event.is_set():
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Collector pull cycle failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.cfg.interval_s)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self) -> int:
        """One pull cycle over all peers. Returns inserted sample count."""
        pub = self.publisher
        if not pub.enabled:
            # Collector mode (or no peers): no outbound federation at all.
            return 0
        collectors: set[str] = set()
        inserted = 0
        for peer in list(pub.peers):
            fed = await pub.get_peer_json(peer, "/api/federation", timeout=10.0)
            if not isinstance(fed, dict):
                # Unreachable: keep the previous classification.
                if peer in pub.collector_peers:
                    collectors.add(peer)
                continue
            if normalize_mode(fed.get("mode")) != MODE_COLLECTOR:
                continue
            collectors.add(peer)
            peer_node_id = str(fed.get("node_id") or "").strip()
            if not peer_node_id or peer_node_id == self.node_id:
                continue
            inserted += await self._pull_peer(peer, peer_node_id)
        pub.set_collector_peers(collectors)
        return inserted

    async def _pull_peer(self, peer: str, peer_node_id: str) -> int:
        raw = await self.publisher.get_peer_json(peer, "/api/devices", timeout=15.0)
        if isinstance(raw, dict):
            raw = raw.get("devices")
        if not isinstance(raw, list):
            return 0
        total = 0
        for device in raw:
            if not isinstance(device, dict):
                continue
            address = str(device.get("address") or "").strip().upper()
            if not is_federated_device_address(address):
                continue
            try:
                total += await self._pull_device(peer, peer_node_id, address, device)
            except Exception:
                logger.exception(
                    "Collector pull %s %s failed", peer_node_id, address
                )
        if total:
            logger.info(
                "Pulled %d sample(s) from collector %s", total, peer_node_id
            )
        return total

    async def _pull_device(
        self,
        peer: str,
        peer_node_id: str,
        address: str,
        device: dict[str, Any],
    ) -> int:
        now = time.time()
        key = (peer_node_id, address)
        cursor = self._cursors.get(key)
        if cursor is None:
            cursor = await self.db.last_reading_ts_from_node(address, peer_node_id)
            floor = now - self.cfg.lookback_hours * 3600.0
            cursor = max(cursor or floor, floor)
            self._cursors[key] = cursor
        try:
            last_seen = float(device.get("last_seen") or 0.0)
        except (TypeError, ValueError):
            last_seen = 0.0
        if last_seen and last_seen <= cursor:
            return 0

        since = cursor - OVERLAP_SECONDS
        data = await self.publisher.get_peer_json(
            peer,
            "/api/history",
            params={
                "address": address,
                "since": str(since),
                "until": str(now),
                "max_points": str(MAX_POINTS),
            },
            timeout=30.0,
        )
        points = data.get("points") if isinstance(data, dict) else None
        if not isinstance(points, list):
            return 0
        try:
            fallback_batt = int(device.get("battery") or 0)
        except (TypeError, ValueError):
            fallback_batt = 0
        rows = collector_samples(
            points,
            peer_node_id=peer_node_id,
            since=since,
            fallback_battery=fallback_batt,
        )
        if not rows:
            return 0

        existing = await self.db.get_device(address)
        name = str(
            (existing or {}).get("name") or device.get("name") or address
        )
        model = str(
            (existing or {}).get("model") or device.get("model") or "unknown"
        ).lower()
        result = await self.db.insert_history_readings(
            address=address,
            display_name=name,
            model=model,
            samples=rows,
            touch_now=False,
        )
        self._cursors[key] = max(cursor, max(r[0] for r in rows))
        return int(result.get("inserted") or 0)
