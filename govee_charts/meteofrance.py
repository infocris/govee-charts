"""Météo-France public observation API (station measurements)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://portail-api.meteofrance.fr/token"
API_BASE = "https://public-api.meteofrance.fr/public/DPObs/v1"
# Observation APIs retain roughly the last day.
MAX_HISTORY_HOURS = 24


@dataclass(frozen=True)
class MeteoFranceStation:
    id: str
    name: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MeteoFranceStation | None:
        raw = raw or {}
        sid = str(raw.get("id") or raw.get("station_id") or "").strip()
        if not sid:
            return None
        name = str(raw.get("name") or raw.get("station_name") or "").strip()
        return cls(id=sid, name=name)


@dataclass(frozen=True)
class MeteoFranceConfig:
    enabled: bool = False
    station_id: str = ""
    station_name: str = ""
    stations: tuple[MeteoFranceStation, ...] = ()
    basic_auth_file: str = "data/secrets/meteofrance_basic.b64"
    cache_seconds: float = 300.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MeteoFranceConfig:
        raw = raw or {}
        stations: list[MeteoFranceStation] = []
        seen: set[str] = set()
        raw_stations = raw.get("stations")
        if isinstance(raw_stations, list):
            for item in raw_stations:
                if not isinstance(item, dict):
                    continue
                st = MeteoFranceStation.from_dict(item)
                if st and st.id not in seen:
                    seen.add(st.id)
                    stations.append(st)
        # Legacy single-station keys
        legacy_id = str(raw.get("station_id") or "").strip()
        legacy_name = str(raw.get("station_name") or "").strip()
        if legacy_id and legacy_id not in seen:
            stations.insert(0, MeteoFranceStation(id=legacy_id, name=legacy_name))
            seen.add(legacy_id)
        primary = stations[0] if stations else None
        return cls(
            enabled=bool(raw.get("enabled", False)),
            station_id=(primary.id if primary else legacy_id),
            station_name=(primary.name if primary else legacy_name),
            stations=tuple(stations),
            basic_auth_file=str(
                raw.get("basic_auth_file") or "data/secrets/meteofrance_basic.b64"
            ).strip(),
            cache_seconds=float(raw.get("cache_seconds") or 300.0),
        )

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.stations and self.basic_auth_file)

    @property
    def station_list(self) -> tuple[MeteoFranceStation, ...]:
        return self.stations


def _kelvin_to_c(value: Any) -> float | None:
    try:
        k = float(value)
    except (TypeError, ValueError):
        return None
    if k < 100:  # already Celsius (defensive)
        return round(k, 2)
    return round(k - 273.15, 2)


def _parse_iso_utc(value: str | None) -> float | None:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _normalize_obs(row: dict[str, Any], *, station_id: str, station_name: str) -> dict[str, Any] | None:
    ts = (
        _parse_iso_utc(row.get("validity_time"))
        or _parse_iso_utc(row.get("reference_time"))
        or _parse_iso_utc(row.get("insert_time"))
    )
    if ts is None:
        return None
    t_c = _kelvin_to_c(row.get("t"))
    u = row.get("u")
    humidity = None
    try:
        if u is not None:
            humidity = round(float(u), 1)
    except (TypeError, ValueError):
        humidity = None
    wind_ms = None
    try:
        if row.get("ff") is not None:
            wind_ms = round(float(row["ff"]), 2)
    except (TypeError, ValueError):
        wind_ms = None
    return {
        "ts": float(ts),
        "temperature_c": t_c,
        "humidity": humidity,
        "wind_speed_ms": wind_ms,
        "station_id": station_id,
        "station_name": station_name or station_id,
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "source": "meteofrance",
    }


def _empty_station(station: MeteoFranceStation, *, error: str | None = None) -> dict[str, Any]:
    return {
        "enabled": True,
        "error": error,
        "station_id": station.id,
        "station_name": station.name or station.id,
        "points": [],
        "latest": None,
    }


class MeteoFranceClient:
    def __init__(self, cfg: MeteoFranceConfig, *, root: Path | None = None) -> None:
        self.cfg = cfg
        self._root = root or Path.cwd()
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._token_expires_at = 0.0
        # station_id -> (fetched_at, payload)
        self._series_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _auth_header_basic(self) -> str:
        path = Path(self.cfg.basic_auth_file)
        if not path.is_absolute():
            path = self._root / path
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            raise RuntimeError(f"Empty Météo-France credentials file: {path}")
        # Accept either bare base64 or "Basic xxx"
        if raw.lower().startswith("basic "):
            return raw
        return f"Basic {raw}"

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": self._auth_header_basic()},
            timeout=20.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Météo-France token response missing access_token")
        expires = float(payload.get("expires_in") or 3600)
        self._token = str(token)
        self._token_expires_at = now + expires
        return self._token

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
    ) -> Any:
        token = await self._ensure_token(client)
        resp = await client.get(
            f"{API_BASE}{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        # Some endpoints return CSV even with format=json when Accept is ignored.
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" in ctype or resp.text.lstrip().startswith(("[", "{")):
            return resp.json()
        raise RuntimeError(f"Unexpected Météo-France content-type: {ctype}")

    def _trim_cached(
        self, cached: dict[str, Any], *, hours_n: int, now: float
    ) -> dict[str, Any]:
        since = now - hours_n * 3600.0
        out = dict(cached)
        pts = [p for p in (out.get("points") or []) if float(p["ts"]) >= since]
        out["points"] = pts
        out["hours"] = hours_n
        if pts:
            out["latest"] = max(pts, key=lambda p: float(p["ts"]))
        else:
            out["latest"] = None
        return out

    async def _fetch_one_series(
        self,
        client: httpx.AsyncClient,
        station: MeteoFranceStation,
        *,
        hours_n: int,
        now: float,
    ) -> dict[str, Any]:
        cached_entry = self._series_cache.get(station.id)
        if (
            cached_entry
            and (now - cached_entry[0]) < self.cfg.cache_seconds
            and int(cached_entry[1].get("hours") or 0) >= hours_n
        ):
            return self._trim_cached(cached_entry[1], hours_n=hours_n, now=now)

        points: list[dict[str, Any]] = []
        seen: set[int] = set()
        dates: list[str | None] = [None]
        for i in range(1, hours_n):
            ts = now - i * 3600.0
            dates.append(
                datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:00:00Z"
                )
            )
        name = station.name or station.id
        try:
            for date_iso in dates:
                params: dict[str, Any] = {
                    "id_station": station.id,
                    "format": "json",
                }
                if date_iso:
                    params["date"] = date_iso
                try:
                    data = await self._get_json(client, "/station/horaire", params)
                except Exception as exc:
                    logger.debug(
                        "Météo-France horaire skip %s %s: %s",
                        station.id,
                        date_iso,
                        exc,
                    )
                    continue
                rows = data if isinstance(data, list) else [data]
                if not rows:
                    continue
                obs = _normalize_obs(
                    rows[0],
                    station_id=station.id,
                    station_name=name,
                )
                if not obs or obs.get("temperature_c") is None:
                    continue
                bucket = int(float(obs["ts"]) // 3600)
                if bucket in seen:
                    continue
                seen.add(bucket)
                points.append(obs)
        except Exception as exc:
            logger.warning(
                "Météo-France station fetch failed (%s): %s", station.id, exc
            )
            return _empty_station(station, error=str(exc))

        points.sort(key=lambda p: float(p["ts"]))
        latest = points[-1] if points else None
        payload = {
            "enabled": True,
            "error": None,
            "station_id": station.id,
            "station_name": name,
            "hours": hours_n,
            "points": points,
            "latest": latest,
        }
        self._series_cache[station.id] = (now, payload)
        return payload

    async def fetch_horaire(
        self,
        *,
        date_iso: str | None = None,
        station_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.cfg.ready:
            return None
        station = None
        if station_id:
            station = next(
                (s for s in self.cfg.station_list if s.id == station_id), None
            )
        if station is None:
            station = self.cfg.station_list[0]
        params: dict[str, Any] = {
            "id_station": station.id,
            "format": "json",
        }
        if date_iso:
            params["date"] = date_iso
        async with httpx.AsyncClient() as client:
            data = await self._get_json(client, "/station/horaire", params)
        rows = data if isinstance(data, list) else [data]
        if not rows:
            return None
        return _normalize_obs(
            rows[0],
            station_id=station.id,
            station_name=station.name or station.id,
        )

    async def fetch_series(self, *, hours: float = 24.0) -> dict[str, Any]:
        """Hourly points for all configured stations (API retention ~24 h).

        Returns ``stations`` (list) and ``station`` (first / primary) for
        backward compatibility with older UI.
        """
        if not self.cfg.ready:
            return {
                "enabled": False,
                "points": [],
                "latest": None,
                "stations": [],
                "station": None,
            }

        hours_n = max(1, min(MAX_HISTORY_HOURS, int(round(float(hours)))))
        now = time.time()

        async with self._lock:
            async with httpx.AsyncClient() as client:
                series = await asyncio.gather(
                    *[
                        self._fetch_one_series(
                            client, st, hours_n=hours_n, now=now
                        )
                        for st in self.cfg.station_list
                    ]
                )

        stations = list(series)
        primary = stations[0] if stations else None
        payload: dict[str, Any] = {
            "enabled": True,
            "stations": stations,
            # Primary station flattened for older consumers.
            "station_id": (primary or {}).get("station_id"),
            "station_name": (primary or {}).get("station_name"),
            "hours": hours_n,
            "points": (primary or {}).get("points") or [],
            "latest": (primary or {}).get("latest"),
            "error": (primary or {}).get("error"),
        }
        return payload
