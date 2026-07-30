"""Open-Meteo hourly forecast client and sensor projections."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from govee_charts.db import Database

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = ROOT / "data" / "weather_cache.json"


@dataclass(frozen=True)
class WeatherConfig:
    enabled: bool = False
    place: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "Europe/Paris"
    cache_seconds: float = 1800.0
    forecast_hours: int = 48
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
            cache_path=str(raw.get("cache_path") or "data/weather_cache.json"),
        )


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


def _cache_key(lat: float, lon: float, forecast_hours: int) -> str:
    # ~1 km grid — avoids cache misses from tiny GPS jitter
    return f"{lat:.2f},{lon:.2f}:{forecast_hours}"


class WeatherService:
    def __init__(self, cfg: WeatherConfig, cache_path: Path | None = None) -> None:
        self.cfg = cfg
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
                loc_preview = {
                    "name": "Local",
                    "latitude": key_lat,
                    "longitude": key_lon,
                    "source": "browser",
                }
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
                key = _cache_key(key_lat, key_lon, self.cfg.forecast_hours)
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
                    key = _cache_key(
                        float(loc["latitude"]),
                        float(loc["longitude"]),
                        self.cfg.forecast_hours,
                    )
                    # Re-check cache after resolve
                    cached = self._get_cached(key, now)
                    if cached is not None:
                        out = dict(cached)
                        out["cache_hit"] = True
                        return out

                    days = max(1, min(16, (self.cfg.forecast_hours + 23) // 24))
                    tz_param = loc.get("timezone") or self.cfg.timezone or "auto"
                    resp = await client.get(
                        FORECAST_URL,
                        params={
                            "latitude": loc["latitude"],
                            "longitude": loc["longitude"],
                            "hourly": "temperature_2m,relative_humidity_2m",
                            "forecast_days": days,
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
            tz_name = payload.get("timezone") or loc.get("timezone") or self.cfg.timezone

            outdoor: list[dict[str, Any]] = []
            for i, stamp in enumerate(times):
                if i >= len(temps) or i >= len(hums):
                    break
                if temps[i] is None or hums[i] is None:
                    continue
                outdoor.append(
                    {
                        "ts": _parse_iso_local(stamp, tz_name),
                        "temperature_c": float(temps[i]),
                        "humidity": float(hums[i]),
                    }
                )

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
                "Weather forecast fetched for %.2f,%.2f (%d hourly points)",
                loc["latitude"],
                loc["longitude"],
                len(outdoor),
            )
            return result

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
        for address in addresses or []:
            addr = address.upper()
            device = await db.get_device(addr)
            if device is None:
                continue
            last_ts = device.get("last_reading_ts") or device.get("last_seen")
            last_temp = device.get("temperature_c")
            last_hum = device.get("humidity")
            if last_ts is None or last_temp is None or last_hum is None:
                continue

            outdoor_now = _nearest(forecast["outdoor"], float(last_ts))
            if outdoor_now is None:
                outdoor_now = _nearest(forecast["outdoor"], now)
            if outdoor_now is None:
                continue

            bias_temp = float(last_temp) - float(outdoor_now["temperature_c"])
            bias_hum = float(last_hum) - float(outdoor_now["humidity"])

            points: list[dict[str, Any]] = []
            for p in forecast["outdoor"]:
                if p["ts"] < now:
                    continue
                if p["ts"] > until:
                    break
                points.append(
                    {
                        "ts": p["ts"],
                        "temperature_c": round(
                            float(p["temperature_c"]) + bias_temp, 2
                        ),
                        "humidity": round(
                            max(0.0, min(100.0, float(p["humidity"]) + bias_hum)),
                            2,
                        ),
                    }
                )

            if not points:
                continue

            temps = [p["temperature_c"] for p in points]
            hums = [p["humidity"] for p in points]
            projections[addr] = {
                "name": device.get("name") or addr,
                "bias_temp": round(bias_temp, 2),
                "bias_humidity": round(bias_hum, 2),
                "points": points,
                "summary": {
                    "temp_min": min(temps),
                    "temp_max": max(temps),
                    "humidity_min": min(hums),
                    "humidity_max": max(hums),
                },
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
        }


def _nearest(
    points: list[dict[str, Any]],
    ts: float,
) -> dict[str, Any] | None:
    if not points:
        return None
    return min(points, key=lambda p: abs(float(p["ts"]) - ts))
