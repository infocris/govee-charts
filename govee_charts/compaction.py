"""Per-device readings compaction (min/max/avg rollups) to save SQLite space."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from govee_charts.db import Database

log = logging.getLogger(__name__)

COMPACTION_POLICIES = ("none", "balanced", "aggressive", "archive", "adaptive")

# Age buckets for System storage UI (days since now).
AGE_BUCKET_DEFS: tuple[tuple[str, float, float | None], ...] = (
    ("0-7d", 0.0, 7.0),
    ("7-30d", 7.0, 30.0),
    ("30-90d", 30.0, 90.0),
    ("90-180d", 90.0, 180.0),
    ("180-365d", 180.0, 365.0),
    ("365d+", 365.0, None),
)

# Assumed live sample interval when estimating post-policy size.
_ASSUMED_SAMPLE_INTERVAL_S = 60.0
# Rough on-disk cost of one readings_rollup row (incl. indexes).
_BYTES_PER_ROLLUP = 200
# Heuristic keep-ratio for adaptive policy on data older than raw_days
# (volatile raw kept + sparse rollups for stable stretches).
_ADAPTIVE_KEEP_FACTOR = 0.35


@dataclass(frozen=True)
class CompactionTier:
    """Age windows relative to *now* for a named policy."""

    # Keep raw samples newer than this many days.
    raw_days: float
    # (older_than_days, younger_than_days|None, bucket_secs)
    # Data with age in [older_than, younger_than) uses that bucket.
    tiers: tuple[tuple[float, float | None, int], ...]


@dataclass(frozen=True)
class AdaptiveParams:
    """Variance-aware compaction: aggregate flat stretches, keep swings."""

    raw_days: float = 30.0
    # Max temperature range (°C) inside a "stable" segment.
    temp_epsilon_c: float = 0.3
    # Minimum segment size before replacing raw with one rollup.
    min_stable_samples: int = 8
    min_stable_secs: float = 600.0
    # A gap larger than this breaks the current segment.
    max_gap_secs: float = 900.0


POLICY_TIERS: dict[str, CompactionTier] = {
    "none": CompactionTier(raw_days=1e9, tiers=()),
    "balanced": CompactionTier(
        raw_days=30.0,
        tiers=(
            (30.0, 180.0, 15 * 60),
            (180.0, 730.0, 3600),
            (730.0, None, 86400),
        ),
    ),
    "aggressive": CompactionTier(
        raw_days=7.0,
        tiers=(
            (7.0, 90.0, 15 * 60),
            (90.0, 365.0, 3600),
            (365.0, None, 86400),
        ),
    ),
    "archive": CompactionTier(
        raw_days=7.0,
        tiers=(
            (7.0, 180.0, 3600),
            (180.0, None, 86400),
        ),
    ),
    # Placeholder tiers for catalog/raw_days; compaction uses AdaptiveParams.
    "adaptive": CompactionTier(raw_days=30.0, tiers=()),
}

ADAPTIVE_PARAMS = AdaptiveParams()

POLICY_LABELS: dict[str, str] = {
    "none": "None (keep raw)",
    "balanced": "Balanced (30d raw → 15m / 1h / 1d)",
    "aggressive": "Aggressive (7d raw → 15m / 1h / 1d)",
    "archive": "Archive (7d raw → 1h / 1d)",
    "adaptive": "Adaptive (30d raw → merge flat ΔT, keep swings)",
}


def normalize_policy(policy: str | None) -> str:
    key = str(policy or "none").strip().lower()
    if key not in COMPACTION_POLICIES:
        raise ValueError(
            f"policy must be one of: {', '.join(COMPACTION_POLICIES)}"
        )
    return key


def bucket_secs_for_age(policy: str, age_days: float) -> int | None:
    """Return rollup bucket size for a sample of given age, or None if keep raw.

    For ``adaptive``, returns ``0`` as a sentinel (variable-length segments)
    when the sample is older than the raw window.
    """
    policy = normalize_policy(policy)
    if policy == "adaptive":
        return 0 if age_days >= ADAPTIVE_PARAMS.raw_days else None
    tiers = POLICY_TIERS[policy]
    if age_days < tiers.raw_days:
        return None
    for older, younger, bucket_secs in tiers.tiers:
        if age_days < older:
            continue
        if younger is None or age_days < younger:
            return int(bucket_secs)
    return None


def estimate_bytes_after_policy(
    *,
    policy: str,
    age_buckets: list[dict[str, Any]],
    bytes_per_raw: float,
    rollup_bytes: int = 0,
) -> int:
    """Estimate on-disk size after applying ``policy`` to current age mix."""
    policy = normalize_policy(policy)
    if policy == "none":
        total = sum(int(b.get("bytes") or 0) for b in age_buckets) + int(rollup_bytes)
        return int(total)

    est = 0.0
    for b in age_buckets:
        samples = int(b.get("samples") or 0)
        cur_bytes = float(b.get("bytes") or 0)
        if samples <= 0:
            continue
        # Mid-age of the bucket for tier lookup.
        key = str(b.get("key") or "")
        age_mid = _age_mid_days(key)
        bucket_secs = bucket_secs_for_age(policy, age_mid)
        if bucket_secs is None:
            est += cur_bytes
            continue
        if policy == "adaptive":
            est += cur_bytes * _ADAPTIVE_KEEP_FACTOR
            continue
        # One rollup replaces ~bucket_secs/sample_interval raw rows.
        factor = min(1.0, _ASSUMED_SAMPLE_INTERVAL_S / float(bucket_secs))
        est += samples * factor * float(_BYTES_PER_ROLLUP)
    # Existing rollups already compacted; keep a floor.
    return int(max(est, float(rollup_bytes)))


def _age_mid_days(key: str) -> float:
    mapping = {
        "0-7d": 3.5,
        "7-30d": 18.5,
        "30-90d": 60.0,
        "90-180d": 135.0,
        "180-365d": 272.0,
        "365d+": 500.0,
    }
    return float(mapping.get(key, 60.0))


def policy_catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in COMPACTION_POLICIES:
        tiers = POLICY_TIERS[key]
        entry: dict[str, Any] = {
            "id": key,
            "label": POLICY_LABELS[key],
            "raw_days": None if key == "none" else tiers.raw_days,
            "tiers": [
                {
                    "older_than_days": older,
                    "younger_than_days": younger,
                    "bucket_secs": bucket_secs,
                }
                for older, younger, bucket_secs in tiers.tiers
            ],
        }
        if key == "adaptive":
            entry["adaptive"] = {
                "temp_epsilon_c": ADAPTIVE_PARAMS.temp_epsilon_c,
                "min_stable_samples": ADAPTIVE_PARAMS.min_stable_samples,
                "min_stable_secs": ADAPTIVE_PARAMS.min_stable_secs,
            }
        out.append(entry)
    return out


@dataclass(frozen=True)
class StableSegment:
    """Inclusive raw-sample span to replace with one min/max/avg rollup."""

    start_ts: float
    end_ts: float
    n: int
    temp_avg: float
    temp_min: float
    temp_max: float
    hum_avg: float
    hum_min: float
    hum_max: float

    @property
    def bucket_secs(self) -> int:
        span = max(1.0, float(self.end_ts) - float(self.start_ts))
        return max(1, int(round(span)))


class AdaptiveSegmenter:
    """Incremental flat-temperature segmenter (safe across chunked reads)."""

    def __init__(self, params: AdaptiveParams | None = None) -> None:
        self.cfg = params or ADAPTIVE_PARAMS
        self._seg: list[dict[str, Any]] = []
        self._t_min = 0.0
        self._t_max = 0.0
        self.completed: list[StableSegment] = []
        self.samples_seen = 0

    def _flush(self, closed: list[dict[str, Any]]) -> None:
        if len(closed) < self.cfg.min_stable_samples:
            return
        t0 = float(closed[0]["ts"])
        t1 = float(closed[-1]["ts"])
        if (t1 - t0) < self.cfg.min_stable_secs:
            return
        temps = [float(r["temperature_c"]) for r in closed]
        hums = [float(r["humidity"]) for r in closed]
        self.completed.append(
            StableSegment(
                start_ts=t0,
                end_ts=t1,
                n=len(closed),
                temp_avg=sum(temps) / len(temps),
                temp_min=min(temps),
                temp_max=max(temps),
                hum_avg=sum(hums) / len(hums),
                hum_min=min(hums),
                hum_max=max(hums),
            )
        )

    def feed(self, rows: list[dict[str, Any]]) -> None:
        cfg = self.cfg
        for row in rows:
            self.samples_seen += 1
            ts = float(row["ts"])
            temp = float(row["temperature_c"])
            if not self._seg:
                self._seg = [row]
                self._t_min = self._t_max = temp
                continue
            prev_ts = float(self._seg[-1]["ts"])
            gap = ts - prev_ts
            if gap > cfg.max_gap_secs or gap < 0:
                self._flush(self._seg)
                self._seg = [row]
                self._t_min = self._t_max = temp
                continue
            new_min = min(self._t_min, temp)
            new_max = max(self._t_max, temp)
            if (new_max - new_min) <= cfg.temp_epsilon_c:
                self._seg.append(row)
                self._t_min, self._t_max = new_min, new_max
                continue
            self._flush(self._seg)
            self._seg = [row]
            self._t_min = self._t_max = temp

    def finish(self) -> list[StableSegment]:
        if self._seg:
            self._flush(self._seg)
            self._seg = []
        return list(self.completed)

    def take_completed(self) -> list[StableSegment]:
        out = list(self.completed)
        self.completed.clear()
        return out


def find_stable_segments(
    rows: list[dict[str, Any]],
    params: AdaptiveParams | None = None,
    *,
    flush_trailing: bool = True,
) -> list[StableSegment]:
    """Split a time-ordered series into rollup-worthy flat temperature runs.

    A segment stays open while ``max(temp) - min(temp) ≤ temp_epsilon_c`` and
    gaps stay within ``max_gap_secs``. Segments that meet the min sample/duration
    thresholds become rollups; short or swinging stretches are left as raw.
    """
    seg = AdaptiveSegmenter(params)
    seg.feed(rows)
    if flush_trailing:
        return seg.finish()
    return seg.take_completed()


def summarize_adaptive_segments(
    segments: list[StableSegment],
    *,
    samples_in_window: int,
) -> dict[str, Any]:
    """Build preview stats from completed adaptive segments."""
    rolled = sum(s.n for s in segments)
    kept_volatile = max(0, int(samples_in_window) - rolled)
    if not segments:
        return {
            "stable_segments": 0,
            "samples_rolled": 0,
            "samples_kept_volatile": kept_volatile,
            "avg_segment_samples": 0.0,
            "avg_segment_span_secs": 0.0,
            "avg_segment_delta_t": 0.0,
            "max_segment_span_secs": 0,
            "max_segment_samples": 0,
        }
    spans = [s.bucket_secs for s in segments]
    deltas = [s.temp_max - s.temp_min for s in segments]
    ns = [s.n for s in segments]
    return {
        "stable_segments": len(segments),
        "samples_rolled": rolled,
        "samples_kept_volatile": kept_volatile,
        "avg_segment_samples": round(sum(ns) / len(ns), 1),
        "avg_segment_span_secs": round(sum(spans) / len(spans), 1),
        "avg_segment_delta_t": round(sum(deltas) / len(deltas), 3),
        "max_segment_span_secs": max(spans),
        "max_segment_samples": max(ns),
    }


@dataclass
class CompactionConfig:
    enabled: bool = True
    interval_s: float = 3600.0
    default_policy: str = "none"
    # Max raw rows deleted per device per tick (chunking).
    max_delete_per_device: int = 50_000

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> CompactionConfig:
        data = dict(raw or {})
        default_policy = str(data.get("default_policy") or "none").strip().lower()
        if default_policy not in COMPACTION_POLICIES:
            default_policy = "none"
        return cls(
            enabled=bool(data.get("enabled", True)),
            interval_s=max(60.0, float(data.get("interval_s") or 3600.0)),
            default_policy=default_policy,
            max_delete_per_device=max(
                1000, int(data.get("max_delete_per_device") or 50_000)
            ),
        )


class CompactionService:
    """Periodic workers job: roll up raw readings per device policy."""

    def __init__(self, db: Database, cfg: CompactionConfig) -> None:
        self.db = db
        self.cfg = cfg

    async def run(self, stop_event: asyncio.Event) -> None:
        log.info(
            "Compaction worker started (interval=%.0fs, default_policy=%s)",
            self.cfg.interval_s,
            self.cfg.default_policy,
        )
        # First pass shortly after startup so System UI can reflect progress.
        next_run = time.time() + 30.0
        while not stop_event.is_set():
            now = time.time()
            wait = max(1.0, next_run - now)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait)
                break
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break
            try:
                summary = await self.run_once()
                if summary["devices_touched"]:
                    log.info(
                        "Compaction: %d device(s), raw_deleted=%d, rollups_upserted=%d",
                        summary["devices_touched"],
                        summary["raw_deleted"],
                        summary["rollups_upserted"],
                    )
            except Exception:
                log.exception("Compaction pass failed")
            next_run = time.time() + self.cfg.interval_s
        log.info("Compaction worker stopped")

    async def run_once(self) -> dict[str, int]:
        states = await self.db.list_compaction_states()
        touched = 0
        raw_deleted = 0
        rollups = 0
        for state in states:
            policy = normalize_policy(state.get("policy"))
            if policy == "none":
                continue
            address = str(state["address"])
            result = await self.db.compact_device(
                address,
                policy,
                max_delete=self.cfg.max_delete_per_device,
            )
            if result["raw_deleted"] or result["rollups_upserted"]:
                touched += 1
                raw_deleted += int(result["raw_deleted"])
                rollups += int(result["rollups_upserted"])
            # Yield between devices so BLE / API stay responsive.
            await asyncio.sleep(0)
        return {
            "devices_touched": touched,
            "raw_deleted": raw_deleted,
            "rollups_upserted": rollups,
        }
