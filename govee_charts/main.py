"""Entry point: BLE collector + HTTP dashboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
import tomllib
from pathlib import Path
from typing import Any

import uvicorn

from govee_charts.api import create_app
from govee_charts.db import Database
from govee_charts.federation import PeerPublisher
from govee_charts.scanner import GoveeScanner, discover_once

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"

DEFAULTS: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8080},
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
    return parser.parse_args()


async def run_server(cfg: dict[str, Any]) -> None:
    db = Database(resolve_db_path(cfg))
    await db.connect()

    fed = cfg["federation"]
    publisher = PeerPublisher(
        fed["peers"],
        node_id=fed["node_id"],
        token=fed["token"] or None,
    )
    await publisher.start()

    stop_event = asyncio.Event()
    scan_task: asyncio.Task[None] | None = None
    if bool(cfg["scanner"].get("enabled", True)):
        scanner = GoveeScanner(
            db,
            labels=cfg["labels"],
            sample_interval=float(cfg["scanner"]["sample_interval"]),
            active=bool(cfg["scanner"]["active"]),
            retention_days=float(cfg["scanner"]["retention_days"]),
            adapters=cfg["scanner"]["adapters"],
            publisher=publisher,
            node_id=fed["node_id"],
        )
        scan_task = asyncio.create_task(scanner.run(stop_event), name="ble-scanner")
    else:
        logging.info("BLE scanner disabled (scanner.enabled=false)")

    app = create_app(
        db,
        labels=cfg["labels"],
        federation_token=fed["token"] or None,
        node_id=fed["node_id"],
    )

    host = str(cfg["server"]["host"])
    port = int(cfg["server"]["port"])
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    logging.info(
        "Web UI on http://%s:%d (node_id=%s)",
        host,
        port,
        fed["node_id"],
    )

    try:
        await server.serve()
    finally:
        stop_event.set()
        if scan_task is not None:
            await scan_task
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
        )
        return

    await run_server(cfg)


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print()
        logging.info("Stopped")


if __name__ == "__main__":
    main()
