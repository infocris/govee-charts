"""Entry point: BLE collector + HTTP dashboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

import uvicorn

from govee_charts.address import build_suffix_map
from govee_charts.api import create_app
from govee_charts.backfill import BackfillConfig, BackfillService
from govee_charts.db import Database
from govee_charts.doors import DoorHaPoller, DoorMqttListener, DoorsConfig, import_ha_door_history
from govee_charts.federation import PeerPublisher
from govee_charts.ha_th import HaThConfig, HaThPoller
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
        # UI alert when no BLE ads for this long (seconds). 0 = disable alert.
        "alert_stale_after": 300.0,
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
        "meteofrance": {
            "enabled": False,
            "station_id": "",
            "station_name": "",
            "stations": [],
            "basic_auth_file": "data/secrets/meteofrance_basic.b64",
            "cache_seconds": 300,
        },
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
        "ha_url": "http://127.0.0.1:8123",
        "ha_token": "",
        "ha_token_file": "",
        "ha_poll_seconds": 10,
        "ha_entities": [],
    },
    "hvac": {
        "enabled": False,
        "ha_url": "http://127.0.0.1:8123",
        "ha_token": "",
        "ha_token_file": "",
        "climate_entity": "climate.medion_smart_mobile_camping_ac_p502_md37735",
        "room": "bedroom",
        "power_entity": "sensor.infocris_consommation_temps_reel",
        "energy_entity": "sensor.infocris_consommation_reseau",
        "water_heater_energy_entity": "sensor.compteur_intelligent_wifi_energie_totale",
        "water_heater_indoor_fraction": 0.30,
        "other_loads_indoor_fraction": 0.90,
        "ac_cop": 3.0,
        "ac_idle_floor_w": 150.0,
        "timezone": "Europe/Paris",
        "poll_seconds": 15.0,
        "retention_days": 365.0,
        "ha_db_path": "",
    },
    "ha_th": {
        "enabled": False,
        "ha_url": "http://127.0.0.1:8123",
        "ha_token": "",
        "ha_token_file": "",
        "poll_seconds": 60.0,
        "sample_interval": 60.0,
        "devices": [],
    },
    "backfill": {
        "enabled": True,
        "lookback_days": 20,
        "poll_seconds": 30,
        "max_job_minutes": 60,
        "min_rssi": -75,
        "seen_max_age_seconds": 600,
        "federation_share": True,
        "federation_pull": True,
        "rssi_prefer_margin_db": 3,
        "peer_signal_cache_seconds": 45,
        "rebuild_seconds": 900,
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
    parser.add_argument(
        "--mode",
        choices=("all", "ui", "workers"),
        default="all",
        help="Runtime mode: all (default), ui only, or workers only",
    )
    return parser.parse_args()


async def _init_runtime_db(
    cfg: dict[str, Any],
    *,
    seed_metadata: bool = True,
) -> tuple[Database, dict[str, str]]:
    db = Database(resolve_db_path(cfg))
    await db.connect()
    if seed_metadata:
        seeded = await db.seed_categories_from_names()
        if seeded:
            logging.info("Inferred categories for %d device(s) from labels", seeded)
        door_meta = await db.backfill_door_sensors()
        if door_meta:
            logging.info("Created metadata for %d door sensor(s)", door_meta)

    suffix_map = build_suffix_map(cfg["labels"])
    suffix_map.update(await db.suffix_map_from_devices())
    return db, suffix_map


async def _start_workers(
    cfg: dict[str, Any],
    db: Database,
    suffix_map: dict[str, str],
    *,
    enable_scanner: bool = True,
) -> dict[str, Any]:
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
    door_ha_task: asyncio.Task[None] | None = None
    hvac_task: asyncio.Task[None] | None = None
    ha_th_task: asyncio.Task[None] | None = None
    backfill_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None

    scanner_enabled = enable_scanner and bool(cfg["scanner"].get("enabled", True))
    scanner: GoveeScanner | None = None
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

    backfill_cfg = BackfillConfig.from_dict(cfg.get("backfill"))
    backfill: BackfillService | None = None
    peers_for_pull = [p for p in (fed.get("peers") or []) if str(p).strip()]
    federation_backfill_ok = bool(
        backfill_cfg.federation_pull and peers_for_pull
    )
    if backfill_cfg.enabled and (scanner_enabled or federation_backfill_ok):
        backfill = BackfillService(
            db,
            backfill_cfg,
            labels=cfg["labels"],
            node_id=fed["node_id"],
            publisher=publisher,
            scanner=scanner,
        )
        backfill_task = asyncio.create_task(
            backfill.run(stop_event), name="gatt-backfill"
        )
        if not scanner_enabled:
            logging.info(
                "History backfill started (federation-only; no local BLE scanner)"
            )
    elif backfill_cfg.enabled:
        logging.info(
            "History backfill skipped (needs local BLE scanner or "
            "federation peers with federation_pull)"
        )
    else:
        logging.info("GATT history backfill disabled (set backfill.enabled=true)")

    doors_cfg = DoorsConfig.from_dict(cfg.get("doors"))
    if doors_cfg.enabled:
        if doors_cfg.ha_db_path:
            try:
                n_imp = await import_ha_door_history(
                    db, doors_cfg.ha_db_path, names=doors_cfg.names
                )
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
        if doors_cfg.ha_entities:
            ha_poller = DoorHaPoller(db, doors_cfg)
            door_ha_task = asyncio.create_task(
                ha_poller.run(stop_event), name="door-ha-poll"
            )
            logging.info(
                "Door HA poll enabled (%d entit%s via %s)",
                len(doors_cfg.ha_entities),
                "y" if len(doors_cfg.ha_entities) == 1 else "ies",
                doors_cfg.ha_url,
            )
    else:
        logging.info("Door historization disabled (set doors.enabled=true)")

    hvac_cfg = HvacConfig.from_dict(cfg.get("hvac"))
    if hvac_cfg.enabled:
        if hvac_cfg.ha_db_path:
            try:
                n_hvac, n_power, n_energy = await import_ha_hvac_history(db, hvac_cfg)
                if n_hvac or n_power or n_energy:
                    logging.info(
                        "Imported %d HVAC event(s), %d power sample(s), %d energy sample(s) from Home Assistant",
                        n_hvac,
                        n_power,
                        n_energy,
                    )
            except Exception:
                logging.exception("Failed to import Home Assistant HVAC/power history")
        pruned_h = await db.prune_hvac_events(hvac_cfg.retention_days)
        pruned_p = await db.prune_power_samples(hvac_cfg.retention_days)
        pruned_e = await db.prune_energy_samples(hvac_cfg.retention_days)
        if pruned_h:
            logging.info("Pruned %d old HVAC event(s)", pruned_h)
        if pruned_p:
            logging.info("Pruned %d old power sample(s)", pruned_p)
        if pruned_e:
            logging.info("Pruned %d old energy sample(s)", pruned_e)
        poller = HvacHaPoller(db, hvac_cfg)
        hvac_task = asyncio.create_task(poller.run(stop_event), name="hvac-ha-poll")
        logging.info(
            "HVAC historization enabled (HA %s, poll %.0fs)",
            hvac_cfg.ha_url,
            hvac_cfg.poll_seconds,
        )
    else:
        logging.info("HVAC historization disabled (set hvac.enabled=true)")

    ha_th_cfg = HaThConfig.from_dict(cfg.get("ha_th"))
    if ha_th_cfg.ready:
        ha_th_poller = HaThPoller(db, ha_th_cfg, node_id=fed["node_id"])
        ha_th_task = asyncio.create_task(
            ha_th_poller.run(stop_event), name="ha-th-poll"
        )
        logging.info(
            "HA T/H poll enabled (%d device%s via %s)",
            len(ha_th_cfg.devices),
            "" if len(ha_th_cfg.devices) == 1 else "s",
            ha_th_cfg.ha_url,
        )
    elif ha_th_cfg.enabled:
        logging.warning(
            "HA T/H enabled but missing token or devices "
            "(set ha_th.ha_token_file and [[ha_th.devices]])"
        )
    else:
        logging.info("HA T/H poll disabled (set ha_th.enabled=true)")

    async def _heartbeat() -> None:
        while not stop_event.is_set():
            await db.touch_runtime_heartbeat("workers")
            await asyncio.sleep(2.0)

    await db.touch_runtime_heartbeat("workers")
    heartbeat_task = asyncio.create_task(_heartbeat(), name="workers-heartbeat")

    return {
        "stop_event": stop_event,
        "publisher": publisher,
        "scanner_task": scan_task,
        "door_task": door_task,
        "door_ha_task": door_ha_task,
        "hvac_task": hvac_task,
        "ha_th_task": ha_th_task,
        "backfill_task": backfill_task,
        "heartbeat_task": heartbeat_task,
        "backfill": backfill,
        "hvac_cfg": hvac_cfg,
    }


async def _stop_workers(
    runtime: dict[str, Any],
    *,
    grace_seconds: float = 3.0,
) -> None:
    """Signal workers to stop, wait briefly, then cancel stragglers in parallel."""
    stop_event: asyncio.Event = runtime["stop_event"]
    stop_event.set()
    labeled = [
        (runtime.get("scanner_task"), "BLE scanner"),
        (runtime.get("door_task"), "Door MQTT"),
        (runtime.get("door_ha_task"), "Door HA poll"),
        (runtime.get("hvac_task"), "HVAC HA poll"),
        (runtime.get("ha_th_task"), "HA T/H poll"),
        (runtime.get("backfill_task"), "GATT backfill"),
        (runtime.get("heartbeat_task"), "Workers heartbeat"),
    ]
    pending_pairs = [
        (task, label)
        for task, label in labeled
        if task is not None and not task.done()
    ]
    if pending_pairs:
        tasks = [task for task, _ in pending_pairs]
        _done, pending = await asyncio.wait(tasks, timeout=grace_seconds)
        timed_out = set(pending)
        for task, label in pending_pairs:
            if task in timed_out:
                logging.warning("%s stop timed out — cancelling", label)
                task.cancel()
        if timed_out:
            await asyncio.wait(timed_out, timeout=2.0)
    publisher: PeerPublisher = runtime["publisher"]
    await publisher.stop()


class _ShutdownServer(uvicorn.Server):
    """uvicorn.Server that also wakes local workers on the first Ctrl+C."""

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        on_signal: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(config)
        self._on_signal = on_signal

    def handle_exit(self, sig: int, frame: Any) -> None:
        if self._on_signal is not None:
            try:
                self._on_signal()
            except Exception:
                logging.exception("Shutdown signal hook failed")
        super().handle_exit(sig, frame)


def _install_stop_signals(stop_event: asyncio.Event) -> None:
    """Make SIGINT/SIGTERM set stop_event (workers-only mode)."""
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except (NotImplementedError, RuntimeError):
            # Windows / embedded loops: KeyboardInterrupt still unwinds finally.
            pass


def _build_weather(cfg: dict[str, Any]) -> WeatherService:
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
        mf = weather_cfg.meteofrance
        if mf.ready:
            names = ", ".join(
                f"{st.name or st.id} ({st.id})" for st in mf.station_list
            )
            logging.info("Météo-France stations enabled: %s", names)
    else:
        logging.info("Weather forecast disabled (set weather.enabled=true)")
    return weather


def _restart_workers_via_systemd() -> tuple[bool, str]:
    cmd = ["systemctl", "restart", "govee-charts-workers.service"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "systemctl not found on this host"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if not detail:
            detail = "permission denied or command failed"
        return False, f"Workers restart failed: {detail}"
    return True, "Workers restarting — UI remains available"


async def run_ui_server(
    cfg: dict[str, Any],
    *,
    workers_runtime: dict[str, Any] | None = None,
    db_override: Database | None = None,
    suffix_map_override: dict[str, str] | None = None,
) -> None:
    if db_override is None or suffix_map_override is None:
        # Workers own one-shot metadata seeding; UI opens the DB as fast as possible.
        db, suffix_map = await _init_runtime_db(cfg, seed_metadata=False)
    else:
        db = db_override
        suffix_map = suffix_map_override
    weather = _build_weather(cfg)
    fed = cfg["federation"]
    backfill = workers_runtime.get("backfill") if workers_runtime else None
    hvac_cfg = workers_runtime.get("hvac_cfg") if workers_runtime else HvacConfig.from_dict(
        cfg.get("hvac")
    )

    servers: list[uvicorn.Server] = []

    def request_shutdown() -> None:
        """First Ctrl+C: stop workers immediately, then HTTP listeners."""
        if workers_runtime is not None:
            workers_runtime["stop_event"].set()
        for server in servers:
            server.should_exit = True

    def request_restart() -> None:
        logging.warning("Stopping HTTP listeners for restart")
        for server in servers:
            server.should_exit = True

    host = str(cfg["server"]["host"])
    port = int(cfg["server"]["port"])
    ssl_port = int(cfg["server"].get("ssl_port") or 8081)
    certfile, keyfile = resolve_ssl_files(cfg["server"])
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host

    app = create_app(
        db,
        labels=cfg["labels"],
        federation_token=fed["token"] or None,
        node_id=fed["node_id"],
        peers=fed["peers"],
        suffix_map=suffix_map,
        weather=weather,
        on_restart_ui=request_restart,
        on_restart_workers=(
            _restart_workers_via_systemd if workers_runtime is None else None
        ),
        backfill=backfill,
        ssl_port=ssl_port if certfile and keyfile else None,
        hvac=hvac_cfg,
        scanner_enabled=bool(cfg["scanner"].get("enabled", True)),
        ble_alert_stale_after=float(cfg["scanner"].get("alert_stale_after", 300.0)),
    )

    http_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    servers.append(_ShutdownServer(http_config, on_signal=request_shutdown))

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
        servers.append(_ShutdownServer(https_config, on_signal=request_shutdown))
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
            # If one listener stops, tear down the other(s) + workers.
            request_shutdown()

    try:
        await asyncio.gather(*(_serve(s) for s in servers))
    finally:
        if workers_runtime is not None:
            await _stop_workers(workers_runtime)
        await db.close()


async def run_workers(cfg: dict[str, Any], *, enable_scanner: bool = True) -> None:
    db, suffix_map = await _init_runtime_db(cfg)
    runtime = await _start_workers(cfg, db, suffix_map, enable_scanner=enable_scanner)
    logging.info("Workers runtime started (node_id=%s)", cfg["federation"]["node_id"])
    stop_event: asyncio.Event = runtime["stop_event"]
    _install_stop_signals(stop_event)
    try:
        await stop_event.wait()
    finally:
        await _stop_workers(runtime)
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

    scanner_enabled = not args.no_scanner
    if args.mode == "ui":
        await run_ui_server(cfg, workers_runtime=None)
        return
    if args.mode == "workers":
        await run_workers(cfg, enable_scanner=scanner_enabled)
        return

    # Compatibility mode: current single-process runtime (UI + workers).
    db, suffix_map = await _init_runtime_db(cfg)
    workers_runtime = await _start_workers(cfg, db, suffix_map, enable_scanner=scanner_enabled)
    await run_ui_server(
        cfg,
        workers_runtime=workers_runtime,
        db_override=db,
        suffix_map_override=suffix_map,
    )


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print()
    logging.info("Stopped")
    # Bleak/CoreBluetooth leaves non-daemon threads that block interpreter
    # shutdown (especially on macOS) — without this, a second Ctrl+C is needed.
    os._exit(0)


if __name__ == "__main__":
    main()
