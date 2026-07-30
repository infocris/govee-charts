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
from govee_charts.federation import PeerPublisher
from govee_charts.scanner import GoveeScanner, discover_once
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
        "cache_path": "data/weather_cache.json",
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

    weather_cfg = WeatherConfig.from_dict(cfg.get("weather"))
    weather = WeatherService(weather_cfg)
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
        if scan_task is not None:
            try:
                await asyncio.wait_for(scan_task, timeout=15.0)
            except asyncio.TimeoutError:
                logging.warning("BLE scanner stop timed out — cancelling")
                scan_task.cancel()
                try:
                    await scan_task
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
