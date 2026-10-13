"""Federation peer URLs and node mode (UI-managed, stored in ``app_settings``)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from govee_charts.settings_store import SettingsStore, default_store

logger = logging.getLogger(__name__)

SECTION = "federation"

MODE_FULL = "full"
MODE_COLLECTOR = "collector"
FEDERATION_MODES = (MODE_FULL, MODE_COLLECTOR)


def normalize_mode(raw: Any) -> str:
    """Return ``full`` or ``collector``."""
    value = str(raw or "").strip().lower()
    if value in ("collector", "collect", "ble", "edge", "sensor"):
        return MODE_COLLECTOR
    return MODE_FULL


def normalize_peer_url(url: str) -> str:
    """Validate and normalize a peer base URL (scheme + host, no trailing slash)."""
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("Peer URL is empty")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Peer URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("Peer URL must include a hostname")
    # Reject credentials / fragments in stored URLs.
    if parsed.username or parsed.password:
        raise ValueError("Peer URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Peer URL must not include query or fragment")
    path = (parsed.path or "").rstrip("/")
    if path not in ("", "/"):
        raise ValueError("Peer URL must be an origin (no path)")
    netloc = parsed.netloc
    return f"{scheme}://{netloc}"


def normalize_peers(peers: list[Any] | None) -> list[str]:
    """Normalize a peer list; drop empties; dedupe (case-sensitive URL)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in peers or []:
        try:
            url = normalize_peer_url(str(raw))
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _parse_settings_payload(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        return {"peers": normalize_peers(data), "mode": MODE_FULL}
    if isinstance(data, dict):
        if "peers" not in data and "mode" not in data:
            return None
        peers_raw = data.get("peers")
        if peers_raw is None:
            peers_raw = []
        if not isinstance(peers_raw, list):
            return None
        return {
            "peers": normalize_peers(peers_raw),
            "mode": normalize_mode(data.get("mode")),
        }
    return None


def _store(store: SettingsStore | None) -> SettingsStore | None:
    return store if store is not None else default_store()


def load_federation_settings(
    store: SettingsStore | None = None,
) -> dict[str, Any] | None:
    """Return ``{peers, mode}`` from the settings store, or None if unavailable."""
    st = _store(store)
    if st is None:
        return None
    try:
        stored = st.get_section(SECTION)
    except Exception as exc:
        logger.warning("Federation settings unreadable: %s", exc)
        return None
    return _parse_settings_payload(
        {"peers": stored.get("peers") or [], "mode": stored.get("mode")}
    )


def load_peers(store: SettingsStore | None = None) -> list[str] | None:
    """Return stored peers, or None if the store is unavailable."""
    settings = load_federation_settings(store)
    if settings is None:
        return None
    return list(settings["peers"])


def settings_version(store: SettingsStore | None = None) -> float | None:
    """Last update timestamp of the federation section (change detection)."""
    st = _store(store)
    if st is None:
        return None
    try:
        return st.section_updated_ts(SECTION)
    except Exception:
        return None


def save_federation_settings(
    *,
    peers: list[Any] | None = None,
    mode: Any = None,
    store: SettingsStore | None = None,
) -> dict[str, Any]:
    """Persist peers and/or mode; fields not passed are preserved."""
    st = _store(store)
    if st is None:
        raise RuntimeError("Settings store is not configured")
    existing = load_federation_settings(st) or {"peers": [], "mode": MODE_FULL}
    payload = {
        "peers": normalize_peers(peers) if peers is not None else list(existing["peers"]),
        "mode": normalize_mode(mode) if mode is not None else str(existing["mode"]),
    }
    st.patch_section(SECTION, payload)
    return payload


def save_peers(peers: list[Any] | None, *, store: SettingsStore | None = None) -> list[str]:
    """Persist peers (preserve mode)."""
    return list(save_federation_settings(peers=peers, store=store)["peers"])


def save_mode(mode: Any, *, store: SettingsStore | None = None) -> str:
    """Persist federation mode (preserve peers)."""
    return str(save_federation_settings(mode=mode, store=store)["mode"])
