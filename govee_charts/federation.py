"""Push local BLE readings to peer Govee Charts instances."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from govee_charts.decode import Reading
from govee_charts.federation_store import (
    MODE_COLLECTOR,
    MODE_FULL,
    load_federation_settings,
    normalize_mode,
    normalize_peers,
    peers_file_mtime,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
QUEUE_MAXSIZE = 5000
PEERS_RELOAD_INTERVAL_S = 5.0


def gatt_source(node_id: str) -> str:
    """Provenance string for GATT-recovered history."""
    return f"{node_id.strip()}/gatt"


def csv_source(node_id: str) -> str:
    """Provenance string for Govee Home CSV imports."""
    return f"{node_id.strip()}/csv"


def fed_pull_source(node_id: str) -> str:
    """Provenance when this node copies history from a peer (not re-forwarded)."""
    return f"{node_id.strip()}/pull"


def classify_reading_source(source: str | None, node_id: str) -> str:
    """Bucket a readings.source value: direct | backfill | federation | other."""
    raw = (source or "").strip()
    local = (node_id or "").strip()
    if not raw:
        return "other"
    lower = raw.lower()
    if lower == "gatt-history" or lower.endswith("/gatt"):
        return "backfill"
    if lower.endswith("/pull"):
        return "federation"
    if lower.endswith("/csv") or lower.endswith("/ha"):
        return "other"
    if "/" in raw:
        return "other"
    if local and raw == local:
        return "direct"
    return "federation"


def source_bucket_sql(source_expr: str = "source") -> str:
    """SQL CASE expression classifying source; bind local node_id as first param."""
    # Placeholders: ? = local node_id (compared for direct).
    return f"""
    CASE
      WHEN {source_expr} = ? THEN 'direct'
      WHEN lower(COALESCE({source_expr}, '')) = 'gatt-history'
        OR lower(COALESCE({source_expr}, '')) LIKE '%/gatt' THEN 'backfill'
      WHEN lower(COALESCE({source_expr}, '')) LIKE '%/pull' THEN 'federation'
      WHEN lower(COALESCE({source_expr}, '')) LIKE '%/csv'
        OR lower(COALESCE({source_expr}, '')) LIKE '%/ha'
        OR TRIM(COALESCE({source_expr}, '')) = '' THEN 'other'
      WHEN instr(COALESCE({source_expr}, ''), '/') = 0 THEN 'federation'
      ELSE 'other'
    END
    """


class PeerPublisher:
    """Fire-and-forget fan-out of locally produced readings to peer nodes."""

    def __init__(
        self,
        peers: list[str],
        *,
        node_id: str,
        token: str | None = None,
        timeout: float = 5.0,
        peers_path: Path | str | None = None,
        mode: str = MODE_FULL,
    ) -> None:
        self.peers = normalize_peers(peers)
        self.mode = normalize_mode(mode)
        self.node_id = node_id
        self.token = token or None
        self.timeout = timeout
        self.peers_path = Path(peers_path) if peers_path else None
        self._peers_mtime: float | None = (
            peers_file_mtime(self.peers_path) if self.peers_path else None
        )
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None
        self._peer_cache: dict[str, dict[str, Any]] = {}
        # Peers seen in collector mode: never pushed to (they pull nothing and
        # are pulled from instead — see collector_pull.py).
        self.collector_peers: set[str] = set()

    @property
    def is_collector(self) -> bool:
        return self.mode == MODE_COLLECTOR

    @property
    def enabled(self) -> bool:
        """True when outbound federation (push/pull) is active."""
        return bool(self.peers) and not self.is_collector

    def set_mode(self, mode: str) -> bool:
        """Update federation mode. Returns True when it changed."""
        normalized = normalize_mode(mode)
        if normalized == self.mode:
            return False
        previous = self.mode
        self.mode = normalized
        if self.is_collector:
            self._drain_queue()
        logger.info(
            "Federation mode %s → %s (node_id=%s)",
            previous,
            normalized,
            self.node_id,
        )
        return True

    def _drain_queue(self) -> int:
        """Drop readings queued before outbound federation was disabled."""
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return dropped
            dropped += 1

    def set_collector_peers(self, peers: set[str]) -> None:
        """Record which peers run in collector mode (excluded from pushes)."""
        normalized = {str(p).rstrip("/") for p in peers}
        if normalized != self.collector_peers:
            logger.info(
                "Federation collector peers: %s",
                ", ".join(sorted(normalized)) or "(none)",
            )
        self.collector_peers = normalized

    async def get_peer_json(
        self,
        peer: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any | None:
        """GET ``{peer}{path}`` and return decoded JSON, or None on any error."""
        if not self.enabled or self._client is None:
            return None
        try:
            kwargs: dict[str, Any] = {"params": params}
            if timeout is not None:
                kwargs["timeout"] = timeout
            res = await self._client.get(f"{peer}{path}", **kwargs)
            if res.status_code >= 400:
                logger.debug("GET %s%s → HTTP %s", peer, path, res.status_code)
                return None
            return res.json()
        except Exception as exc:
            logger.debug("GET %s%s failed: %s", peer, path, exc)
            return None

    def set_peers(self, peers: list[str]) -> bool:
        """Replace peer list in memory. Returns True when the list changed."""
        normalized = normalize_peers(peers)
        if normalized == self.peers:
            return False
        previous = list(self.peers)
        self.peers = normalized
        # Drop cache entries for removed peers.
        keep = set(normalized)
        self.collector_peers &= keep
        for key in list(self._peer_cache):
            if key not in keep:
                self._peer_cache.pop(key, None)
        logger.info(
            "Federation peers updated (%d → %d): %s",
            len(previous),
            len(normalized),
            ", ".join(normalized) or "(none)",
        )
        return True

    def reload_peers_from_disk(self) -> bool:
        """Reload peers/mode from ``peers_path`` when the file mtime changes."""
        if self.peers_path is None:
            return False
        mtime = peers_file_mtime(self.peers_path)
        if mtime is None or mtime == self._peers_mtime:
            return False
        loaded = load_federation_settings(self.peers_path)
        if loaded is None:
            return False
        self._peers_mtime = mtime
        changed_peers = self.set_peers(list(loaded.get("peers") or []))
        changed_mode = self.set_mode(str(loaded.get("mode") or MODE_FULL))
        return changed_peers or changed_mode

    async def start(self) -> None:
        # Always start the worker so peers/mode added later via the UI are picked up.
        headers = {}
        if self.token:
            headers["X-Govee-Token"] = self.token
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
            # LAN peers often use self-signed certs
            verify=False,
        )
        self._task = asyncio.create_task(self._worker(), name="federation-publisher")
        if self.is_collector:
            logger.info(
                "Federation collector mode (BLE only, no outbound; node_id=%s)",
                self.node_id,
            )
        elif self.peers:
            logger.info(
                "Federation publisher → %s (node_id=%s)",
                ", ".join(self.peers),
                self.node_id,
            )
        else:
            logger.info(
                "Federation publisher idle (no peers, node_id=%s)",
                self.node_id,
            )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def publish(
        self,
        reading: Reading,
        ts: float,
        *,
        source: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = {
            "address": reading.address,
            "name": reading.name,
            "model": reading.model,
            "ts": ts,
            "temperature_c": reading.temperature_c,
            "humidity": reading.humidity,
            "battery": reading.battery,
            "rssi": reading.rssi,
        }
        if source:
            payload["source"] = source
        self._enqueue(payload)

    def publish_many(self, items: list[dict[str, Any]]) -> int:
        """Enqueue raw ingest reading dicts. Returns number accepted."""
        if not self.enabled or not items:
            return 0
        accepted = 0
        for item in items:
            if self._enqueue(item):
                accepted += 1
        return accepted

    def _enqueue(self, payload: dict[str, Any]) -> bool:
        try:
            self._queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "Federation queue full — dropping reading for %s",
                payload.get("address"),
            )
            return False

    async def peer_device_signals(
        self,
        *,
        cache_seconds: float = 45.0,
    ) -> list[dict[str, Any]]:
        """
        Fetch each peer's node_id + devices (for RSSI election).

        Returns list of {node_id, url, devices, ok}.
        """
        if not self.enabled or self._client is None:
            return []

        now = time.time()
        results: list[dict[str, Any]] = []

        async def _one(peer: str) -> dict[str, Any]:
            cached = self._peer_cache.get(peer)
            if (
                cached
                and now - float(cached.get("fetched_at") or 0) < cache_seconds
            ):
                return dict(cached)

            node_id = peer
            devices: list[dict[str, Any]] = []
            backfill: dict[str, dict[str, bool]] = {}
            ok = False
            try:
                assert self._client is not None
                fed = await self._client.get(f"{peer}/api/federation")
                if fed.status_code < 400:
                    data = fed.json()
                    node_id = str(data.get("node_id") or peer).strip() or peer
                dev_res = await self._client.get(f"{peer}/api/devices")
                if dev_res.status_code < 400:
                    raw = dev_res.json()
                    if isinstance(raw, list):
                        devices = raw
                    elif isinstance(raw, dict):
                        devices = list(raw.get("devices") or [])
                    ok = True
                # Backfill GATT flags (enabled / gatt_enabled) so RSSI election
                # does not yield to a peer that will not run GATT for the sensor.
                try:
                    bf_res = await self._client.get(
                        f"{peer}/api/backfill",
                        params={"recent_limit": 1, "job_limit": 1},
                    )
                    if bf_res.status_code < 400:
                        bf_raw = bf_res.json()
                        for row in bf_raw.get("devices") or []:
                            addr = str(row.get("address") or "").upper()
                            if not addr:
                                continue
                            backfill[addr] = {
                                "enabled": bool(row.get("enabled")),
                                "gatt_enabled": bool(
                                    row.get("gatt_enabled", True)
                                ),
                            }
                except Exception as exc:
                    logger.debug(
                        "Peer backfill flags %s failed: %s", peer, exc
                    )
            except Exception as exc:
                logger.debug("Peer signal fetch %s failed: %s", peer, exc)
                ok = False

            entry = {
                "url": peer,
                "node_id": node_id,
                "devices": devices,
                "backfill": backfill,
                "ok": ok,
                "fetched_at": now,
            }
            if ok:
                self._peer_cache[peer] = entry
            return entry

        gathered = await asyncio.gather(
            *(_one(peer) for peer in self.peers),
            return_exceptions=True,
        )
        for item in gathered:
            if isinstance(item, Exception):
                logger.debug("Peer signal gather error: %s", item)
                continue
            results.append(item)
        return results

    async def fetch_peer_history(
        self,
        address: str,
        *,
        since: float,
        until: float,
        max_points: int = 10000,
    ) -> list[dict[str, Any]]:
        """
        GET /api/history from each peer for ``address`` in [since, until].

        Returns list of {url, node_id, points} for peers that answered OK.
        """
        if not self.enabled or self._client is None:
            return []
        address = str(address).upper()
        since_f = float(since)
        until_f = float(until)
        if until_f < since_f:
            since_f, until_f = until_f, since_f
        params = {
            "address": address,
            "since": str(since_f),
            "until": str(until_f),
            "max_points": str(max(100, int(max_points))),
        }

        async def _one(peer: str) -> dict[str, Any] | None:
            try:
                assert self._client is not None
                # Resolve node_id (cached devices probe when possible).
                node_id = peer
                cached = self._peer_cache.get(peer)
                if cached and cached.get("node_id"):
                    node_id = str(cached["node_id"])
                else:
                    try:
                        fed = await self._client.get(f"{peer}/api/federation")
                        if fed.status_code < 400:
                            node_id = (
                                str(fed.json().get("node_id") or peer).strip()
                                or peer
                            )
                    except Exception:
                        pass
                res = await self._client.get(
                    f"{peer}/api/history",
                    params=params,
                    timeout=30.0,
                )
                if res.status_code >= 400:
                    return None
                data = res.json()
                points = data.get("points") if isinstance(data, dict) else None
                if not isinstance(points, list) or not points:
                    return None
                return {
                    "url": peer,
                    "node_id": node_id,
                    "points": points,
                }
            except Exception as exc:
                logger.debug(
                    "Peer history fetch %s %s failed: %s", peer, address, exc
                )
                return None

        gathered = await asyncio.gather(
            *(_one(peer) for peer in self.peers),
            return_exceptions=True,
        )
        out: list[dict[str, Any]] = []
        for item in gathered:
            if isinstance(item, Exception):
                logger.debug("Peer history gather error: %s", item)
                continue
            if item:
                out.append(item)
        return out

    async def _worker(self) -> None:
        assert self._client is not None
        while True:
            self.reload_peers_from_disk()
            try:
                item = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=PEERS_RELOAD_INTERVAL_S,
                )
            except asyncio.TimeoutError:
                continue
            batch = [item]
            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            # Mode may have flipped to collector while waiting on the queue.
            targets = [
                p for p in list(self.peers) if p not in self.collector_peers
            ]
            if not self.enabled or not targets:
                continue
            body = {"node_id": self.node_id, "readings": batch}
            await asyncio.gather(
                *(self._post(peer, body) for peer in targets),
                return_exceptions=True,
            )

    async def _post(self, peer: str, body: dict[str, Any]) -> None:
        assert self._client is not None
        url = f"{peer}/api/ingest"
        try:
            res = await self._client.post(url, json=body)
            if res.status_code >= 400:
                logger.warning(
                    "Federation POST %s → HTTP %s: %s",
                    url,
                    res.status_code,
                    res.text[:200],
                )
        except Exception as exc:
            logger.warning("Federation POST %s failed: %s", url, exc)
