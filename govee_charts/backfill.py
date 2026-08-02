"""Single-worker GATT history backfill queue (recent gaps first)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from govee_charts.db import Database
from govee_charts.federation import PeerPublisher, gatt_source
from govee_charts.history_gatt import MAX_HISTORY_MINUTES, download_history
from govee_charts.scanner import GoveeScanner

logger = logging.getLogger(__name__)

PHASE_PRIORITY = {
    "hour": 0,
    "day": 1,
    "week": 2,
    "deep": 3,
}


@dataclass
class BackfillConfig:
    enabled: bool = True
    lookback_days: float = 20.0
    poll_seconds: float = 30.0
    max_job_minutes: int = 60
    min_rssi: int = -75
    seen_max_age_seconds: float = 600.0
    connect_timeout: float = 25.0
    weak_rssi_backoff_seconds: float = 300.0
    federation_share: bool = True
    # Defer only when a peer is at least this many dB stronger (ties → local).
    rssi_prefer_margin_db: float = 3.0
    peer_signal_cache_seconds: float = 45.0
    # Full pending-queue rebuild interval (incremental enqueue otherwise).
    rebuild_seconds: float = 900.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BackfillConfig:
        raw = raw or {}
        margin_raw = raw.get("rssi_prefer_margin_db")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            lookback_days=float(raw.get("lookback_days") or 20.0),
            poll_seconds=max(5.0, float(raw.get("poll_seconds") or 30.0)),
            max_job_minutes=max(5, int(raw.get("max_job_minutes") or 60)),
            min_rssi=int(raw.get("min_rssi") if raw.get("min_rssi") is not None else -75),
            seen_max_age_seconds=max(
                60.0, float(raw.get("seen_max_age_seconds") or 600.0)
            ),
            connect_timeout=max(5.0, float(raw.get("connect_timeout") or 25.0)),
            weak_rssi_backoff_seconds=max(
                30.0, float(raw.get("weak_rssi_backoff_seconds") or 300.0)
            ),
            federation_share=bool(raw.get("federation_share", True)),
            rssi_prefer_margin_db=float(
                3.0 if margin_raw is None else margin_raw
            ),
            peer_signal_cache_seconds=max(
                5.0, float(raw.get("peer_signal_cache_seconds") or 45.0)
            ),
            rebuild_seconds=max(
                60.0, float(raw.get("rebuild_seconds") or 900.0)
            ),
        )


def _minute_floor(ts: float) -> int:
    return int(ts // 60)


def _missing_ranges(
    existing: set[int],
    start_ts: float,
    end_ts: float,
    *,
    max_job_minutes: int,
) -> list[tuple[float, float, int]]:
    """
    Contiguous missing minute ranges in [start_ts, end_ts), split to ≤ max_job_minutes.
    Returns list of (window_start, window_end, expected_samples).
    """
    start_m = _minute_floor(start_ts)
    end_m = _minute_floor(end_ts)
    if end_m <= start_m:
        return []

    missing: list[int] = []
    for m in range(start_m, end_m):
        if m not in existing:
            missing.append(m)
    if not missing:
        return []

    ranges: list[tuple[float, float, int]] = []
    run_start = missing[0]
    prev = missing[0]
    for m in missing[1:]:
        if m == prev + 1 and (m - run_start + 1) <= max_job_minutes:
            prev = m
            continue
        # close run
        ranges.append((run_start * 60.0, (prev + 1) * 60.0, prev - run_start + 1))
        run_start = m
        prev = m
    ranges.append((run_start * 60.0, (prev + 1) * 60.0, prev - run_start + 1))
    return ranges


def _phase_bands(now: float, lookback_days: float) -> list[tuple[str, float, float]]:
    """
    Exclusive time bands newest → oldest.
    Each tuple: (phase, band_start, band_end) with band_start < band_end ≤ now.
    """
    lookback_min = min(int(lookback_days * 24 * 60), MAX_HISTORY_MINUTES)
    lookback_start = now - lookback_min * 60.0
    # Leave the current incomplete minute alone.
    tip = now - 60.0
    hour_start = tip - 60.0 * 60.0
    day_start = tip - 24.0 * 3600.0
    week_start = tip - 7.0 * 86400.0

    bands: list[tuple[str, float, float]] = []
    bands.append(("hour", max(hour_start, lookback_start), tip))
    if day_start < hour_start:
        bands.append(("day", max(day_start, lookback_start), hour_start))
    if week_start < day_start:
        bands.append(("week", max(week_start, lookback_start), day_start))
    if lookback_start < week_start:
        # Deep: day-sized chunks, oldest unfinished day first among remaining
        # but still after recent phases via priority.
        cursor = week_start
        while cursor > lookback_start:
            chunk_start = max(lookback_start, cursor - 86400.0)
            bands.append(("deep", chunk_start, cursor))
            cursor = chunk_start
    return [(p, s, e) for p, s, e in bands if e - s >= 60.0]


@dataclass
class LiveJobProgress:
    job_id: int | None = None
    address: str | None = None
    name: str | None = None
    phase: str | None = None
    window_start: float | None = None
    window_end: float | None = None
    samples_done: int = 0
    samples_expected: int = 0
    last_sample_ts: float | None = None
    last_sample_temp: float | None = None
    rssi: int | None = None
    battery: int | None = None
    started_at: float | None = None


@dataclass
class BackfillService:
    db: Database
    cfg: BackfillConfig
    labels: dict[str, str] = field(default_factory=dict)
    node_id: str = "local"
    publisher: PeerPublisher | None = None
    scanner: GoveeScanner | None = None

    def __post_init__(self) -> None:
        self._paused = False
        self._worker: str = "idle"
        self._live = LiveJobProgress()
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_ts = 0.0
        self._last_rebuild_ts = 0.0
        self._rr_cursor = 0
        self._weak_backoff: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    @property
    def source_tag(self) -> str:
        return gatt_source(self.node_id)

    def pause(self) -> None:
        self._paused = True
        if self._worker != "busy":
            self._worker = "paused"

    def resume(self) -> None:
        self._paused = False
        if self._worker == "paused":
            self._worker = "idle"

    async def snapshot(self) -> dict[str, Any]:
        counts = await self.db.backfill_job_counts()
        devices = {d["address"].upper(): d for d in await self.db.list_devices()}
        local_rssi = await self.db.local_rssi_map(self.node_id)
        peer_rssi = await self._peer_best_rssi_map()
        margin = max(0.0, float(self.cfg.rssi_prefer_margin_db))

        summaries = await self.db.summarize_backfill_queue()
        queue: list[dict[str, Any]] = []
        for row in summaries:
            addr = str(row["address"]).upper()
            if self._live.job_id and self._live.address == addr and self._worker == "busy":
                # Still show device but note current job is active; keep in list.
                pass
            dev = devices.get(addr) or {}
            local = local_rssi.get(addr)
            peer = peer_rssi.get(addr)
            local_best = False
            if local is not None:
                local_best = peer is None or peer <= local + margin
            entry = {
                "address": addr,
                "name": self._label(addr, str(dev.get("name") or addr)),
                "phase": row.get("phase") or "hour",
                "jobs": int(row.get("jobs") or 0),
                "samples_expected": int(row.get("samples_expected") or 0),
                "priority": int(row.get("priority") or 0),
                "rssi": local,
                "local_best": local_best,
            }
            queue.append(entry)

        queue.sort(
            key=lambda e: (
                # Local-best first, then phase priority, then stronger RSSI.
                0 if e.get("local_best") else 1,
                int(e["priority"]),
                -(e["rssi"] if e.get("rssi") is not None else -999),
                -int(e["samples_expected"]),
                e["name"],
            )
        )

        enabled_set = await self.db.list_backfill_enabled()
        queued_by_addr = {
            str(row["address"]).upper(): row for row in summaries
        }
        device_rows: list[dict[str, Any]] = []
        for device in devices.values():
            addr = str(device.get("address") or "").upper()
            if not addr:
                continue
            model = str(device.get("model") or "").lower()
            if model and model not in ("h5075", "h5072", "h5179"):
                continue
            local = local_rssi.get(addr)
            peer = peer_rssi.get(addr)
            local_best = False
            if local is not None:
                local_best = peer is None or peer <= local + margin
            q = queued_by_addr.get(addr) or {}
            device_rows.append(
                {
                    "address": addr,
                    "name": self._label(addr, str(device.get("name") or addr)),
                    "model": model or None,
                    "enabled": addr in enabled_set,
                    "rssi": local,
                    "local_best": local_best,
                    "queued_jobs": int(q.get("jobs") or 0),
                    "phase": q.get("phase"),
                }
            )
        device_rows.sort(key=lambda e: (e["name"].lower(), e["address"]))

        live = self._live
        current = None
        if live.job_id is not None and self._worker == "busy":
            eta = None
            if live.started_at and live.samples_done > 0 and live.samples_expected > 0:
                rate = live.samples_done / max(0.1, time.time() - live.started_at)
                remaining = max(0, live.samples_expected - live.samples_done)
                eta = remaining / rate if rate > 0 else None
            current = {
                "job_id": live.job_id,
                "address": live.address,
                "name": live.name,
                "phase": live.phase,
                "window_start": live.window_start,
                "window_end": live.window_end,
                "samples_done": live.samples_done,
                "samples_expected": live.samples_expected,
                "last_sample_ts": live.last_sample_ts,
                "last_sample_temp": live.last_sample_temp,
                "rssi": live.rssi,
                "battery": live.battery,
                "eta_seconds": eta,
            }

        worker = "paused" if self._paused else self._worker
        return {
            "enabled": self.cfg.enabled,
            "paused": self._paused,
            "worker": worker,
            "current": current,
            "queue": queue,
            "devices": device_rows,
            "totals": {
                "pending": int(counts.get("pending") or 0)
                + int(counts.get("deferred") or 0),
                "running": int(counts.get("running") or 0),
                "done": int(counts.get("done") or 0),
                "failed": int(counts.get("failed") or 0),
            },
            "config": {
                "lookback_days": self.cfg.lookback_days,
                "poll_seconds": self.cfg.poll_seconds,
                "max_job_minutes": self.cfg.max_job_minutes,
                "min_rssi": self.cfg.min_rssi,
                "federation_share": self.cfg.federation_share,
                "rssi_prefer_margin_db": self.cfg.rssi_prefer_margin_db,
                "rebuild_seconds": self.cfg.rebuild_seconds,
            },
        }

    def _label(self, address: str, fallback: str) -> str:
        return self.labels.get(address.upper()) or fallback

    async def refresh_gaps(
        self,
        *,
        force: bool = False,
        addresses: list[str] | None = None,
    ) -> int:
        """Detect gaps and enqueue jobs. Returns number of newly enqueued jobs."""
        async with self._refresh_lock:
            now = time.time()
            if (
                not force
                and self._last_refresh_ts
                and now - self._last_refresh_ts < self.cfg.poll_seconds
            ):
                return 0

            # Quantize to the minute so band edges stay stable across polls.
            now_q = float(int(now // 60) * 60)
            self._last_refresh_ts = now

            enabled_set = await self.db.list_backfill_enabled()
            scope: set[str] | None = None
            if addresses is not None:
                scope = {str(a).upper() for a in addresses if a}
                scope &= enabled_set

            # Drop queue entries for sensors that are no longer opted in.
            pruned = await self.db.clear_open_backfill_jobs_except(enabled_set)
            if pruned:
                logger.info(
                    "Cleared %d open backfill job(s) for disabled sensor(s)",
                    pruned,
                )

            rebuild = (
                addresses is None
                and (
                    force
                    or not self._last_rebuild_ts
                    or now - self._last_rebuild_ts >= self.cfg.rebuild_seconds
                )
            )
            if rebuild:
                cleared = await self.db.clear_open_backfill_jobs()
                self._last_rebuild_ts = now
                if cleared:
                    logger.info(
                        "Cleared %d open backfill job(s) before rebuild", cleared
                    )

            if not enabled_set or (scope is not None and not scope):
                return 0

            devices = await self.db.list_devices()
            enqueued = 0
            bands = _phase_bands(now_q, self.cfg.lookback_days)
            for device in devices:
                addr = str(device["address"]).upper()
                if addr not in enabled_set:
                    continue
                if scope is not None and addr not in scope:
                    continue
                model = str(device.get("model") or "").lower()
                if model and model not in ("h5075", "h5072", "h5179"):
                    continue
                for phase, band_start, band_end in bands:
                    existing = await self.db.reading_minutes(
                        addr, band_start, band_end, cover_seconds=75.0
                    )
                    for win_start, win_end, expected in _missing_ranges(
                        existing,
                        band_start,
                        band_end,
                        max_job_minutes=self.cfg.max_job_minutes,
                    ):
                        # Skip tiny holes in recent bands (live ads are sparse).
                        if phase in ("hour", "day") and expected < 3:
                            continue
                        job_id = await self.db.enqueue_backfill_job(
                            address=addr,
                            phase=phase,
                            window_start=win_start,
                            window_end=win_end,
                            priority=PHASE_PRIORITY[phase],
                            samples_expected=expected,
                        )
                        if job_id is not None:
                            enqueued += 1
            if enqueued:
                logger.info(
                    "Backfill enqueued %d job(s)%s",
                    enqueued,
                    " (rebuild)" if rebuild else "",
                )
            return enqueued

    async def set_device_enabled(self, address: str, enabled: bool) -> dict[str, Any]:
        """Opt a sensor in/out of GATT backfill; cancel or enqueue accordingly."""
        address = address.upper()
        device = await self.db.get_device(address)
        if device is None:
            raise KeyError(f"Unknown device {address}")
        model = str(device.get("model") or "").lower()
        if model and model not in ("h5075", "h5072", "h5179"):
            raise ValueError(f"Model {model or '?'} does not support GATT history")

        stored = await self.db.set_backfill_enabled(address, enabled)
        cancelled = 0
        enqueued = 0
        if not stored:
            cancelled = await self.db.cancel_open_backfill_jobs(address)
            logger.info(
                "Backfill disabled for %s (cancelled %d open job(s))",
                address,
                cancelled,
            )
        else:
            enqueued = await self.refresh_gaps(force=True, addresses=[address])
            logger.info(
                "Backfill enabled for %s (enqueued %d job(s))",
                address,
                enqueued,
            )
        return {
            "address": address,
            "name": self._label(address, str(device.get("name") or address)),
            "enabled": stored,
            "cancelled": cancelled,
            "enqueued": enqueued,
        }

    async def _local_rssi_map(self) -> dict[str, int | None]:
        """Latest known local RSSI per address (this node's readings / state)."""
        typed: dict[str, int | None] = {
            addr: rssi for addr, rssi in (await self.db.local_rssi_map(self.node_id)).items()
        }
        # Ensure every known device key exists for scoring.
        for device in await self.db.list_devices():
            addr = str(device.get("address") or "").upper()
            if addr and addr not in typed:
                typed[addr] = None
        return typed

    async def _peer_best_rssi_map(self) -> dict[str, int]:
        """Best fresh peer RSSI per address (empty if no federation)."""
        pub = self.publisher
        if pub is None or not pub.enabled:
            return {}
        peers = await pub.peer_device_signals(
            cache_seconds=self.cfg.peer_signal_cache_seconds
        )
        now = time.time()
        max_age = self.cfg.seen_max_age_seconds
        best: dict[str, int] = {}
        for peer in peers:
            if not peer.get("ok"):
                continue
            peer_id = str(peer.get("node_id") or "").strip()
            if not peer_id or peer_id == self.node_id:
                continue
            for device in peer.get("devices") or []:
                addr = str(device.get("address") or "").upper()
                if not addr:
                    continue
                last_seen = float(device.get("last_seen") or 0.0)
                if not last_seen or now - last_seen > max_age:
                    continue
                rssi = device.get("rssi")
                if rssi is None:
                    continue
                try:
                    peer_r = int(rssi)
                except (TypeError, ValueError):
                    continue
                prev = best.get(addr)
                if prev is None or peer_r > prev:
                    best[addr] = peer_r
        return best

    def _address_pick_score(
        self,
        address: str,
        *,
        local_rssi: dict[str, int | None],
        peer_rssi: dict[str, int],
    ) -> tuple[int, int, int]:
        """
        Higher tuple sorts first: local-best, above min_rssi, stronger RSSI.
        """
        local = local_rssi.get(address)
        peer = peer_rssi.get(address)
        margin = max(0.0, float(self.cfg.rssi_prefer_margin_db))
        if local is None:
            local_best = 0
            above_min = 0
            rssi_score = -999
        else:
            peer_stronger = peer is not None and peer > local + margin
            local_best = 0 if peer_stronger else 1
            above_min = 1 if local >= self.cfg.min_rssi else 0
            rssi_score = int(local)
        return (local_best, above_min, rssi_score)

    async def _pick_job(self) -> dict[str, Any] | None:
        enabled_set = await self.db.list_backfill_enabled()
        if not enabled_set:
            return None

        pending = await self.db.list_backfill_jobs(
            statuses=["pending"], limit=300
        )
        pending = [
            j for j in pending if str(j["address"]).upper() in enabled_set
        ]
        if not pending:
            # Promote deferred that are old enough.
            deferred = await self.db.list_backfill_jobs(
                statuses=["deferred"], limit=100
            )
            now = time.time()
            for job in deferred:
                addr = str(job["address"]).upper()
                if addr not in enabled_set:
                    continue
                until = self._weak_backoff.get(addr, 0.0)
                if now >= until:
                    await self.db.update_backfill_job(job["id"], status="pending")
                    pending.append(job)
            if not pending:
                return None

        # Best phase priority first (hour → day → week → deep).
        best_pri = min(int(j["priority"]) for j in pending)
        candidates = [j for j in pending if int(j["priority"]) == best_pri]

        now = time.time()
        addresses = sorted(
            {
                str(j["address"]).upper()
                for j in candidates
                if now >= self._weak_backoff.get(str(j["address"]).upper(), 0.0)
            }
        )
        if not addresses:
            # Everything in backoff — fall back to full candidate set.
            addresses = sorted(
                {str(j["address"]).upper() for j in candidates}
            )
        if not addresses:
            return None

        local_rssi = await self._local_rssi_map()
        peer_rssi = await self._peer_best_rssi_map()

        def score(addr: str) -> tuple[int, int, int]:
            return self._address_pick_score(
                addr, local_rssi=local_rssi, peer_rssi=peer_rssi
            )

        addresses.sort(key=score, reverse=True)
        top_score = score(addresses[0])
        top = [a for a in addresses if score(a) == top_score]
        self._rr_cursor = self._rr_cursor % len(top)
        preferred = top[self._rr_cursor]
        self._rr_cursor = (self._rr_cursor + 1) % len(top)

        device_jobs = [
            j for j in candidates if str(j["address"]).upper() == preferred
        ]
        if not device_jobs:
            device_jobs = candidates
        # Recent phases: newer windows first. Deep lookback: oldest day first.
        if best_pri >= PHASE_PRIORITY["deep"]:
            device_jobs.sort(key=lambda j: (float(j["window_start"]), int(j["id"])))
        else:
            device_jobs.sort(key=lambda j: (-float(j["window_end"]), int(j["id"])))
        return device_jobs[0]

    async def _yield_to_better_peer(
        self,
        address: str,
        local_rssi: int | None,
    ) -> str | None:
        """
        Defer only when a reachable peer is strictly stronger by margin.
        Equal RSSI keeps the job on this node (avoids permanent yield to peers).
        """
        pub = self.publisher
        if pub is None or not pub.enabled:
            return None
        if local_rssi is None:
            return None

        peers = await pub.peer_device_signals(
            cache_seconds=self.cfg.peer_signal_cache_seconds
        )
        now = time.time()
        max_age = self.cfg.seen_max_age_seconds
        margin = max(0.0, float(self.cfg.rssi_prefer_margin_db))
        local_r = int(local_rssi)

        best_peer: tuple[int, str] | None = None
        for peer in peers:
            if not peer.get("ok"):
                continue
            peer_id = str(peer.get("node_id") or "").strip()
            if not peer_id or peer_id == self.node_id:
                continue
            for device in peer.get("devices") or []:
                if str(device.get("address") or "").upper() != address:
                    continue
                last_seen = float(device.get("last_seen") or 0.0)
                if not last_seen or now - last_seen > max_age:
                    continue
                rssi = device.get("rssi")
                if rssi is None:
                    continue
                try:
                    peer_r = int(rssi)
                except (TypeError, ValueError):
                    continue
                if best_peer is None or peer_r > best_peer[0]:
                    best_peer = (peer_r, peer_id)
                break

        if best_peer is None:
            return None
        peer_r, peer_id = best_peer
        if peer_r > local_r + margin:
            return (
                f"peer {peer_id} has better rssi "
                f"({peer_r} > {local_r}+{margin:g})"
            )
        return None

    def _publish_gatt_samples(
        self,
        *,
        address: str,
        name: str,
        model: str,
        samples: list[tuple[float, float, float]],
        battery: int,
        rssi: int | None,
    ) -> None:
        if not self.cfg.federation_share or self.publisher is None:
            return
        if not self.publisher.enabled or not samples:
            return
        source = self.source_tag
        payloads = [
            {
                "address": address,
                "name": name,
                "model": model,
                "ts": float(ts),
                "temperature_c": float(temp),
                "humidity": float(hum),
                "battery": int(battery),
                "rssi": rssi,
                "source": source,
            }
            for ts, temp, hum in samples
        ]
        n = self.publisher.publish_many(payloads)
        if n:
            logger.info(
                "Federation queued %d/%d GATT sample(s) for %s (%s)",
                n,
                len(payloads),
                name,
                source,
            )

    async def _run_job(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        address = str(job["address"]).upper()
        phase = str(job["phase"])
        window_start = float(job["window_start"])
        window_end = float(job["window_end"])
        expected = int(job.get("samples_expected") or 0)

        device = await self.db.get_device(address)
        name = self._label(address, str((device or {}).get("name") or address))
        model = str((device or {}).get("model") or "h5075")

        await self.db.update_backfill_job(job_id, status="running")
        self._worker = "busy"
        self._live = LiveJobProgress(
            job_id=job_id,
            address=address,
            name=name,
            phase=phase,
            window_start=window_start,
            window_end=window_end,
            samples_done=0,
            samples_expected=expected,
            started_at=time.time(),
        )

        if not await self.db.is_backfill_enabled(address):
            await self.db.update_backfill_job(
                job_id,
                status="cancelled",
                error="disabled by user",
            )
            return

        # Gate: recently seen?
        last_seen = float((device or {}).get("last_seen") or 0.0)
        age = time.time() - last_seen if last_seen else 1e9
        if age > self.cfg.seen_max_age_seconds:
            await self.db.update_backfill_job(
                job_id,
                status="deferred",
                error=f"not seen for {age:.0f}s",
            )
            await self.db.upsert_backfill_state(address, last_attempt_ts=time.time())
            self._weak_backoff[address] = (
                time.time() + self.cfg.weak_rssi_backoff_seconds
            )
            return

        # Prefer strong RSSI when known from last reading / state.
        known_rssi = (device or {}).get("rssi")
        state = await self.db.get_backfill_state(address)
        if known_rssi is None and state:
            known_rssi = state.get("last_rssi")
        local_rssi_i: int | None = None
        if known_rssi is not None:
            try:
                local_rssi_i = int(known_rssi)
            except (TypeError, ValueError):
                local_rssi_i = None

        if (
            local_rssi_i is not None
            and local_rssi_i < self.cfg.min_rssi
            and time.time() < self._weak_backoff.get(address, 0.0)
        ):
            await self.db.update_backfill_job(
                job_id,
                status="deferred",
                error=f"rssi {local_rssi_i} below {self.cfg.min_rssi}",
            )
            return

        # Yield to a peer with a better signal when possible.
        try:
            yield_reason = await self._yield_to_better_peer(address, local_rssi_i)
        except Exception:
            logger.exception("Peer RSSI election failed for %s", address)
            yield_reason = None
        if yield_reason:
            await self.db.update_backfill_job(
                job_id,
                status="deferred",
                error=yield_reason,
            )
            self._weak_backoff[address] = (
                time.time() + self.cfg.weak_rssi_backoff_seconds
            )
            logger.info(
                "Backfill job %s %s [%s] deferred: %s",
                job_id,
                name,
                phase,
                yield_reason,
            )
            return

        fallback_battery = await self.db.last_battery(address)
        if fallback_battery is None and state and state.get("last_battery") is not None:
            fallback_battery = int(state["last_battery"])

        now = time.time()
        start_min = max(1, int(round((now - window_start) / 60.0)))
        end_min = max(1, int(round((now - window_end) / 60.0)))
        if start_min < end_min:
            start_min, end_min = end_min, start_min
        start_min = min(start_min, MAX_HISTORY_MINUTES)

        inserted_count = 0
        done_samples = 0

        def on_sample(sample: Any, _notif: int) -> None:
            nonlocal done_samples
            done_samples += 1
            self._live.samples_done = done_samples
            self._live.last_sample_ts = sample.ts
            self._live.last_sample_temp = sample.temperature_c

        if self.scanner is not None:
            await self.scanner.pause_for_gatt()
        try:
            result = await download_history(
                address,
                start_min=start_min,
                end_min=end_min,
                timeout=self.cfg.connect_timeout,
                fallback_battery=fallback_battery,
                on_sample=on_sample,
                now=now,
            )
        finally:
            if self.scanner is not None:
                await self.scanner.resume_after_gatt()

        if not await self.db.is_backfill_enabled(address):
            await self.db.update_backfill_job(
                job_id,
                status="cancelled",
                samples_done=done_samples,
                error="disabled by user",
            )
            return

        if result.rssi is not None:
            self._live.rssi = result.rssi
        elif local_rssi_i is not None:
            self._live.rssi = local_rssi_i

        battery = result.battery if result.battery is not None else fallback_battery
        if battery is None:
            battery = 0
        self._live.battery = battery

        await self.db.upsert_backfill_state(
            address,
            last_attempt_ts=time.time(),
            last_rssi=result.rssi if result.rssi is not None else local_rssi_i,
            last_battery=battery,
            success=bool(result.samples) and result.error is None,
        )

        if result.error and not result.samples:
            err_l = (result.error or "").lower()
            status = "failed"
            if "not found" in err_l or "inprogress" in err_l.replace(" ", ""):
                status = "deferred"
            if result.rssi is not None and result.rssi < self.cfg.min_rssi:
                status = "deferred"
                self._weak_backoff[address] = (
                    time.time() + self.cfg.weak_rssi_backoff_seconds
                )
            elif "not found" in err_l or "inprogress" in err_l.replace(" ", ""):
                self._weak_backoff[address] = (
                    time.time() + self.cfg.weak_rssi_backoff_seconds
                )
            await self.db.update_backfill_job(
                job_id,
                status=status,
                samples_done=0,
                error=result.error,
            )
            logger.warning(
                "Backfill job %s %s [%s] failed: %s",
                job_id,
                name,
                phase,
                result.error,
            )
            return

        # Prefer known RSSI from discovery for stored rows.
        store_rssi = result.rssi if result.rssi is not None else local_rssi_i
        samples_payload = [
            (_minute_floor(s.ts) * 60.0, s.temperature_c, s.humidity)
            for s in result.samples
            if window_start - 30.0 <= s.ts < window_end + 30.0
        ]
        # If decode window slightly drifts, still store all samples from the pull.
        if not samples_payload and result.samples:
            samples_payload = [
                (_minute_floor(s.ts) * 60.0, s.temperature_c, s.humidity)
                for s in result.samples
            ]

        source = self.source_tag
        inserted_count = await self.db.insert_gatt_readings(
            address=address,
            display_name=name,
            model=model,
            samples=samples_payload,
            battery=int(battery),
            rssi=store_rssi,
            source=source,
        )
        self._publish_gatt_samples(
            address=address,
            name=name,
            model=model,
            samples=samples_payload,
            battery=int(battery),
            rssi=store_rssi,
        )
        self._live.samples_done = len(samples_payload)
        await self.db.update_backfill_job(
            job_id,
            status="done",
            samples_done=len(samples_payload),
            samples_expected=max(expected, len(samples_payload)),
            error=result.error,
        )
        if result.rssi is not None and result.rssi < self.cfg.min_rssi:
            self._weak_backoff[address] = (
                time.time() + self.cfg.weak_rssi_backoff_seconds / 2
            )
        logger.info(
            "Backfill job %s %s [%s] stored %d/%d sample(s) in %.1fs%s",
            job_id,
            name,
            phase,
            inserted_count,
            len(samples_payload),
            result.duration_s,
            f" ({result.error})" if result.error else "",
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self.cfg.enabled:
            logger.info("GATT history backfill disabled")
            return

        recovered = await self.db.reset_running_backfill_jobs()
        if recovered:
            logger.info("Re-queued %d interrupted backfill job(s)", recovered)

        enabled_set = await self.db.list_backfill_enabled()
        pruned = await self.db.clear_open_backfill_jobs_except(enabled_set)
        if pruned:
            logger.info(
                "Cleared %d open backfill job(s) for disabled sensor(s) at startup",
                pruned,
            )

        logger.info(
            "GATT history backfill started (lookback=%.0fd, max_job=%dm, min_rssi=%d)",
            self.cfg.lookback_days,
            self.cfg.max_job_minutes,
            self.cfg.min_rssi,
        )
        try:
            while not stop_event.is_set():
                if self._paused:
                    self._worker = "paused"
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(), timeout=self.cfg.poll_seconds
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

                try:
                    await self.refresh_gaps()
                except Exception:
                    logger.exception("Backfill gap refresh failed")

                job = await self._pick_job()
                if job is None:
                    self._worker = "idle"
                    self._live = LiveJobProgress()
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(), timeout=self.cfg.poll_seconds
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

                try:
                    await self._run_job(job)
                except Exception as exc:
                    logger.exception("Backfill job crashed")
                    try:
                        await self.db.update_backfill_job(
                            int(job["id"]),
                            status="failed",
                            error=str(exc),
                        )
                    except Exception:
                        pass
                finally:
                    if not self._paused:
                        self._worker = "idle"
                    self._live = LiveJobProgress()

                # Brief yield between jobs so ads/UI stay responsive.
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._worker = "idle"
            logger.info("GATT history backfill stopped")
