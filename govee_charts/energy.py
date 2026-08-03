"""Apartment electrical energy → indoor heat estimates."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from govee_charts.db import Database
from govee_charts.hvac import hvac_active_bands

KWH_TO_MJ = 3.6
KWH_TO_KCAL = 860.0


def day_start_ts(now: float, tz_name: str = "Europe/Paris") -> float:
    """Local midnight for the calendar day containing ``now``."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    local = datetime.fromtimestamp(now, tz=timezone.utc).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


def is_hvac_cooling(state: str | None) -> bool:
    text = str(state or "").strip().lower()
    return text in ("cool", "dry")


def is_hvac_heating(state: str | None) -> bool:
    text = str(state or "").strip().lower()
    return text in ("heat",)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def energy_delta_kwh(
    samples: list[dict[str, Any]],
    *,
    start_ts: float,
    end_ts: float,
) -> float | None:
    """
    Positive energy increase over [start_ts, end_ts].

    Ignores downward jumps (meter reset). Returns None if not enough data.
    """
    if not samples:
        return None
    pts = [
        (float(s["ts"]), float(s["value_kwh"]))
        for s in samples
        if s.get("ts") is not None and s.get("value_kwh") is not None
    ]
    if len(pts) < 1:
        return None
    pts.sort(key=lambda x: x[0])
    first: tuple[float, float] | None = None
    for ts, val in pts:
        if ts >= start_ts:
            first = (ts, val)
            break
    if first is None:
        before = [p for p in pts if p[0] <= start_ts]
        if not before:
            return None
        first = before[-1]
    last = pts[-1]
    if last[0] < start_ts:
        return None
    total = 0.0
    prev = first[1]
    started = False
    for ts, val in pts:
        if ts < first[0]:
            continue
        if ts > end_ts:
            break
        if not started:
            prev = val
            started = True
            continue
        delta = val - prev
        if delta > 0:
            total += delta
        prev = val
    return total


def integrate_power_kwh(
    power_points: list[dict[str, Any]],
    *,
    start_ts: float,
    end_ts: float,
    watts_fn,
) -> float:
    """
    Integrate effective watts over [start_ts, end_ts] using step-hold samples.

    ``watts_fn(ts, raw_watts) -> float`` returns the component to integrate.
    """
    pts = [
        (float(p["ts"]), float(p["watts"]))
        for p in power_points
        if p.get("ts") is not None and p.get("watts") is not None
    ]
    if not pts or end_ts <= start_ts:
        return 0.0
    pts.sort(key=lambda x: x[0])
    before = [p for p in pts if p[0] <= start_ts]
    window = [p for p in pts if start_ts < p[0] <= end_ts]
    series: list[tuple[float, float]] = []
    if before:
        series.append((start_ts, before[-1][1]))
    elif window:
        series.append((start_ts, window[0][1]))
    else:
        return 0.0
    series.extend(window)
    if series[-1][0] < end_ts:
        series.append((end_ts, series[-1][1]))

    joules = 0.0
    for i in range(len(series) - 1):
        t0, w0 = series[i]
        t1, _w1 = series[i + 1]
        t_a = max(t0, start_ts)
        t_b = min(t1, end_ts)
        if t_b <= t_a:
            continue
        watts = max(0.0, float(watts_fn(t_a, w0)))
        joules += watts * (t_b - t_a)
    return joules / 3.6e6


def _baseline_watts(
    power_points: list[dict[str, Any]],
    band_start: float,
    *,
    lookback_s: float = 3600.0,
    idle_floor_w: float,
    off_watts: list[float] | None = None,
) -> float:
    """
    Baseline home load just before an HVAC band.

    Prefer the median of the 30–60 min lookback; if too thin, fall back to the
    median of same-window off-period samples, then idle_floor_w.
    """
    pts = [
        float(p["watts"])
        for p in power_points
        if p.get("watts") is not None
        and band_start - lookback_s <= float(p["ts"]) < band_start
    ]
    med = _median(pts) if len(pts) >= 3 else None
    if med is None and off_watts:
        med = _median(off_watts)
    if med is None:
        pts2 = [
            float(p["watts"])
            for p in power_points
            if p.get("watts") is not None and float(p["ts"]) < band_start
        ]
        med = _median(pts2[-40:]) if pts2 else None
    if med is None:
        return float(idle_floor_w)
    return max(float(idle_floor_w), float(med))


def _off_period_watts(
    power_points: list[dict[str, Any]],
    active_bands: list[dict[str, float]],
    *,
    start_ts: float,
    end_ts: float,
) -> list[float]:
    """Power samples in [start_ts, end_ts] that fall outside active HVAC bands."""
    bands_s = [
        (float(b["x1"]) / 1000.0, float(b["x2"]) / 1000.0) for b in active_bands
    ]

    def in_band(ts: float) -> bool:
        for a, b in bands_s:
            if a <= ts < b:
                return True
        return False

    out: list[float] = []
    for p in power_points:
        if p.get("watts") is None or p.get("ts") is None:
            continue
        ts = float(p["ts"])
        if ts < start_ts or ts > end_ts:
            continue
        if in_band(ts):
            continue
        out.append(float(p["watts"]))
    return out


def estimate_ac_energy_kwh(
    power_points: list[dict[str, Any]],
    bands: list[dict[str, float]],
    *,
    idle_floor_w: float = 150.0,
    off_watts: list[float] | None = None,
) -> float:
    """
    Estimate AC kWh from whole-home power during active HVAC bands.

    ``bands`` use Chart.js ms epochs ({x1, x2}) from ``hvac_active_bands``.
    """
    total = 0.0
    for band in bands:
        start = float(band["x1"]) / 1000.0
        end = float(band["x2"]) / 1000.0
        if end <= start:
            continue
        base = _baseline_watts(
            power_points,
            start,
            idle_floor_w=idle_floor_w,
            off_watts=off_watts,
        )

        def watts_fn(_ts: float, raw: float, _base: float = base) -> float:
            return max(0.0, raw - _base)

        total += integrate_power_kwh(
            power_points, start_ts=start, end_ts=end, watts_fn=watts_fn
        )
    return total


def _band_baselines(
    power_points: list[dict[str, Any]],
    bands: list[dict[str, float]],
    *,
    idle_floor_w: float,
    off_watts: list[float] | None = None,
) -> list[tuple[float, float, float]]:
    """List of (start_s, end_s, baseline_w) for each band."""
    out: list[tuple[float, float, float]] = []
    for band in bands:
        start = float(band["x1"]) / 1000.0
        end = float(band["x2"]) / 1000.0
        if end <= start:
            continue
        base = _baseline_watts(
            power_points,
            start,
            idle_floor_w=idle_floor_w,
            off_watts=off_watts,
        )
        out.append((start, end, base))
    return out


def build_heat_gain_series(
    power_points: list[dict[str, Any]],
    *,
    cool_bands: list[dict[str, float]],
    heat_bands: list[dict[str, float]],
    start_ts: float,
    end_ts: float,
    other_loads_indoor_fraction: float = 0.90,
    ac_cop: float = 3.0,
    idle_floor_w: float = 150.0,
    off_watts: list[float] | None = None,
) -> list[dict[str, Any]]:
    """
    Instantaneous net indoor heat rate (W) from whole-home power + HVAC mode.

    Water-heater power is not metered separately here, so tank load is treated
    as part of ``other`` for the series (totals in the summary use meter deltas).
    """
    f_other = min(1.0, max(0.0, float(other_loads_indoor_fraction)))
    cop = max(0.0, float(ac_cop))
    cool = _band_baselines(
        power_points, cool_bands, idle_floor_w=idle_floor_w, off_watts=off_watts
    )
    heat = _band_baselines(
        power_points, heat_bands, idle_floor_w=idle_floor_w, off_watts=off_watts
    )

    def mode_at(ts: float) -> tuple[str, float]:
        for a, b, base in cool:
            if a <= ts < b:
                return "cool", base
        for a, b, base in heat:
            if a <= ts < b:
                return "heat", base
        return "off", float(idle_floor_w)

    pts = [
        (float(p["ts"]), float(p["watts"]))
        for p in power_points
        if p.get("ts") is not None
        and p.get("watts") is not None
        and start_ts <= float(p["ts"]) <= end_ts
    ]
    pts.sort(key=lambda x: x[0])
    series: list[dict[str, Any]] = []
    for ts, p_home in pts:
        mode, base = mode_at(ts)
        p_ac = max(0.0, p_home - base) if mode in ("cool", "heat") else 0.0
        p_other = max(0.0, p_home - p_ac)
        q = f_other * p_other
        if mode == "cool":
            q -= cop * p_ac
        elif mode == "heat":
            q += cop * p_ac
        series.append({"ts": ts, "watts": round(q, 1)})
    return series


def cooling_bands_from_events(
    events: list[dict[str, Any]],
    *,
    now_ts: float | None = None,
) -> list[dict[str, float]]:
    """Active bands limited to cool/dry states (heat extraction)."""
    if not events:
        return []
    end = float(now_ts if now_ts is not None else time.time())
    bands: list[dict[str, float]] = []
    active_start: float | None = None
    for ev in events:
        ts = float(ev.get("ts") or 0)
        cooling = is_hvac_cooling(str(ev.get("state") or ""))
        if cooling and active_start is None:
            active_start = ts
        elif not cooling and active_start is not None:
            if ts > active_start:
                bands.append({"x1": active_start * 1000.0, "x2": ts * 1000.0})
            active_start = None
    if active_start is not None and end > active_start:
        bands.append({"x1": active_start * 1000.0, "x2": end * 1000.0})
    return bands


async def meter_delta_today_kwh(
    db: Database,
    entity_id: str,
    *,
    now: float,
    day_start: float,
    daily_reset: bool = False,
) -> float | None:
    """kWh consumed today for one meter entity."""
    if not entity_id:
        return None
    latest = await db.latest_energy(entity_id)
    if latest is None:
        return None
    if daily_reset:
        return max(0.0, float(latest["value_kwh"]))
    start_row = await db.energy_at_or_before(entity_id, day_start)
    if start_row is None:
        start_row = await db.energy_at_or_after(entity_id, day_start)
    if start_row is None:
        return None
    delta = float(latest["value_kwh"]) - float(start_row["value_kwh"])
    if delta < 0:
        hist = await db.energy_history(
            entity_id=entity_id, since=day_start - 3600.0
        )
        return energy_delta_kwh(hist, start_ts=day_start, end_ts=now)
    return delta


async def build_energy_summary(
    db: Database,
    *,
    energy_entity: str,
    water_heater_entity: str,
    power_entity: str,
    climate_entity: str,
    water_heater_indoor_fraction: float = 0.30,
    other_loads_indoor_fraction: float = 0.90,
    ac_cop: float = 3.0,
    ac_idle_floor_w: float = 150.0,
    timezone: str = "Europe/Paris",
    now: float | None = None,
    hours: float | None = None,
    include_heat_gain: bool = True,
) -> dict[str, Any]:
    """
    Electrical + indoor-heat summary for today (default) or the last ``hours``.
    """
    t_now = float(now if now is not None else time.time())
    if hours is not None and hours > 0:
        t_start = t_now - float(hours) * 3600.0
        window_label = f"{hours:g}h"
    else:
        t_start = day_start_ts(t_now, timezone)
        window_label = "today"

    f_wh = min(1.0, max(0.0, float(water_heater_indoor_fraction)))
    f_other = min(1.0, max(0.0, float(other_loads_indoor_fraction)))
    cop = max(0.0, float(ac_cop))

    home_kwh: float | None = None
    if energy_entity:
        if hours is None:
            home_kwh = await meter_delta_today_kwh(
                db,
                energy_entity,
                now=t_now,
                day_start=t_start,
                daily_reset=True,
            )
        else:
            hist = await db.energy_history(
                entity_id=energy_entity, since=t_start - 3600.0
            )
            home_kwh = energy_delta_kwh(hist, start_ts=t_start, end_ts=t_now)

    wh_kwh: float | None = None
    if water_heater_entity:
        if hours is None:
            wh_kwh = await meter_delta_today_kwh(
                db,
                water_heater_entity,
                now=t_now,
                day_start=t_start,
                daily_reset=False,
            )
        else:
            hist = await db.energy_history(
                entity_id=water_heater_entity, since=t_start - 3600.0
            )
            wh_kwh = energy_delta_kwh(hist, start_ts=t_start, end_ts=t_now)

    lookback_h = max(6.0, (t_now - t_start) / 3600.0 + 2.0)
    power_pts = await db.power_history(
        hours=lookback_h, entity_id=power_entity or None
    )
    events = await db.hvac_history(
        hours=lookback_h, entity_id=climate_entity or None
    )
    all_active = hvac_active_bands(events, now_ts=t_now)
    cool_bands = cooling_bands_from_events(events, now_ts=t_now)

    def _clip(bands: list[dict[str, float]]) -> list[dict[str, float]]:
        out: list[dict[str, float]] = []
        for b in bands:
            x1 = max(float(b["x1"]) / 1000.0, t_start)
            x2 = min(float(b["x2"]) / 1000.0, t_now)
            if x2 > x1:
                out.append({"x1": x1 * 1000.0, "x2": x2 * 1000.0})
        return out

    active_clipped = _clip(all_active)
    cool_clipped = _clip(cool_bands)
    off_watts = _off_period_watts(
        power_pts, active_clipped, start_ts=t_start, end_ts=t_now
    )

    ac_kwh = estimate_ac_energy_kwh(
        power_pts,
        active_clipped,
        idle_floor_w=ac_idle_floor_w,
        off_watts=off_watts,
    )
    ac_cool_kwh = estimate_ac_energy_kwh(
        power_pts,
        cool_clipped,
        idle_floor_w=ac_idle_floor_w,
        off_watts=off_watts,
    )

    if home_kwh is None and power_pts:

        def all_w(_ts: float, raw: float) -> float:
            return max(0.0, raw)

        home_kwh = integrate_power_kwh(
            power_pts, start_ts=t_start, end_ts=t_now, watts_fn=all_w
        )

    e_home = float(home_kwh or 0.0)
    e_wh = max(0.0, float(wh_kwh or 0.0))
    e_ac = max(0.0, float(ac_kwh))
    e_other = max(0.0, e_home - e_wh - e_ac)

    q_wh = f_wh * e_wh
    q_other = f_other * e_other
    q_extracted = cop * max(0.0, float(ac_cool_kwh))

    heat_bands: list[dict[str, float]] = []
    active_start: float | None = None
    for ev in events:
        ts = float(ev.get("ts") or 0)
        heating = is_hvac_heating(str(ev.get("state") or ""))
        if heating and active_start is None:
            active_start = ts
        elif not heating and active_start is not None:
            if ts > active_start:
                heat_bands.append(
                    {"x1": active_start * 1000.0, "x2": ts * 1000.0}
                )
            active_start = None
    if active_start is not None:
        heat_bands.append({"x1": active_start * 1000.0, "x2": t_now * 1000.0})
    heat_clipped = _clip(heat_bands)
    ac_heat_kwh = estimate_ac_energy_kwh(
        power_pts,
        heat_clipped,
        idle_floor_w=ac_idle_floor_w,
        off_watts=off_watts,
    )
    q_heat_delivered = cop * ac_heat_kwh

    q_indoor_kwh = q_wh + q_other - q_extracted + q_heat_delivered

    heat_gain: list[dict[str, Any]] = []
    if include_heat_gain:
        heat_gain = build_heat_gain_series(
            power_pts,
            cool_bands=cool_clipped,
            heat_bands=heat_clipped,
            start_ts=t_start,
            end_ts=t_now,
            other_loads_indoor_fraction=f_other,
            ac_cop=cop,
            idle_floor_w=ac_idle_floor_w,
            off_watts=off_watts,
        )

    return {
        "window": window_label,
        "since": t_start,
        "until": t_now,
        "home_kwh": round(e_home, 3),
        "water_heater_kwh": round(e_wh, 3),
        "ac_kwh": round(e_ac, 3),
        "ac_cool_kwh": round(float(ac_cool_kwh), 3),
        "other_kwh": round(e_other, 3),
        "heat_indoor_kwh": round(q_indoor_kwh, 3),
        "heat_indoor_mj": round(q_indoor_kwh * KWH_TO_MJ, 2),
        "heat_indoor_kcal": round(q_indoor_kwh * KWH_TO_KCAL, 0),
        # Aliases matching the plan wording for /api/hvac consumers.
        "home_today_kwh": round(e_home, 3) if hours is None else None,
        "water_heater_today_kwh": round(e_wh, 3) if hours is None else None,
        "ac_today_kwh": round(e_ac, 3) if hours is None else None,
        "heat_indoor_today_mj": (
            round(q_indoor_kwh * KWH_TO_MJ, 2) if hours is None else None
        ),
        "heat_indoor_today_kcal": (
            round(q_indoor_kwh * KWH_TO_KCAL, 0) if hours is None else None
        ),
        "breakdown": {
            "water_heater_indoor_kwh": round(q_wh, 3),
            "other_indoor_kwh": round(q_other, 3),
            "ac_extracted_kwh": round(q_extracted, 3),
            "ac_heat_delivered_kwh": round(q_heat_delivered, 3),
        },
        "assumptions": {
            "water_heater_indoor_fraction": f_wh,
            "other_loads_indoor_fraction": f_other,
            "ac_cop": cop,
            "ac_idle_floor_w": float(ac_idle_floor_w),
        },
        "heat_gain_w": heat_gain,
    }
