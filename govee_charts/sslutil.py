"""Resolve TLS certificate paths for the web UI."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CERT = ROOT / "data" / "ssl" / "cert.pem"
DEFAULT_KEY = ROOT / "data" / "ssl" / "key.pem"
GEN_SCRIPT = ROOT / "scripts" / "gen-ssl-cert.sh"

logger = logging.getLogger(__name__)


def resolve_ssl_files(server_cfg: dict[str, Any]) -> tuple[Path | None, Path | None]:
    """Return (certfile, keyfile) when SSL is enabled, else (None, None)."""
    if not bool(server_cfg.get("ssl", False)):
        return None, None

    cert = Path(str(server_cfg.get("certfile") or DEFAULT_CERT))
    key = Path(str(server_cfg.get("keyfile") or DEFAULT_KEY))
    if not cert.is_absolute():
        cert = ROOT / cert
    if not key.is_absolute():
        key = ROOT / key

    if cert.is_file() and key.is_file():
        return cert, key

    auto = bool(server_cfg.get("ssl_auto_generate", True))
    if auto and GEN_SCRIPT.is_file():
        logger.info("SSL cert missing — generating self-signed certificate…")
        subprocess.run(
            ["bash", str(GEN_SCRIPT)],
            check=True,
            cwd=str(ROOT),
        )
        if cert.is_file() and key.is_file():
            return cert, key

    raise FileNotFoundError(
        f"SSL enabled but cert/key missing ({cert}, {key}). "
        "Run: make ssl"
    )
