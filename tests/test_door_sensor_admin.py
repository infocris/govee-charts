"""Contact sensor management: full list, delete, HA entity add/remove."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from govee_charts.api import create_app
from govee_charts.db import Database
from govee_charts.doors import DoorHaPoller, DoorsConfig
from govee_charts.main import DEFAULTS
from govee_charts.settings_store import SettingsStore


def _setup(tmp_path: Path):
    # Python 3.9: create_app builds asyncio.Lock()s, which need a current loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    db = Database(tmp_path / "readings.db")
    loop.run_until_complete(db.connect())
    store = SettingsStore(tmp_path / "readings.db")
    app = create_app(db, settings_store=store, config_defaults=DEFAULTS)
    return loop, db, store, app


def test_list_delete_and_ha_entities(tmp_path: Path):
    loop, db, store, app = _setup(tmp_path)
    try:
        loop.run_until_complete(
            db.insert_door_event(
                sensor_id="ring-1", name="Porte Cuisine", state="closed", ts=1.0, source="ring-mqtt"
            )
        )
        loop.run_until_complete(db.ensure_door_sensor(sensor_id="silent", name="Silent"))
        with TestClient(app) as client:
            listed = client.get("/api/doors/sensors").json()
            ids = {s["sensor_id"]: s for s in listed["sensors"]}
            assert set(ids) == {"ring-1", "silent"}
            assert ids["ring-1"]["event_count"] == 1
            assert ids["silent"]["event_count"] == 0

            renamed = client.patch("/api/doors/silent", json={"name": "Garage window", "kind": "window"})
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["name"] == "Garage window"

            bad = client.post("/api/doors/ha-entities", json={"entity_id": "light.x"})
            assert bad.status_code == 400
            added = client.post(
                "/api/doors/ha-entities",
                json={"entity_id": "binary_sensor.porte_garage", "name": "Garage"},
            )
            assert added.status_code == 200, added.text
            assert store.get_section("doors")["ha_entities"] == ["binary_sensor.porte_garage"]
            dup = client.post(
                "/api/doors/ha-entities", json={"entity_id": "binary_sensor.porte_garage"}
            )
            assert dup.status_code == 409
            listed = client.get("/api/doors/sensors").json()
            garage = next(s for s in listed["sensors"] if s["sensor_id"] == "binary_sensor.porte_garage")
            assert garage["ha_polled"] is True
            assert garage["name"] == "Garage"

            gone = client.delete("/api/doors/binary_sensor.porte_garage")
            assert gone.status_code == 200 and gone.json()["unpolled"] is True
            assert store.get_section("doors")["ha_entities"] == []

            assert client.delete("/api/doors/ring-1").status_code == 200
            assert client.delete("/api/doors/ring-1").status_code == 404
            remaining = [s["sensor_id"] for s in client.get("/api/doors/sensors").json()["sensors"]]
            assert remaining == ["silent"]
            assert client.get("/api/doors/sensors").json()["sensors"][0]["kind"] == "window"
    finally:
        loop.run_until_complete(db.db.close())
        asyncio.set_event_loop(None)
        loop.close()


def test_poller_reloads_entities(tmp_path: Path):
    store = SettingsStore(tmp_path / "readings.db")
    cfg = DoorsConfig.from_dict({"enabled": True, "ha_entities": ["binary_sensor.a"]})
    poller = DoorHaPoller(None, cfg, settings_store=store)  # type: ignore[arg-type]
    assert poller.entities == ("binary_sensor.a",)
    assert not poller.reload_entities()
    store.patch_section("doors", {"ha_entities": ["binary_sensor.a", "binary_sensor.b"]})
    assert poller.reload_entities()
    assert poller.entities == ("binary_sensor.a", "binary_sensor.b")
    store.patch_section("doors", {"ha_entities": []})
    assert poller.reload_entities()
    assert poller.entities == ()
