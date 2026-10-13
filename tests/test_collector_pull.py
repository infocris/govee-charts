from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from govee_charts.collector_pull import (
    CollectorPullConfig,
    CollectorPullService,
    collector_samples,
)
from govee_charts.db import Database
from govee_charts.federation import PeerPublisher

MAC = "AA:BB:CC:DD:2E:08"
PEER = "https://collector.example:8082"


class FakePublisher(PeerPublisher):
    """PeerPublisher with canned peer responses instead of HTTP."""

    def __init__(self, responses: dict[str, Any], **kwargs: Any) -> None:
        super().__init__([PEER], node_id="hub", **kwargs)
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get_peer_json(self, peer, path, *, params=None, timeout=None):
        if not self.enabled:
            return None
        self.calls.append((path, params))
        return self.responses.get(path)


def test_collector_samples_keeps_own_raw_only():
    points = [
        {"ts": 100.0, "temperature_c": 20.0, "humidity": 50.0, "source": "pi"},
        {"ts": 160.0, "temperature_c": 20.1, "humidity": 50.0, "source": "pi/gatt"},
        {"ts": 220.0, "temperature_c": 20.2, "humidity": 50.0, "source": "hub"},
        {"ts": 280.0, "temperature_c": 20.3, "source": "pi", "rollup": True},
        {"ts": 40.0, "temperature_c": 19.0, "source": "pi"},
        {"ts": 340.0, "temperature_c": "bad", "source": "pi"},
    ]
    rows = collector_samples(points, peer_node_id="pi", since=50.0, fallback_battery=77)
    assert [(r[0], r[5]) for r in rows] == [(100.0, "pi"), (160.0, "pi/gatt")]
    assert rows[1][2] == 50.0
    assert rows[0][3] == 77


class CollectorPullTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "readings.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        now = time.time()
        self.t0 = now - 600
        self.responses = {
            "/api/federation": {"node_id": "pi", "mode": "collector"},
            "/api/devices": [
                {
                    "address": MAC,
                    "name": "GVH5075_2E08",
                    "model": "h5075",
                    "last_seen": now,
                    "battery": 90,
                },
                {"address": "A889CA39-71C5-0000-0000-000000000000", "last_seen": now},
            ],
            "/api/history": {
                "points": [
                    {"ts": self.t0, "temperature_c": 21.0, "humidity": 40.0,
                     "battery": 90, "rssi": -60, "source": "pi"},
                    {"ts": self.t0 + 60, "temperature_c": 21.1, "humidity": 41.0,
                     "battery": 90, "rssi": -61, "source": "pi"},
                    {"ts": self.t0 + 120, "temperature_c": 25.0, "humidity": 41.0,
                     "source": "other-node"},
                ]
            },
        }

    def _service(self, pub: FakePublisher) -> CollectorPullService:
        return CollectorPullService(
            self.db, pub, CollectorPullConfig(), node_id="hub"
        )

    async def test_pulls_collector_readings(self) -> None:
        pub = FakePublisher(self.responses)
        svc = self._service(pub)
        self.assertEqual(await svc.poll_once(), 2)
        self.assertEqual(pub.collector_peers, {PEER})
        points = await self.db.history(MAC, since=self.t0 - 1, until=time.time())
        self.assertEqual([p["source"] for p in points], ["pi", "pi"])
        device = await self.db.get_device(MAC)
        assert device is not None
        self.assertAlmostEqual(device["last_seen"], self.t0 + 60, places=3)
        self.assertEqual(
            await self.db.last_reading_ts_from_node(MAC, "pi"), self.t0 + 60
        )
        # Same window again: nothing new.
        self.assertEqual(await svc.poll_once(), 0)
        # UUID address is never queried.
        hist_addrs = [p["address"] for path, p in pub.calls if path == "/api/history"]
        self.assertTrue(all(a == MAC for a in hist_addrs))

    async def test_full_peer_is_not_pulled(self) -> None:
        self.responses["/api/federation"] = {"node_id": "pi", "mode": "full"}
        pub = FakePublisher(self.responses)
        self.assertEqual(await self._service(pub).poll_once(), 0)
        self.assertEqual(pub.collector_peers, set())
        self.assertEqual([c[0] for c in pub.calls], ["/api/federation"])

    async def test_collector_node_does_not_pull(self) -> None:
        pub = FakePublisher(self.responses, mode="collector")
        self.assertEqual(await self._service(pub).poll_once(), 0)
        self.assertEqual(pub.calls, [])


def test_switch_to_collector_drains_queue():
    from govee_charts.decode import Reading

    pub = PeerPublisher([PEER], node_id="hub")
    pub.publish(
        Reading(
            temperature_c=20.0, humidity=50.0, battery=90,
            address=MAC, name="x", model="h5075", rssi=-60,
        ),
        time.time(),
    )
    assert pub._queue.qsize() == 1
    assert pub.set_mode("collector")
    assert pub._queue.qsize() == 0
    assert not pub.enabled
