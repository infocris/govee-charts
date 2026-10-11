"""Tests for UI-managed federation peer persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from govee_charts.federation_store import (
    format_peers_toml,
    load_peers_file,
    normalize_peer_url,
    normalize_peers,
    resolve_peers,
    save_peers,
    sync_peers_to_config_toml,
)


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


def test_save_and_load_peers_file(tmp_path: Path):
    path = tmp_path / "federation_peers.json"
    written = save_peers(
        ["https://a.example:8082/", "https://b.example:8083"],
        peers_path=path,
        config_path=tmp_path / "missing.toml",
    )
    assert written == ["https://a.example:8082", "https://b.example:8083"]
    assert load_peers_file(path) == written


def test_resolve_peers_file_wins(tmp_path: Path):
    path = tmp_path / "federation_peers.json"
    save_peers(["https://file.example:1"], peers_path=path, config_path=tmp_path / "x.toml")
    assert resolve_peers(
        ["https://config.example:2"],
        peers_path=path,
        seed_file=False,
    ) == ["https://file.example:1"]


def test_resolve_peers_seeds_from_config(tmp_path: Path):
    path = tmp_path / "federation_peers.json"
    out = resolve_peers(
        ["https://config.example:8082/"],
        peers_path=path,
        seed_file=True,
    )
    assert out == ["https://config.example:8082"]
    assert load_peers_file(path) == out


def test_sync_peers_to_config_toml(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[server]\nport = 8080\n\n"
        "[federation]\n"
        'node_id = "local"\n'
        "token = \"\"\n"
        "peers = [\n"
        '  "https://old.example:8082",\n'
        "]\n"
        "\n[weather]\nenabled = true\n",
        encoding="utf-8",
    )
    assert sync_peers_to_config_toml(
        ["https://new.example:8082", "https://other.example:8083"],
        cfg,
    )
    text = cfg.read_text(encoding="utf-8")
    assert "https://new.example:8082" in text
    assert "https://other.example:8083" in text
    assert "https://old.example:8082" not in text
    assert 'node_id = "local"' in text
    assert "[weather]" in text


def test_format_peers_toml_empty():
    assert format_peers_toml([]) == "peers = []"
