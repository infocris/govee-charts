"""Persist federation peer URLs and node mode (UI-managed, shared by UI + workers)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PEERS_PATH = ROOT / "data" / "federation_peers.json"
DEFAULT_CONFIG_PATH = ROOT / "config.toml"

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


def load_federation_settings(path: Path | None = None) -> dict[str, Any] | None:
    """Return ``{peers, mode}`` from disk, or None if missing/unreadable."""
    path = path or DEFAULT_PEERS_PATH
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Federation peers file unreadable (%s): %s", path, exc)
        return None
    parsed = _parse_settings_payload(data)
    if parsed is None:
        logger.warning("Federation peers file has unexpected shape: %s", path)
    return parsed


def load_peers_file(path: Path | None = None) -> list[str] | None:
    """Return peers from disk, or None if the file is missing/unreadable."""
    settings = load_federation_settings(path)
    if settings is None:
        return None
    return list(settings["peers"])


def load_mode(path: Path | None = None) -> str | None:
    """Return stored mode, or None if the file is missing/unreadable."""
    settings = load_federation_settings(path)
    if settings is None:
        return None
    return str(settings["mode"])


def save_federation_settings(
    *,
    peers: list[Any] | None = None,
    mode: Any = None,
    peers_path: Path | None = None,
    config_path: Path | None = None,
    preserve_missing: bool = True,
) -> dict[str, Any]:
    """Atomically write peers + mode. Optionally preserve fields not passed."""
    path = peers_path or DEFAULT_PEERS_PATH
    existing = load_federation_settings(path) if preserve_missing else None
    if peers is None:
        normalized_peers = list((existing or {}).get("peers") or [])
    else:
        normalized_peers = normalize_peers(peers)
    if mode is None:
        normalized_mode = str((existing or {}).get("mode") or MODE_FULL)
    else:
        normalized_mode = normalize_mode(mode)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"peers": normalized_peers, "mode": normalized_mode}
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)

    try:
        sync_peers_to_config_toml(normalized_peers, config_path)
    except Exception as exc:
        logger.warning("Could not sync peers into config.toml: %s", exc)
    try:
        sync_mode_to_config_toml(normalized_mode, config_path)
    except Exception as exc:
        logger.warning("Could not sync mode into config.toml: %s", exc)
    return payload


def save_peers_file(peers: list[str], path: Path | None = None) -> list[str]:
    """Atomically write peers JSON (preserves mode). Returns normalized peers."""
    return list(
        save_federation_settings(peers=peers, peers_path=path)["peers"]
    )


def peers_file_mtime(path: Path | None = None) -> float | None:
    path = path or DEFAULT_PEERS_PATH
    try:
        return path.stat().st_mtime if path.exists() else None
    except OSError:
        return None


_PEERS_ARRAY_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)peers\s*=\s*\[[^\]]*\]",
    re.DOTALL,
)
_MODE_RE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)mode\s*=\s*"(?P<value>[^"]*)"',
)


def format_peers_toml(peers: list[str], *, indent: str = "") -> str:
    if not peers:
        return f"{indent}peers = []"
    inner = ",\n".join(f'{indent}  "{p}"' for p in peers)
    return f"{indent}peers = [\n{inner},\n{indent}]"


def _federation_region(text: str) -> tuple[int, int, str]:
    fed_idx = text.find("[federation]")
    search_from = fed_idx if fed_idx >= 0 else 0
    next_section = text.find("\n[", search_from + 1)
    region_end = next_section if next_section >= 0 else len(text)
    return search_from, region_end, text[search_from:region_end]


def sync_peers_to_config_toml(
    peers: list[str],
    path: Path | None = None,
) -> bool:
    """Rewrite the uncommented ``peers = […]`` array in config.toml."""
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    search_from, region_end, region = _federation_region(text)
    match = _PEERS_ARRAY_RE.search(region)
    if not match:
        logger.warning("No peers = […] array found in %s [federation]", path)
        return False
    indent = match.group("indent") or ""
    replacement = format_peers_toml(normalize_peers(peers), indent=indent)
    new_region = region[: match.start()] + replacement + region[match.end() :]
    new_text = text[:search_from] + new_region + text[region_end:]
    if new_text == text:
        return False
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return True


def sync_mode_to_config_toml(
    mode: str,
    path: Path | None = None,
) -> bool:
    """Rewrite or insert ``mode = "…"`` under ``[federation]``."""
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return False
    normalized = normalize_mode(mode)
    text = path.read_text(encoding="utf-8")
    search_from, region_end, region = _federation_region(text)
    match = _MODE_RE.search(region)
    line = f'mode = "{normalized}"'
    if match:
        indent = match.group("indent") or ""
        replacement = f"{indent}{line}"
        new_region = region[: match.start()] + replacement + region[match.end() :]
    else:
        # Insert after [federation] header line.
        lines = region.splitlines(keepends=True)
        if not lines:
            return False
        insert_at = 1 if lines[0].lstrip().startswith("[federation]") else 0
        indent = ""
        lines.insert(insert_at, f"{indent}{line}\n")
        new_region = "".join(lines)
    new_text = text[:search_from] + new_region + text[region_end:]
    if new_text == text:
        return False
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return True


def resolve_federation_settings(
    config_peers: list[Any] | None,
    *,
    config_mode: Any = None,
    peers_path: Path | None = None,
    seed_file: bool = True,
) -> dict[str, Any]:
    """Return runtime settings: file wins when present, else config (seed)."""
    config_norm = {
        "peers": normalize_peers(list(config_peers or [])),
        "mode": normalize_mode(config_mode),
    }
    file_settings = load_federation_settings(peers_path)
    if file_settings is not None:
        return file_settings
    if seed_file:
        try:
            return save_federation_settings(
                peers=config_norm["peers"],
                mode=config_norm["mode"],
                peers_path=peers_path,
                preserve_missing=False,
            )
        except Exception as exc:
            logger.warning("Could not seed federation peers file: %s", exc)
    return config_norm


def resolve_peers(
    config_peers: list[Any] | None,
    *,
    peers_path: Path | None = None,
    seed_file: bool = True,
    config_mode: Any = None,
) -> list[str]:
    """Return runtime peers (compat wrapper)."""
    return list(
        resolve_federation_settings(
            config_peers,
            config_mode=config_mode,
            peers_path=peers_path,
            seed_file=seed_file,
        )["peers"]
    )


def save_peers(
    peers: list[Any] | None,
    *,
    peers_path: Path | None = None,
    config_path: Path | None = None,
) -> list[str]:
    """Persist peers to JSON (preserve mode) and mirror into config.toml."""
    return list(
        save_federation_settings(
            peers=peers,
            peers_path=peers_path,
            config_path=config_path,
        )["peers"]
    )


def save_mode(
    mode: Any,
    *,
    peers_path: Path | None = None,
    config_path: Path | None = None,
) -> str:
    """Persist federation mode (preserve peers) and mirror into config.toml."""
    return str(
        save_federation_settings(
            mode=mode,
            peers_path=peers_path,
            config_path=config_path,
        )["mode"]
    )
