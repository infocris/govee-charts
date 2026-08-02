"""Single-worker GATT history backfill queue (recent gaps first)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from govee_charts.db import Database
from govee_charts.history_gatt import MAX_HISTORY_MINUTES, download_history

logger = logging.getLogger(__name__)

PHASE_PRIORITY = {
    "hour": 0,
    "day": 1,
    "week": 2,
    "deep": 3,
}

SOURCE = "gatt-history"


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BackfillConfig:
        raw = raw or {}
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

    def __post_init__(self) -> None:
        self._paused = False
        self._worker: str = "idle"
        self._live = LiveJobProgress()
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_ts = 0.0
        self._rr_cursor = 0
        self._weak_backoff: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

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
        pending = await self.db.list_backfill_jobs(
            statuses=["pending", "deferred"], limit=200
        )
        devices = {d["address"].upper(): d for d in await self.db.list_devices()}

        # Summarize queue per device (waiting only).
        by_addr: dict[str, dict[str, Any]] = {}
        for job in pending:
            if self._live.job_id and job["id"] == self._live.job_id:
                continue
            addr = str(job["address"]).upper()
            entry = by_addr.get(addr)
            if entry is None:
                dev = devices.get(addr) or {}
                entry = {
                    "address": addr,
                    "name": self._label(addr, str(dev.get("name") or addr)),
                    "phase": job["phase"],
                    "jobs": 0,
                    "samples_expected": 0,
                    "priority": job["priority"],
                }
                by_addr[addr] = entry
            entry["jobs"] += 1
            entry["samples_expected"] += int(job.get("samples_expected") or 0)
            # Keep the highest-priority (lowest number) phase label.
            if int(job["priority"]) < int(entry["priority"]):
                entry["phase"] = job["phase"]
                entry["priority"] = job["priority"]

        queue = sorted(
            by_addr.values(),
            key=lambda e: (int(e["priority"]), -int(e["samples_expected"]), e["name"]),
        )

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
            },
        }

    def _label(self, address: str, fallback: str) -> str:
        return self.labels.get(address.upper()) or fallback

    async def refresh_gaps(self, *, force: bool = False) -> int:
        """Detect gaps and enqueue jobs. Returns number of newly enqueued jobs."""
        async with self._refresh_lock:
            now = time.time()
            if (
                not force
                and self._last_refresh_ts
                and now - self._last_refresh_ts < self.cfg.poll_seconds
            ):
                return 0
            self._last_refresh_ts = now
            devices = await self.db.list_devices()
            enqueued = 0
            bands = _phase_bands(now, self.cfg.lookback_days)
            for device in devices:
                addr = str(device["address"]).upper()
                # Only local BLE MACs with a model (skip pure peer-only if desired —
                # peers may still benefit from local GATT if in range).
                model = str(device.get("model") or "").lower()
                if model and model not in ("h5075", "h5072", "h5179"):
                    continue
                for phase, band_start, band_end in bands:
                    existing = await self.db.reading_minutes(addr, band_start, band_end)
                    for win_start, win_end, expected in _missing_ranges(
                        existing,
                        band_start,
                        band_end,
                        max_job_minutes=self.cfg.max_job_minutes,
                    ):
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
                logger.info("Backfill enqueued %d job(s)", enqueued)
            return enqueued

    async def _pick_job(self) -> dict[str, Any] | None:
        pending = await self.db.list_backfill_jobs(
            statuses=["pending"], limit=300
        )
        if not pending:
            # Promote deferred that are old enough.
            deferred = await self.db.list_backfill_jobs(
                statuses=["deferred"], limit=100
            )
            now = time.time()
            for job in deferred:
                addr = str(job["address"]).upper()
                until = self._weak_backoff.get(addr, 0.0)
                if now >= until:
                    await self.db.update_backfill_job(job["id"], status="pending")
                    pending.append(job)
            if not pending:
                return None

        # Best priority first.
        best_pri = min(int(j["priority"]) for j in pending)
        candidates = [j for j in pending if int(j["priority"]) == best_pri]
        # Round-robin across devices within the same priority.
        addresses = sorted({str(j["address"]).upper() for j in candidates})
        if not addresses:
            return None
        self._rr_cursor = self._rr_cursor % len(addresses)
        preferred = addresses[self._rr_cursor]
        self._rr_cursor = (self._rr_cursor + 1) % len(addresses)
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
        if (
            known_rssi is not None
            and int(known_rssi) < self.cfg.min_rssi
            and time.time() < self._weak_backoff.get(address, 0.0)
        ):
            await self.db.update_backfill_job(
                job_id,
                status="deferred",
                error=f"rssi {known_rssi} below {self.cfg.min_rssi}",
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

        result = await download_history(
            address,
            start_min=start_min,
            end_min=end_min,
            timeout=self.cfg.connect_timeout,
            fallback_battery=fallback_battery,
            on_sample=on_sample,
            now=now,
        )

        if result.rssi is not None:
            self._live.rssi = result.rssi
        elif known_rssi is not None:
            self._live.rssi = int(known_rssi)

        battery = result.battery if result.battery is not None else fallback_battery
        if battery is None:
            battery = 0
        self._live.battery = battery

        await self.db.upsert_backfill_state(
            address,
            last_attempt_ts=time.time(),
            last_rssi=result.rssi if result.rssi is not None else (
                int(known_rssi) if known_rssi is not None else None
            ),
            last_battery=battery,
            success=bool(result.samples) and result.error is None,
        )

        if result.error and not result.samples:
            status = "deferred" if "not found" in (result.error or "") else "failed"
            if result.rssi is not None and result.rssi < self.cfg.min_rssi:
                status = "deferred"
                self._weak_backoff[address] = (
                    time.time() + self.cfg.weak_rssi_backoff_seconds
                )
            elif "not found" in (result.error or ""):
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
        store_rssi = result.rssi if result.rssi is not None else (
            int(known_rssi) if known_rssi is not None else None
        )
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

        inserted_count = await self.db.insert_gatt_readings(
            address=address,
            display_name=name,
            model=model,
            samples=samples_payload,
            battery=int(battery),
            rssi=store_rssi,
            source=SOURCE,
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
