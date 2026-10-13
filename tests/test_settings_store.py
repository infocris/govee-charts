"""Tests for DB-backed settings (import, diffs, secrets, API)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from govee_charts.api import create_app
from govee_charts.main import DEFAULTS
from govee_charts.settings_store import (
    KEY_APARTMENT_PLANS,
    KEY_IMPORTED,
    SECRET_MASK,
    SettingsStore,
    bootstrap_part,
    deep_merge,
    diff_from_defaults,
    import_legacy_settings,
    load_sections,
    mask_secrets,
    unmask_secrets,
    validate_against_defaults,
)


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "readings.db")


def test_diff_keeps_only_changes():
    defaults = {"a": 1, "b": {"c": 2, "d": [1]}, "labels": {}}
    value = {"a": 1, "b": {"c": 3, "d": [1]}, "e": "x"}
    assert diff_from_defaults(value, defaults) == {"b": {"c": 3}, "e": "x"}
    assert diff_from_defaults(defaults, defaults) == {}


def test_bootstrap_part_picks_server_database_and_log_file():
    raw = {
        "server": {"port": 9000},
        "database": {"path": "x.db"},
        "scanner": {"log_file": "a.log", "active": False},
        "weather": {"enabled": True},
    }
    assert bootstrap_part(raw) == {
        "server": {"port": 9000},
        "database": {"path": "x.db"},
        "scanner": {"log_file": "a.log"},
    }


def test_import_once_from_toml_and_json(store: SettingsStore, tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "federation_peers.json").write_text(
        json.dumps({"peers": ["https://a.example:8082"], "mode": "collector"}),
        encoding="utf-8",
    )
    (data_dir / "apartment_plans.json").write_text(
        json.dumps({"active_plan_id": None, "plans": []}), encoding="utf-8"
    )
    toml_cfg = {
        "server": {"port": 9000},
        "scanner": {"log_file": "a.log", "active": False, "retention_days": 30},
        "federation": {"node_id": "edge", "peers": ["https://old.example:1"]},
        "labels": {"aa:bb": "Living"},
    }
    assert import_legacy_settings(store, toml_cfg, DEFAULTS, data_dir=data_dir)

    # Only non-default, non-bootstrap values are stored.
    assert store.get_section("scanner") == {"active": False}
    assert store.get_section("federation") == {
        "node_id": "edge",
        "peers": ["https://a.example:8082"],
        "mode": "collector",
    }
    assert store.get_section("labels") == {"aa:bb": "Living"}
    assert store.get(KEY_APARTMENT_PLANS) == {"active_plan_id": None, "plans": []}
    assert not (data_dir / "federation_peers.json").exists()
    assert (data_dir / "federation_peers.json.imported").exists()
    assert "server" not in load_sections(store, DEFAULTS)

    # Second run is a no-op: the database is the source of truth.
    toml_cfg["scanner"]["active"] = True
    assert not import_legacy_settings(store, toml_cfg, DEFAULTS, data_dir=data_dir)
    assert store.get_section("scanner") == {"active": False}
    assert store.get(KEY_IMPORTED) is not None


def test_mask_roundtrip_keeps_secrets():
    current = {"token": "s3cret", "ha_token_file": "data/x", "nested": {"mqtt_password": "pw"}}
    masked = mask_secrets(current)
    assert masked["token"] == SECRET_MASK
    assert masked["ha_token_file"] == "data/x"
    assert masked["nested"]["mqtt_password"] == SECRET_MASK
    assert unmask_secrets(masked, current) == current
    changed = dict(masked, token="new")
    assert unmask_secrets(changed, current)["token"] == "new"


def test_validate_against_defaults():
    defaults = {"enabled": False, "port": 1883, "names": {}, "lat": None}
    assert validate_against_defaults({"enabled": True, "port": 1.5, "lat": 4}, defaults) == []
    errors = validate_against_defaults({"enabled": "yes", "names": []}, defaults)
    assert len(errors) == 2


def test_settings_api_roundtrip(store: SettingsStore):
    # Python 3.9: create_app builds asyncio.Lock()s, which need a current loop
    # (earlier IsolatedAsyncioTestCase runs leave none set).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = create_app(
        db=None,  # type: ignore[arg-type]
        settings_store=store,
        config_defaults=DEFAULTS,
    )
    client = TestClient(app)

    listed = client.get("/api/settings").json()
    names = [s["name"] for s in listed["sections"]]
    assert "server" not in names and "database" not in names
    assert "federation" in names

    store.set_section("federation", {"token": "s3cret"})
    got = client.get("/api/settings/federation").json()
    assert got["value"]["token"] == SECRET_MASK
    assert got["customized"] is True

    value = dict(got["value"], peers=["https://a.example:8082/"], mode="collector")
    put = client.put("/api/settings/federation", json={"value": value})
    assert put.status_code == 200, put.text
    stored = store.get_section("federation")
    assert stored["token"] == "s3cret"
    assert stored["peers"] == ["https://a.example:8082"]
    assert app.state.federation_mode == "collector"

    bad = client.put("/api/settings/scanner", json={"value": {"active": "yes"}})
    assert bad.status_code == 422
    assert client.get("/api/settings/server").status_code == 404

    # Saving defaults back clears the row.
    scanner = client.get("/api/settings/scanner").json()["value"]
    assert "log_file" not in scanner
    client.put("/api/settings/scanner", json={"value": scanner})
    assert store.get_section("scanner") == {}

    reset = client.delete("/api/settings/federation")
    assert reset.status_code == 200
    assert store.get_section("federation") == {}
    assert deep_merge(DEFAULTS["federation"], {})["peers"] == []
    asyncio.set_event_loop(None)
    loop.close()
