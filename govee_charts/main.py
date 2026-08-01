"""Entry point: BLE collector + HTTP dashboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

import uvicorn

from govee_charts.address import build_suffix_map
from govee_charts.api import create_app
from govee_charts.db import Database
from govee_charts.doors import DoorMqttListener, DoorsConfig, import_ha_door_history
from govee_charts.federation import PeerPublisher
from govee_charts.hvac import HvacConfig, HvacHaPoller, import_ha_hvac_history
from govee_charts.scanner import GoveeScanner, discover_once
from govee_charts.apartment import (
    ApartmentLayout,
    default_apartment_dict,
    load_overrides,
)
from govee_charts.sslutil import resolve_ssl_files
from govee_charts.weather import WeatherConfig, WeatherService

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"

DEFAULTS: dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
        "ssl": False,
        "ssl_port": 8081,
        "ssl_auto_generate": True,
        "certfile": "data/ssl/cert.pem",
        "keyfile": "data/ssl/key.pem",
    },
    "scanner": {
        "enabled": True,
        "active": True,
        "sample_interval": 60.0,
        "retention_days": 30,
        "log_file": "govee-charts.log",
        # Empty = default adapter. Example: ["hci0", "hci1"]
        "adapters": [],
    },
    "database": {"path": "data/readings.db"},
    "federation": {
        "node_id": "",
        "token": "",
        "peers": [],
    },
    "weather": {
        "enabled": False,
        "place": "",
        "latitude": None,
        "longitude": None,
        "timezone": "Europe/Paris",
        "cache_seconds": 1800,
        "forecast_hours": 48,
        "calib_hours": 48,
        "tau_min_hours": 0.5,
        "tau_max_hours": 24,
        "tau_default_hours": 3,
        "cache_path": "data/weather_cache.json",
    },
    "apartment": default_apartment_dict(),
    "doors": {
        "enabled": False,
        "mqtt_host": "127.0.0.1",
        "mqtt_port": 1883,
        "mqtt_username": "hass",
        "mqtt_password": "",
        "mqtt_password_file": "",
        "discovery_prefix": "homeassistant",
        "ring_topic": "ring/#",
        "retention_days": 365,
        "ha_db_path": "",
        "ha_device_registry": "",
        "names": {},
    },
    "hvac": {
        "enabled": False,
        "ha_url": "http://127.0.0.1:8123",
        "ha_token": "",
        "ha_token_file": "",
        "climate_entity": "climate.medion_smart_mobile_camping_ac_p502_md37735",
        "power_entity": "sensor.infocris_consommation_temps_reel",
        "poll_seconds": 15,
        "retention_days": 365,
        "ha_db_path": "",
    },
    "labels": {},
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as fh:
            cfg = deep_merge(cfg, tomllib.load(fh))
    # Normalize labels keys to uppercase strings
    labels_raw = cfg.get("labels") or {}
    cfg["labels"] = {str(k).upper(): str(v) for k, v in labels_raw.items()}
    adapters_raw = cfg.get("scanner", {}).get("adapters") or []
    if isinstance(adapters_raw, str):
        adapters_raw = [adapters_raw]
    cfg["scanner"]["adapters"] = [
        str(a).strip() for a in adapters_raw if str(a).strip()
    ]
    peers_raw = cfg.get("federation", {}).get("peers") or []
    if isinstance(peers_raw, str):
        peers_raw = [peers_raw]
    cfg["federation"]["peers"] = [
        str(p).strip().rstrip("/") for p in peers_raw if str(p).strip()
    ]
    node_id = str(cfg["federation"].get("node_id") or "").strip()
    if not node_id:
        node_id = socket.gethostname() or "local"
    cfg["federation"]["node_id"] = node_id
    cfg["federation"]["token"] = str(cfg["federation"].get("token") or "").strip()
    return cfg


def setup_logging(log_file: str) -> None:
    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    logging.getLogger("bleak").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def resolve_db_path(cfg: dict[str, Any]) -> Path:
    path = Path(cfg["database"]["path"])
    if not path.is_absolute():
        path = ROOT / path
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Govee Charts — BLE collector + web UI")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Scan BLE for Govee sensors (30s) then exit",
    )
    parser.add_argument(
        "--no-scanner",
        action="store_true",
        help="Start web UI only (disable local BLE scanning)",
    )
    return parser.parse_args()


async def run_server(cfg: dict[str, Any], *, enable_scanner: bool = True) -> None:
    db = Database(resolve_db_path(cfg))
    await db.connect()
    seeded = await db.seed_categories_from_names()
    if seeded:
        logging.info("Inferred categories for %d device(s) from labels", seeded)
    door_meta = await db.backfill_door_sensors()
    if door_meta:
        logging.info("Created metadata for %d door sensor(s)", door_meta)

    suffix_map = build_suffix_map(cfg["labels"])
    suffix_map.update(await db.suffix_map_from_devices())

    fed = cfg["federation"]
    publisher = PeerPublisher(
        fed["peers"],
        node_id=fed["node_id"],
        token=fed["token"] or None,
    )
    await publisher.start()

    stop_event = asyncio.Event()
    scan_task: asyncio.Task[None] | None = None
    door_task: asyncio.Task[None] | None = None
    hvac_task: asyncio.Task[None] | None = None
    scanner_enabled = enable_scanner and bool(cfg["scanner"].get("enabled", True))
    if scanner_enabled:
        scanner = GoveeScanner(
            db,
            labels=cfg["labels"],
            sample_interval=float(cfg["scanner"]["sample_interval"]),
            active=bool(cfg["scanner"]["active"]),
            retention_days=float(cfg["scanner"]["retention_days"]),
            adapters=cfg["scanner"]["adapters"],
            publisher=publisher,
            node_id=fed["node_id"],
            suffix_map=suffix_map,
        )
        scan_task = asyncio.create_task(scanner.run(stop_event), name="ble-scanner")
    else:
        logging.info("BLE scanner disabled (scanner.enabled=false or --no-scanner)")

    doors_cfg = DoorsConfig.from_dict(cfg.get("doors"))
    if doors_cfg.enabled:
        if doors_cfg.ha_db_path:
            try:
                n_imp = await import_ha_door_history(db, doors_cfg.ha_db_path)
                if n_imp:
                    logging.info("Imported %d door event(s) from Home Assistant", n_imp)
            except Exception:
                logging.exception("Failed to import Home Assistant door history")
        pruned = await db.prune_door_events(doors_cfg.retention_days)
        if pruned:
            logging.info("Pruned %d old door event(s)", pruned)
        listener = DoorMqttListener(db, doors_cfg)
        door_task = asyncio.create_task(listener.run(stop_event), name="door-mqtt")
        logging.info(
            "Door historization enabled (MQTT %s:%d)",
            doors_cfg.mqtt_host,
            doors_cfg.mqtt_port,
        )
    else:
        logging.info("Door historization disabled (set doors.enabled=true)")

    hvac_cfg = HvacConfig.from_dict(cfg.get("hvac"))
    if hvac_cfg.enabled:
        if hvac_cfg.ha_db_path:
            try:
                n_hvac, n_power = await import_ha_hvac_history(db, hvac_cfg)
                if n_hvac or n_power:
                    logging.info(
                        "Imported %d HVAC event(s) and %d power sample(s) from Home Assistant",
                        n_hvac,
                        n_power,
                    )
            except Exception:
                logging.exception("Failed to import Home Assistant HVAC/power history")
        pruned_h = await db.prune_hvac_events(hvac_cfg.retention_days)
        pruned_p = await db.prune_power_samples(hvac_cfg.retention_days)
        if pruned_h:
            logging.info("Pruned %d old HVAC event(s)", pruned_h)
        if pruned_p:
            logging.info("Pruned %d old power sample(s)", pruned_p)
        poller = HvacHaPoller(db, hvac_cfg)
        hvac_task = asyncio.create_task(poller.run(stop_event), name="hvac-ha-poll")
        logging.info(
            "HVAC historization enabled (HA %s, poll %.0fs)",
            hvac_cfg.ha_url,
            hvac_cfg.poll_seconds,
        )
    else:
        logging.info("HVAC historization disabled (set hvac.enabled=true)")

    weather_cfg = WeatherConfig.from_dict(cfg.get("weather"))
    apt_raw = dict(cfg.get("apartment") or {})
    if not apt_raw.get("timezone") and cfg.get("weather", {}).get("timezone"):
        apt_raw["timezone"] = cfg["weather"]["timezone"]
    apartment = ApartmentLayout.from_dict(apt_raw)
    n_ovr = apartment.apply_overrides(load_overrides())
    if n_ovr:
        logging.info("Applied façade overrides for %d room(s)", n_ovr)
    weather = WeatherService(weather_cfg, apartment=apartment)
    if weather.enabled:
        if weather.has_config_location:
            loc = weather_cfg.place or (
                f"{weather_cfg.latitude},{weather_cfg.longitude}"
            )
            logging.info(
                "Weather forecast enabled (config=%s, browser geolocation OK)",
                loc,
            )
        else:
            logging.info(
                "Weather forecast enabled (browser geolocation; optional [weather] place fallback)"
            )
        if apartment.enabled:
            logging.info(
                "Apartment network enabled (%d rooms, floor %d/%d)",
                len(apartment.rooms),
                apartment.floor,
                apartment.floors_total,
            )
    else:
        logging.info("Weather forecast disabled (set weather.enabled=true)")

    servers: list[uvicorn.Server] = []

    def request_restart() -> None:
        logging.warning("Stopping HTTP listeners for restart")
        for server in servers:
            server.should_exit = True

    app = create_app(
        db,
        labels=cfg["labels"],
        federation_token=fed["token"] or None,
        node_id=fed["node_id"],
        peers=fed["peers"],
        suffix_map=suffix_map,
        weather=weather,
        on_restart=request_restart,
    )

    host = str(cfg["server"]["host"])
    port = int(cfg["server"]["port"])
    ssl_port = int(cfg["server"].get("ssl_port") or 8081)
    certfile, keyfile = resolve_ssl_files(cfg["server"])
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host

    http_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    http_server = uvicorn.Server(http_config)
    servers.append(http_server)

    logging.info(
        "Web UI on http://%s:%d (node_id=%s)",
        display_host,
        port,
        fed["node_id"],
    )

    if certfile and keyfile:
        https_config = uvicorn.Config(
            app,
            host=host,
            port=ssl_port,
            log_level="info",
            access_log=False,
            ssl_certfile=str(certfile),
            ssl_keyfile=str(keyfile),
        )
        servers.append(uvicorn.Server(https_config))
        logging.info(
            "Web UI on https://%s:%d (TLS self-signed)",
            display_host,
            ssl_port,
        )
        logging.info(
            "Accept the browser certificate warning once — needed for geolocation on LAN"
        )

    async def _serve(server: uvicorn.Server) -> None:
        try:
            await server.serve()
        finally:
            # If one listener stops, tear down the other(s)
            for other in servers:
                other.should_exit = True

    try:
        await asyncio.gather(*(_serve(s) for s in servers))
    finally:
        stop_event.set()
        for task, label in (
            (scan_task, "BLE scanner"),
            (door_task, "Door MQTT"),
            (hvac_task, "HVAC HA poll"),
        ):
            if task is None:
                continue
            try:
                await asyncio.wait_for(task, timeout=15.0)
            except asyncio.TimeoutError:
                logging.warning("%s stop timed out — cancelling", label)
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        await publisher.stop()
        await db.close()


async def amain() -> None:
    args = parse_args()
    cfg = load_config()
    setup_logging(str(cfg["scanner"]["log_file"]))

    if args.discover:
        await discover_once(
            duration=30.0,
            active=bool(cfg["scanner"]["active"]),
            adapters=cfg["scanner"]["adapters"],
            suffix_map=build_suffix_map(cfg["labels"]),
        )
        return

    await run_server(cfg, enable_scanner=not args.no_scanner)


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print()
        logging.info("Stopped")


if __name__ == "__main__":
    main()
