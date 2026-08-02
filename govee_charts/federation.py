"""Push local BLE readings to peer Govee Charts instances."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from govee_charts.decode import Reading

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
QUEUE_MAXSIZE = 5000


def gatt_source(node_id: str) -> str:
    """Provenance string for GATT-recovered history."""
    return f"{node_id.strip()}/gatt"


def csv_source(node_id: str) -> str:
    """Provenance string for Govee Home CSV imports."""
    return f"{node_id.strip()}/csv"


class PeerPublisher:
    """Fire-and-forget fan-out of locally produced readings to peer nodes."""

    def __init__(
        self,
        peers: list[str],
        *,
        node_id: str,
        token: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.peers = [p.rstrip("/") for p in peers if p.strip()]
        self.node_id = node_id
        self.token = token or None
        self.timeout = timeout
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None
        self._peer_cache: dict[str, dict[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.peers)

    async def start(self) -> None:
        if not self.enabled:
            return
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
        logger.info(
            "Federation publisher → %s (node_id=%s)",
            ", ".join(self.peers),
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
            except Exception as exc:
                logger.debug("Peer signal fetch %s failed: %s", peer, exc)
                ok = False

            entry = {
                "url": peer,
                "node_id": node_id,
                "devices": devices,
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

    async def _worker(self) -> None:
        assert self._client is not None
        while True:
            item = await self._queue.get()
            batch = [item]
            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            body = {"node_id": self.node_id, "readings": batch}
            await asyncio.gather(
                *(self._post(peer, body) for peer in self.peers),
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
