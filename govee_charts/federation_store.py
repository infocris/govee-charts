"""Persist federation peer URLs (UI-managed, shared by UI + workers)."""

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


def load_peers_file(path: Path | None = None) -> list[str] | None:
    """Return peers from disk, or None if the file is missing/unreadable."""
    path = path or DEFAULT_PEERS_PATH
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Federation peers file unreadable (%s): %s", path, exc)
        return None
    if isinstance(data, list):
        return normalize_peers(data)
    if isinstance(data, dict) and isinstance(data.get("peers"), list):
        return normalize_peers(data["peers"])
    logger.warning("Federation peers file has unexpected shape: %s", path)
    return None


def save_peers_file(peers: list[str], path: Path | None = None) -> list[str]:
    """Atomically write peers JSON. Returns the normalized list written."""
    path = path or DEFAULT_PEERS_PATH
    normalized = normalize_peers(peers)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"peers": normalized}
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return normalized


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


def format_peers_toml(peers: list[str], *, indent: str = "") -> str:
    if not peers:
        return f"{indent}peers = []"
    inner = ",\n".join(f'{indent}  "{p}"' for p in peers)
    return f"{indent}peers = [\n{inner},\n{indent}]"


def sync_peers_to_config_toml(
    peers: list[str],
    path: Path | None = None,
) -> bool:
    """Rewrite the uncommented ``peers = […]`` array in config.toml.

    Returns True when the file was updated.
    """
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    # Prefer the peers array inside [federation] when present.
    fed_idx = text.find("[federation]")
    search_from = fed_idx if fed_idx >= 0 else 0
    next_section = text.find("\n[", search_from + 1)
    region_end = next_section if next_section >= 0 else len(text)
    region = text[search_from:region_end]
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


def resolve_peers(
    config_peers: list[Any] | None,
    *,
    peers_path: Path | None = None,
    seed_file: bool = True,
) -> list[str]:
    """Return runtime peers: file wins when present, else config (optionally seed)."""
    config_norm = normalize_peers(list(config_peers or []))
    file_peers = load_peers_file(peers_path)
    if file_peers is not None:
        return file_peers
    if seed_file:
        try:
            save_peers_file(config_norm, peers_path)
        except Exception as exc:
            logger.warning("Could not seed federation peers file: %s", exc)
    return config_norm


def save_peers(
    peers: list[Any] | None,
    *,
    peers_path: Path | None = None,
    config_path: Path | None = None,
) -> list[str]:
    """Persist peers to JSON and mirror into config.toml when possible."""
    normalized = save_peers_file(list(peers or []), peers_path)
    try:
        sync_peers_to_config_toml(normalized, config_path)
    except Exception as exc:
        logger.warning("Could not sync peers into config.toml: %s", exc)
    return normalized
