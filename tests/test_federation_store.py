"""Tests for UI-managed federation peer persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from govee_charts.federation import PeerPublisher
from govee_charts.federation_store import (
    MODE_COLLECTOR,
    MODE_FULL,
    load_federation_settings,
    load_peers,
    normalize_mode,
    normalize_peer_url,
    normalize_peers,
    save_mode,
    save_peers,
    settings_version,
)
from govee_charts.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "readings.db")


def test_normalize_peer_url_ok():
    assert (
        normalize_peer_url("https://raspberrian.example:8082/")
        == "https://raspberrian.example:8082"
    )
    assert normalize_peer_url("http://192.168.1.20:8080") == "http://192.168.1.20:8080"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "raspberrian",
        "ftp://x",
        "https://user:pass@host",
        "https://host/path",
        "https://host?x=1",
    ],
)
def test_normalize_peer_url_rejects(bad):
    with pytest.raises(ValueError):
        normalize_peer_url(bad)


def test_normalize_peers_dedupes():
    assert normalize_peers(
        [
            "https://a.example:8082/",
            "https://a.example:8082",
            "https://b.example:8083",
            "",
            "not-a-url",
        ]
    ) == ["https://a.example:8082", "https://b.example:8083"]


def test_save_and_load_peers(store: SettingsStore):
    written = save_peers(
        ["https://a.example:8082/", "https://b.example:8083"],
        store=store,
    )
    assert written == ["https://a.example:8082", "https://b.example:8083"]
    assert load_peers(store) == written


def test_settings_version_changes_on_save(store: SettingsStore):
    assert settings_version(store) is None
    save_peers(["https://a.example:8082"], store=store)
    assert settings_version(store) is not None


def test_normalize_mode():
    assert normalize_mode("full") == MODE_FULL
    assert normalize_mode("collector") == MODE_COLLECTOR
    assert normalize_mode("BLE") == MODE_COLLECTOR
    assert normalize_mode("") == MODE_FULL


def test_save_mode_preserves_peers(store: SettingsStore):
    save_peers(["https://a.example:8082"], store=store)
    assert save_mode("collector", store=store) == MODE_COLLECTOR
    assert load_federation_settings(store) == {
        "peers": ["https://a.example:8082"],
        "mode": MODE_COLLECTOR,
    }


def test_save_preserves_other_federation_keys(store: SettingsStore):
    store.set_section("federation", {"node_id": "edge", "token": "s3cret"})
    save_peers(["https://a.example:8082"], store=store)
    stored = store.get_section("federation")
    assert stored["node_id"] == "edge"
    assert stored["token"] == "s3cret"
    assert stored["peers"] == ["https://a.example:8082"]


def test_peer_publisher_collector_disables_outbound():
    pub = PeerPublisher(
        ["https://a.example:8082"],
        node_id="edge",
        mode="collector",
    )
    assert pub.is_collector
    assert not pub.enabled
    pub.set_mode("full")
    assert pub.enabled
    pub.set_mode("collector")
    assert not pub.enabled
