"""Open-Meteo hourly forecast client and sensor projections."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from govee_charts.apartment import ApartmentLayout, simulate_network
from govee_charts.db import Database

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = ROOT / "data" / "weather_cache.json"

# Minimum aligned hourly pairs before RC fit is trusted.
_MIN_ALIGNED = 12
# Max gap when matching a sensor sample to an outdoor hour.
_ALIGN_MAX_GAP_S = 2700.0
# Exterior sensors track outdoor weather quickly.
_EXTERIOR_TAU_HOURS = 0.25


@dataclass(frozen=True)
class WeatherConfig:
    enabled: bool = False
    place: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "Europe/Paris"
    cache_seconds: float = 1800.0
    forecast_hours: int = 48
    calib_hours: float = 48.0
    tau_min_hours: float = 0.5
    tau_max_hours: float = 24.0
    tau_default_hours: float = 3.0
    cache_path: str = "data/weather_cache.json"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> WeatherConfig:
        raw = raw or {}
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        try:
            latitude = float(lat) if lat not in (None, "") else None
        except (TypeError, ValueError):
            latitude = None
        try:
            longitude = float(lon) if lon not in (None, "") else None
        except (TypeError, ValueError):
            longitude = None
        return cls(
            enabled=bool(raw.get("enabled", False)),
            place=str(raw.get("place") or "").strip(),
            latitude=latitude,
            longitude=longitude,
            timezone=str(raw.get("timezone") or "Europe/Paris").strip()
            or "Europe/Paris",
            cache_seconds=float(raw.get("cache_seconds") or 1800.0),
            forecast_hours=int(raw.get("forecast_hours") or 48),
            calib_hours=float(raw.get("calib_hours") or 48.0),
            tau_min_hours=float(raw.get("tau_min_hours") or 0.5),
            tau_max_hours=float(raw.get("tau_max_hours") or 24.0),
            tau_default_hours=float(raw.get("tau_default_hours") or 3.0),
            cache_path=str(raw.get("cache_path") or "data/weather_cache.json"),
        )

    @property
    def past_days(self) -> int:
        """Open-Meteo past_days covering the calibration window."""
        return max(1, min(7, (int(self.calib_hours) + 23) // 24))


def _parse_iso_local(value: str, tz_name: str) -> float:
    """Parse Open-Meteo local ISO time (no offset) into UTC unix timestamp."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        dt = dt.replace(tzinfo=tz)
    return dt.timestamp()


def _cache_key(lat: float, lon: float, forecast_hours: int, past_days: int) -> str:
    # ~1 km grid — avoids cache misses from tiny GPS jitter
    # v3: + wind_speed_10m + wind_direction_10m
    return f"{lat:.2f},{lon:.2f}:{forecast_hours}:p{past_days}:wind1"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _rc_step(t: float, t_eq: float, dt_s: float, tau_s: float) -> float:
    """Exact discrete step toward equilibrium with time constant tau."""
    if dt_s <= 0:
        return t
    if tau_s <= 1e-6:
        return t_eq
    return t_eq + (t - t_eq) * math.exp(-dt_s / tau_s)


def _align_hourly(
    outdoor: list[dict[str, Any]],
    readings: list[dict[str, Any]],
    *,
    since: float,
    until: float,
    max_gap_s: float = _ALIGN_MAX_GAP_S,
) -> list[tuple[float, float, float]]:
    """Align sensor readings to outdoor hourly points → (ts, T_int, T_ext)."""
    if not outdoor or not readings:
        return []
    pairs: list[tuple[float, float, float]] = []
    for p in outdoor:
        ts = float(p["ts"])
        if ts < since or ts > until:
            continue
        nearest = min(readings, key=lambda r: abs(float(r["ts"]) - ts))
        if abs(float(nearest["ts"]) - ts) > max_gap_s:
            continue
        temp = nearest.get("temperature_c")
        if temp is None:
            continue
        pairs.append((ts, float(temp), float(p["temperature_c"])))
    return pairs


def _tau_grid(tau_min_h: float, tau_max_h: float, n: int = 24) -> list[float]:
    lo = max(1e-3, float(tau_min_h))
    hi = max(lo * 1.01, float(tau_max_h))
    if n <= 1:
        return [lo]
    ratio = (hi / lo) ** (1.0 / (n - 1))
    return [lo * (ratio**i) for i in range(n)]


def _rmse_for_tau(
    pairs: list[tuple[float, float, float]],
    delta: float,
    tau_hours: float,
) -> float:
    """Free-run RC from the first sample; score against later observations."""
    if len(pairs) < 2:
        return float("inf")
    tau_s = tau_hours * 3600.0
    t_sim = pairs[0][1]
    err_sq = 0.0
    count = 0
    for i in range(1, len(pairs)):
        ts_prev = pairs[i - 1][0]
        ts, t_obs, t_ext = pairs[i]
        dt = ts - ts_prev
        t_eq = t_ext + delta
        t_sim = _rc_step(t_sim, t_eq, dt, tau_s)
        err_sq += (t_sim - t_obs) ** 2
        count += 1
    if count == 0:
        return float("inf")
    return math.sqrt(err_sq / count)


def fit_rc(
    pairs: list[tuple[float, float, float]],
    *,
    tau_min_hours: float,
    tau_max_hours: float,
    tau_default_hours: float,
) -> tuple[str, float, float]:
    """Fit Δ then τ. Returns (model, bias_temp, tau_hours)."""
    if len(pairs) < _MIN_ALIGNED:
        return "offset", 0.0, 0.0

    deltas = [t_int - t_ext for _, t_int, t_ext in pairs]
    delta = _median(deltas)

    best_tau = float(tau_default_hours)
    best_rmse = _rmse_for_tau(pairs, delta, best_tau)
    default_rmse = best_rmse
    for tau in _tau_grid(tau_min_hours, tau_max_hours):
        rmse = _rmse_for_tau(pairs, delta, tau)
        if rmse < best_rmse:
            best_rmse = rmse
            best_tau = tau

    # Flat landscape → keep default rather than an arbitrary edge of the grid.
    if abs(default_rmse - best_rmse) < 0.05 and default_rmse < float("inf"):
        best_tau = float(tau_default_hours)

    best_tau = max(tau_min_hours, min(tau_max_hours, best_tau))
    return "rc", delta, best_tau


def simulate_rc_temp(
    outdoor_future: list[dict[str, Any]],
    *,
    t0: float,
    ts0: float,
    delta: float,
    tau_hours: float,
) -> list[float]:
    """Simulate temperature on future outdoor timestamps starting from t0@ts0."""
    tau_s = tau_hours * 3600.0
    t = t0
    prev_ts = ts0
    out: list[float] = []
    for p in outdoor_future:
        ts = float(p["ts"])
        t_eq = float(p["temperature_c"]) + delta
        t = _rc_step(t, t_eq, ts - prev_ts, tau_s)
        out.append(t)
        prev_ts = ts
    return out


class WeatherService:
    def __init__(
        self,
        cfg: WeatherConfig,
        cache_path: Path | None = None,
        apartment: ApartmentLayout | None = None,
    ) -> None:
        self.cfg = cfg
        self.apartment = apartment or ApartmentLayout()
        self._lock = asyncio.Lock()
        self._mem: dict[str, tuple[float, dict[str, Any]]] = {}
        self._resolved_config: dict[str, Any] | None = None
        path = cache_path
        if path is None:
            path = Path(cfg.cache_path)
            if not path.is_absolute():
                path = ROOT / path
        self._disk_path = path
        self._disk: dict[str, Any] = self._load_disk()

    @property
    def enabled(self) -> bool:
        """Feature flag only — coords may come from the browser."""
        return bool(self.cfg.enabled)

    @property
    def has_config_location(self) -> bool:
        return bool(self.cfg.place) or (
            self.cfg.latitude is not None and self.cfg.longitude is not None
        )

    def _load_disk(self) -> dict[str, Any]:
        try:
            if self._disk_path.exists():
                return json.loads(self._disk_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Weather disk cache unreadable: %s", exc)
        return {"entries": {}, "resolved": None}

    def _save_disk(self) -> None:
        try:
            self._disk_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._disk_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._disk, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._disk_path)
        except Exception as exc:
            logger.warning("Weather disk cache write failed: %s", exc)

    def _get_cached(self, key: str, now: float) -> dict[str, Any] | None:
        mem = self._mem.get(key)
        if mem is not None and (now - mem[0]) < self.cfg.cache_seconds:
            return mem[1]

        entries = self._disk.get("entries") or {}
        entry = entries.get(key)
        if not entry:
            return None
        cached_at = float(entry.get("cached_at") or 0)
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return None
        if (now - cached_at) < self.cfg.cache_seconds:
            self._mem[key] = (cached_at, payload)
            return payload
        return None

    def _get_stale(self, key: str) -> dict[str, Any] | None:
        mem = self._mem.get(key)
        if mem is not None:
            return mem[1]
        entries = self._disk.get("entries") or {}
        entry = entries.get(key)
        if entry and isinstance(entry.get("payload"), dict):
            return entry["payload"]
        return None

    def _store_cache(self, key: str, payload: dict[str, Any], now: float) -> None:
        self._mem[key] = (now, payload)
        entries = dict(self._disk.get("entries") or {})
        entries[key] = {"cached_at": now, "payload": payload}
        # Keep disk small
        if len(entries) > 8:
            oldest = sorted(entries.items(), key=lambda kv: kv[1].get("cached_at", 0))
            for drop_key, _ in oldest[: len(entries) - 8]:
                entries.pop(drop_key, None)
        self._disk["entries"] = entries
        self._save_disk()

    async def _resolve_config_location(
        self, client: httpx.AsyncClient
    ) -> dict[str, Any]:
        if self._resolved_config is not None:
            return self._resolved_config
        disk_resolved = self._disk.get("resolved")
        if isinstance(disk_resolved, dict) and disk_resolved.get("latitude") is not None:
            # Reuse if place/coords still match config
            if self.cfg.latitude is not None and self.cfg.longitude is not None:
                if (
                    abs(float(disk_resolved["latitude"]) - self.cfg.latitude) < 1e-4
                    and abs(float(disk_resolved["longitude"]) - self.cfg.longitude) < 1e-4
                ):
                    self._resolved_config = disk_resolved
                    return self._resolved_config
            if self.cfg.place and disk_resolved.get("place") == self.cfg.place:
                self._resolved_config = disk_resolved
                return self._resolved_config

        if self.cfg.latitude is not None and self.cfg.longitude is not None:
            self._resolved_config = {
                "name": self.cfg.place or "Configured",
                "place": self.cfg.place,
                "latitude": self.cfg.latitude,
                "longitude": self.cfg.longitude,
                "timezone": self.cfg.timezone,
                "source": "config",
            }
            self._disk["resolved"] = self._resolved_config
            self._save_disk()
            return self._resolved_config

        place = self.cfg.place
        if not place:
            raise RuntimeError("No weather location configured")

        resp = await client.get(
            GEOCODE_URL,
            params={"name": place, "count": 1, "language": "fr", "format": "json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
        if not results:
            raise RuntimeError(f"No geocoding result for place={place!r}")
        hit = results[0]
        self._resolved_config = {
            "name": hit.get("name") or place,
            "place": place,
            "latitude": float(hit["latitude"]),
            "longitude": float(hit["longitude"]),
            "timezone": hit.get("timezone") or self.cfg.timezone,
            "country": hit.get("country_code") or "",
            "admin1": hit.get("admin1") or "",
            "source": "config",
        }
        self._disk["resolved"] = self._resolved_config
        self._save_disk()
        logger.info(
            "Weather location resolved: %s (%.4f, %.4f) tz=%s",
            self._resolved_config["name"],
            self._resolved_config["latitude"],
            self._resolved_config["longitude"],
            self._resolved_config["timezone"],
        )
        return self._resolved_config

    async def _location_for_request(
        self,
        client: httpx.AsyncClient,
        *,
        latitude: float | None,
        longitude: float | None,
    ) -> dict[str, Any]:
        if latitude is not None and longitude is not None:
            return {
                "name": "Local",
                "latitude": float(latitude),
                "longitude": float(longitude),
                "timezone": "auto",
                "admin1": "",
                "country": "",
                "source": "browser",
            }
        return await self._resolve_config_location(client)

    def _make_cache_key(self, lat: float, lon: float) -> str:
        return _cache_key(
            lat, lon, self.cfg.forecast_hours, self.cfg.past_days
        )

    async def fetch_forecast(
        self,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "outdoor": [], "location": None}

        if (latitude is None) ^ (longitude is None):
            raise RuntimeError("latitude and longitude must be provided together")

        if latitude is None and longitude is None and not self.has_config_location:
            return {
                "enabled": False,
                "error": "No location — allow browser geolocation or set [weather] place",
                "outdoor": [],
                "location": None,
            }

        async with self._lock:
            # Resolve key: for config location we need coords first (may use cache)
            now = time.time()
            if latitude is not None and longitude is not None:
                key_lat, key_lon = float(latitude), float(longitude)
            else:
                # Peek disk/config without network if possible
                if self._resolved_config is not None:
                    loc_preview = self._resolved_config
                elif isinstance(self._disk.get("resolved"), dict):
                    loc_preview = self._disk["resolved"]
                else:
                    loc_preview = None

                if loc_preview and loc_preview.get("latitude") is not None:
                    key_lat = float(loc_preview["latitude"])
                    key_lon = float(loc_preview["longitude"])
                else:
                    key_lat = key_lon = None

            if key_lat is not None and key_lon is not None:
                key = self._make_cache_key(key_lat, key_lon)
                cached = self._get_cached(key, now)
                if cached is not None:
                    out = dict(cached)
                    out["cache_hit"] = True
                    return out
            else:
                key = None

            try:
                async with httpx.AsyncClient() as client:
                    loc = await self._location_for_request(
                        client, latitude=latitude, longitude=longitude
                    )
                    key = self._make_cache_key(
                        float(loc["latitude"]),
                        float(loc["longitude"]),
                    )
                    # Re-check cache after resolve
                    cached = self._get_cached(key, now)
                    if cached is not None:
                        out = dict(cached)
                        out["cache_hit"] = True
                        return out

                    days = max(1, min(16, (self.cfg.forecast_hours + 23) // 24))
                    past_days = self.cfg.past_days
                    tz_param = loc.get("timezone") or self.cfg.timezone or "auto"
                    resp = await client.get(
                        FORECAST_URL,
                        params={
                            "latitude": loc["latitude"],
                            "longitude": loc["longitude"],
                            "hourly": (
                                "temperature_2m,relative_humidity_2m,"
                                "shortwave_radiation,cloud_cover,"
                                "wind_speed_10m,wind_direction_10m"
                            ),
                            "windspeed_unit": "ms",
                            "forecast_days": days,
                            "past_days": past_days,
                            "timezone": tz_param,
                        },
                        timeout=20.0,
                    )
                    resp.raise_for_status()
                    payload = resp.json()
            except Exception as exc:
                if key:
                    stale = self._get_stale(key)
                    if stale is not None:
                        logger.warning(
                            "Weather fetch failed (%s) — serving stale cache", exc
                        )
                        out = dict(stale)
                        out["cache_hit"] = True
                        out["stale"] = True
                        return out
                raise

            hourly = payload.get("hourly") or {}
            times = hourly.get("time") or []
            temps = hourly.get("temperature_2m") or []
            hums = hourly.get("relative_humidity_2m") or []
            sw = hourly.get("shortwave_radiation") or []
            clouds = hourly.get("cloud_cover") or []
            wind_speeds = hourly.get("wind_speed_10m") or []
            wind_dirs = hourly.get("wind_direction_10m") or []
            tz_name = payload.get("timezone") or loc.get("timezone") or self.cfg.timezone

            outdoor: list[dict[str, Any]] = []
            for i, stamp in enumerate(times):
                if i >= len(temps) or i >= len(hums):
                    break
                if temps[i] is None or hums[i] is None:
                    continue
                point: dict[str, Any] = {
                    "ts": _parse_iso_local(stamp, tz_name),
                    "temperature_c": float(temps[i]),
                    "humidity": float(hums[i]),
                }
                if i < len(sw) and sw[i] is not None:
                    point["shortwave_radiation"] = float(sw[i])
                if i < len(clouds) and clouds[i] is not None:
                    point["cloud_cover"] = float(clouds[i])
                if i < len(wind_speeds) and wind_speeds[i] is not None:
                    point["wind_speed_ms"] = float(wind_speeds[i])
                if i < len(wind_dirs) and wind_dirs[i] is not None:
                    point["wind_direction_deg"] = float(wind_dirs[i])
                outdoor.append(point)

            result = {
                "enabled": True,
                "location": {
                    "name": loc.get("name") or "Local",
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                    "timezone": tz_name,
                    "admin1": loc.get("admin1") or "",
                    "country": loc.get("country") or "",
                    "source": loc.get("source") or "config",
                },
                "generated_at": now,
                "outdoor": outdoor,
                "cache_hit": False,
            }
            self._store_cache(key, result, now)
            logger.info(
                "Weather forecast fetched for %.2f,%.2f (%d hourly points, past_days=%d)",
                loc["latitude"],
                loc["longitude"],
                len(outdoor),
                past_days,
            )
            return result

    async def _project_network(
        self,
        db: Database,
        devices: list[dict[str, Any]],
        forecast_outdoor: list[dict[str, Any]],
        *,
        now: float,
        until: float,
    ) -> dict[str, dict[str, Any]] | None:
        """Multi-room RC when apartment layout + enough mapped sensors."""
        layout = self.apartment
        if not layout.enabled:
            return None

        # room_id → device (prefer interior with a reading)
        by_room: dict[str, dict[str, Any]] = {}
        for device in devices:
            zone = (device.get("zone") or "").strip().lower()
            if zone == "exterior":
                continue
            room = (device.get("room") or "").strip().lower()
            if room not in layout.rooms:
                continue
            temp = device.get("temperature_c")
            hum = device.get("humidity")
            ts = device.get("last_reading_ts") or device.get("last_seen")
            if temp is None or hum is None or ts is None:
                continue
            # Keep first device per room
            if room not in by_room:
                by_room[room] = device

        if not layout.can_network_project(set(by_room.keys())):
            return None

        future_outdoor = [
            p for p in forecast_outdoor if p["ts"] >= now and p["ts"] <= until
        ]
        if not future_outdoor:
            return None

        measured = {
            room: float(dev["temperature_c"]) for room, dev in by_room.items()
        }
        # Earliest last_ts among measured rooms as sim start
        ts0 = min(
            float(dev.get("last_reading_ts") or dev.get("last_seen") or now)
            for dev in by_room.values()
        )

        try:
            series = simulate_network(
                layout, measured, future_outdoor, ts0=ts0
            )
        except Exception as exc:
            logger.warning("Apartment network simulation failed: %s", exc)
            return None

        projections: dict[str, dict[str, Any]] = {}
        for room, device in by_room.items():
            addr = str(device.get("address") or "").upper()
            temps = series.get(room) or []
            if len(temps) != len(future_outdoor):
                continue
            last_hum = float(device["humidity"])
            last_ts = float(
                device.get("last_reading_ts") or device.get("last_seen") or now
            )
            outdoor_now = _nearest(forecast_outdoor, last_ts)
            if outdoor_now is None:
                outdoor_now = _nearest(forecast_outdoor, now)
            if outdoor_now is None:
                continue
            bias_hum = last_hum - float(outdoor_now["humidity"])
            instant_bias = float(device["temperature_c"]) - float(
                outdoor_now["temperature_c"]
            )

            bias_temp = instant_bias
            if layout.rooms[room].faces_exterior:
                calib_since = now - self.cfg.calib_hours * 3600.0
                history = await db.history(addr, self.cfg.calib_hours)
                pairs = _align_hourly(
                    forecast_outdoor,
                    history,
                    since=calib_since,
                    until=now,
                )
                if len(pairs) >= 3:
                    bias_temp = _median(
                        [t_int - t_ext for _, t_int, t_ext in pairs]
                    )

            points: list[dict[str, Any]] = []
            for p, temp in zip(future_outdoor, temps):
                points.append(
                    {
                        "ts": p["ts"],
                        "temperature_c": round(temp, 2),
                        "humidity": round(
                            max(0.0, min(100.0, float(p["humidity"]) + bias_hum)),
                            2,
                        ),
                    }
                )
            temp_vals = [p["temperature_c"] for p in points]
            hum_vals = [p["humidity"] for p in points]
            projections[addr] = {
                "name": device.get("name") or addr,
                "model": "network",
                "room": room,
                "tau_hours": 0.0,
                "bias_temp": round(bias_temp, 2),
                "bias_humidity": round(bias_hum, 2),
                "points": points,
                "summary": {
                    "temp_min": min(temp_vals),
                    "temp_max": max(temp_vals),
                    "humidity_min": min(hum_vals),
                    "humidity_max": max(hum_vals),
                },
            }

        return projections if projections else None

    async def _project_device(
        self,
        db: Database,
        device: dict[str, Any],
        forecast_outdoor: list[dict[str, Any]],
        *,
        now: float,
        until: float,
    ) -> dict[str, Any] | None:
        addr = str(device.get("address") or "").upper()
        last_ts = device.get("last_reading_ts") or device.get("last_seen")
        last_temp = device.get("temperature_c")
        last_hum = device.get("humidity")
        if last_ts is None or last_temp is None or last_hum is None:
            return None

        outdoor_now = _nearest(forecast_outdoor, float(last_ts))
        if outdoor_now is None:
            outdoor_now = _nearest(forecast_outdoor, now)
        if outdoor_now is None:
            return None

        instant_bias_temp = float(last_temp) - float(outdoor_now["temperature_c"])
        bias_hum = float(last_hum) - float(outdoor_now["humidity"])

        future_outdoor = [
            p
            for p in forecast_outdoor
            if p["ts"] >= now and p["ts"] <= until
        ]
        if not future_outdoor:
            return None

        zone = (device.get("zone") or "").strip().lower()
        model = "offset"
        bias_temp = instant_bias_temp
        tau_hours = 0.0

        if zone == "exterior":
            # Fast tracking of outdoor air; Δ from recent median when possible.
            calib_since = now - self.cfg.calib_hours * 3600.0
            history = await db.history(addr, self.cfg.calib_hours)
            pairs = _align_hourly(
                forecast_outdoor,
                history,
                since=calib_since,
                until=now,
            )
            if len(pairs) >= 3:
                bias_temp = _median([t_int - t_ext for _, t_int, t_ext in pairs])
            else:
                bias_temp = instant_bias_temp
            model = "rc"
            tau_hours = _EXTERIOR_TAU_HOURS
            temps = simulate_rc_temp(
                future_outdoor,
                t0=float(last_temp),
                ts0=float(last_ts),
                delta=bias_temp,
                tau_hours=tau_hours,
            )
        else:
            calib_since = now - self.cfg.calib_hours * 3600.0
            history = await db.history(addr, self.cfg.calib_hours)
            pairs = _align_hourly(
                forecast_outdoor,
                history,
                since=calib_since,
                until=now,
            )
            model, fitted_delta, fitted_tau = fit_rc(
                pairs,
                tau_min_hours=self.cfg.tau_min_hours,
                tau_max_hours=self.cfg.tau_max_hours,
                tau_default_hours=self.cfg.tau_default_hours,
            )
            if model == "rc":
                bias_temp = fitted_delta
                tau_hours = fitted_tau
                temps = simulate_rc_temp(
                    future_outdoor,
                    t0=float(last_temp),
                    ts0=float(last_ts),
                    delta=bias_temp,
                    tau_hours=tau_hours,
                )
            else:
                # Instant equilibrium (legacy offset).
                bias_temp = instant_bias_temp
                tau_hours = 0.0
                temps = [
                    float(p["temperature_c"]) + bias_temp for p in future_outdoor
                ]

        points: list[dict[str, Any]] = []
        for p, temp in zip(future_outdoor, temps):
            points.append(
                {
                    "ts": p["ts"],
                    "temperature_c": round(temp, 2),
                    "humidity": round(
                        max(0.0, min(100.0, float(p["humidity"]) + bias_hum)),
                        2,
                    ),
                }
            )

        temp_vals = [p["temperature_c"] for p in points]
        hum_vals = [p["humidity"] for p in points]
        return {
            "name": device.get("name") or addr,
            "model": model,
            "tau_hours": round(tau_hours, 2),
            "bias_temp": round(bias_temp, 2),
            "bias_humidity": round(bias_hum, 2),
            "points": points,
            "summary": {
                "temp_min": min(temp_vals),
                "temp_max": max(temp_vals),
                "humidity_min": min(hum_vals),
                "humidity_max": max(hum_vals),
            },
        }

    async def build_response(
        self,
        db: Database,
        *,
        hours: float = 24.0,
        addresses: list[str] | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "hours": hours,
                "location": None,
                "outdoor": [],
                "projections": {},
            }

        try:
            forecast = await self.fetch_forecast(
                latitude=latitude, longitude=longitude
            )
        except Exception as exc:
            logger.warning("Weather forecast failed: %s", exc)
            return {
                "enabled": False,
                "error": str(exc),
                "hours": hours,
                "location": None,
                "outdoor": [],
                "projections": {},
            }

        if not forecast.get("enabled"):
            return {
                "enabled": False,
                "error": forecast.get("error"),
                "hours": hours,
                "location": None,
                "outdoor": [],
                "projections": {},
            }

        now = time.time()
        since = now - hours * 3600.0
        until = now + hours * 3600.0
        outdoor = [
            p for p in forecast["outdoor"] if since <= p["ts"] <= until
        ]

        projections: dict[str, Any] = {}
        devices: list[dict[str, Any]] = []
        for address in addresses or []:
            addr = address.upper()
            device = await db.get_device(addr)
            if device is None:
                continue
            devices.append(device)

        network_proj = await self._project_network(
            db,
            devices,
            forecast["outdoor"],
            now=now,
            until=until,
        )
        covered: set[str] = set()
        if network_proj:
            projections.update(network_proj)
            covered = set(network_proj.keys())

        for device in devices:
            addr = str(device.get("address") or "").upper()
            if addr in covered:
                continue
            proj = await self._project_device(
                db,
                device,
                forecast["outdoor"],
                now=now,
                until=until,
            )
            if proj is not None:
                projections[addr] = proj

        apt_meta = self.apartment.summary() if self.apartment.enabled else {
            "enabled": False
        }

        return {
            "enabled": True,
            "hours": hours,
            "location": forecast.get("location"),
            "generated_at": forecast.get("generated_at"),
            "cache_hit": bool(forecast.get("cache_hit")),
            "stale": bool(forecast.get("stale")),
            "outdoor": outdoor,
            "projections": projections,
            "apartment": apt_meta,
        }


def _nearest(
    points: list[dict[str, Any]],
    ts: float,
) -> dict[str, Any] | None:
    if not points:
        return None
    return min(points, key=lambda p: abs(float(p["ts"]) - ts))
