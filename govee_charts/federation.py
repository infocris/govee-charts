"""Push local BLE readings to peer Govee Charts instances."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from govee_charts.decode import Reading

logger = logging.getLogger(__name__)


class PeerPublisher:
    """Fire-and-forget fan-out of locally scanned readings to peer nodes."""

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
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None

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

    def publish(self, reading: Reading, ts: float) -> None:
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
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Federation queue full — dropping reading for %s", reading.address)

    async def _worker(self) -> None:
        assert self._client is not None
        while True:
            item = await self._queue.get()
            batch = [item]
            while len(batch) < 25:
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
