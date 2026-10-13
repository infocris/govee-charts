"""Runtime settings persisted in SQLite (``app_settings`` table in readings.db).

``config.toml`` only keeps bootstrap keys (``[server]``, ``[database]``,
``scanner.log_file``). Every other section lives in the database as a JSON diff
against ``DEFAULTS`` and is edited from Settings. The first start imports the
legacy ``config.toml`` sections and UI-managed JSON files once.

Uses short-lived stdlib ``sqlite3`` connections so sync callers (config load,
federation store, plan store) work in any process (UI or workers).
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Sections that stay in config.toml (needed before the database is reachable).
BOOTSTRAP_SECTIONS = ("server", "database")
# Keys inside DB-managed sections that also stay in config.toml.
BOOTSTRAP_KEYS: dict[str, tuple[str, ...]] = {"scanner": ("log_file",)}

SECTION_PREFIX = "section:"
KEY_APARTMENT_OVERRIDES = "apartment_overrides"
KEY_APARTMENT_PLANS = "apartment_plans"
KEY_IMPORTED = "meta:toml_imported"

SECRET_MASK = "********"

_SAME = object()


class SettingsStore:
    """Key → JSON value store backed by the ``app_settings`` table."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_ts REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def get(self, key: str, default: Any = None) -> Any:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            logger.warning("Setting %s is not valid JSON; using default", key)
            return default

    def set(self, key: str, value: Any) -> None:
        self.set_many({key: value})

    def set_many(self, values: dict[str, Any]) -> None:
        now = time.time()
        rows = [
            (key, json.dumps(value, ensure_ascii=False), now)
            for key, value in values.items()
        ]
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "INSERT INTO app_settings(key, value, updated_ts) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_ts = excluded.updated_ts",
                rows,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def delete(self, key: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        finally:
            conn.close()

    def updated_ts(self, key: str) -> float | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT updated_ts FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        return float(row[0]) if row else None

    # --- config sections -------------------------------------------------

    def get_section(self, name: str) -> dict[str, Any]:
        """Stored diff for one config section (``{}`` when not customized)."""
        value = self.get(SECTION_PREFIX + name)
        return value if isinstance(value, dict) else {}

    def set_section(self, name: str, value: dict[str, Any]) -> None:
        self.set(SECTION_PREFIX + name, strip_bootstrap(name, value))

    def patch_section(self, name: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge ``patch`` into the stored section; return the new stored diff."""
        stored = self.get_section(name)
        stored.update(patch)
        self.set_section(name, stored)
        return stored

    def delete_section(self, name: str) -> None:
        self.delete(SECTION_PREFIX + name)

    def section_updated_ts(self, name: str) -> float | None:
        return self.updated_ts(SECTION_PREFIX + name)


_default_store: SettingsStore | None = None


def configure_default_store(path: Path) -> SettingsStore:
    """Open (or reuse) the process-wide store for ``path``."""
    global _default_store
    if _default_store is None or _default_store.path != Path(path):
        _default_store = SettingsStore(path)
    return _default_store


def default_store() -> SettingsStore | None:
    return _default_store


def set_default_store(store: SettingsStore | None) -> None:
    """Install a store explicitly (tests)."""
    global _default_store
    _default_store = store


# --- helpers ---------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _diff(value: Any, default: Any) -> Any:
    if value == default:
        return _SAME
    if isinstance(value, dict) and isinstance(default, dict):
        out: dict[str, Any] = {}
        for key, sub in value.items():
            if key in default:
                d = _diff(sub, default[key])
                if d is _SAME:
                    continue
                out[key] = d
            else:
                out[key] = sub
        # Keys dropped from a default dict cannot be expressed as a diff.
        return out if out else _SAME
    return value


def diff_from_defaults(value: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys that differ from ``default`` (so new defaults propagate)."""
    out = _diff(value, default)
    return {} if out is _SAME else out


def strip_bootstrap(section: str, value: dict[str, Any]) -> dict[str, Any]:
    out = dict(value)
    for key in BOOTSTRAP_KEYS.get(section, ()):
        out.pop(key, None)
    return out


def bootstrap_part(raw: dict[str, Any]) -> dict[str, Any]:
    """Subset of a parsed config.toml that stays file-based."""
    out: dict[str, Any] = {}
    for section in BOOTSTRAP_SECTIONS:
        if isinstance(raw.get(section), dict):
            out[section] = copy.deepcopy(raw[section])
    for section, keys in BOOTSTRAP_KEYS.items():
        src = raw.get(section)
        if not isinstance(src, dict):
            continue
        picked = {k: src[k] for k in keys if k in src}
        if picked:
            out.setdefault(section, {}).update(picked)
    return out


def is_secret_key(key: str) -> bool:
    k = key.lower()
    if k.endswith("_file") or k.endswith("_path"):
        return False
    return "token" in k or "password" in k or "secret" in k


def mask_secrets(value: Any) -> Any:
    """Replace non-empty secret strings with ``SECRET_MASK`` (API responses)."""
    if isinstance(value, dict):
        out = {}
        for key, sub in value.items():
            if is_secret_key(str(key)) and isinstance(sub, str) and sub:
                out[key] = SECRET_MASK
            else:
                out[key] = mask_secrets(sub)
        return out
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    return value


def unmask_secrets(new: Any, current: Any) -> Any:
    """Restore secrets the client sent back as ``SECRET_MASK``."""
    if isinstance(new, dict):
        cur = current if isinstance(current, dict) else {}
        out = {}
        for key, sub in new.items():
            if sub == SECRET_MASK and is_secret_key(str(key)):
                out[key] = cur.get(key, "")
            else:
                out[key] = unmask_secrets(sub, cur.get(key))
        return out
    if isinstance(new, list):
        cur_list = current if isinstance(current, list) else []
        return [
            unmask_secrets(v, cur_list[i] if i < len(cur_list) else None)
            for i, v in enumerate(new)
        ]
    return new


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "null"


def validate_against_defaults(
    value: Any, default: Any, path: str = ""
) -> list[str]:
    """Return type errors where ``value`` disagrees with a non-null default."""
    errors: list[str] = []
    if default is None:
        return errors
    expected = _type_name(default)
    actual = _type_name(value)
    if expected != actual:
        errors.append(f"{path or 'value'}: expected {expected}, got {actual}")
        return errors
    if isinstance(value, dict) and default:
        for key, sub in value.items():
            if key in default:
                errors.extend(
                    validate_against_defaults(
                        sub, default[key], f"{path}.{key}" if path else str(key)
                    )
                )
    return errors


# --- one-time import -------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Legacy settings file unreadable (%s): %s", path, exc)
    return None


def _retire(path: Path) -> None:
    try:
        path.replace(path.with_name(path.name + ".imported"))
    except OSError as exc:
        logger.warning("Could not rename imported file %s: %s", path, exc)


def import_legacy_settings(
    store: SettingsStore,
    toml_cfg: dict[str, Any],
    defaults: dict[str, Any],
    *,
    data_dir: Path | None = None,
    force: bool = False,
) -> bool:
    """Import config.toml sections + UI JSON files once. Returns True if run."""
    sections = [s for s in defaults if s not in BOOTSTRAP_SECTIONS]
    legacy_sections = [
        s for s in sections if isinstance(toml_cfg.get(s), dict) and strip_bootstrap(s, toml_cfg[s])
    ]
    if store.get(KEY_IMPORTED) is not None and not force:
        if legacy_sections:
            logger.warning(
                "config.toml sections ignored (settings live in the database, "
                "edit them in Settings → Configuration): %s",
                ", ".join(legacy_sections),
            )
        return False

    data_dir = data_dir or DATA_DIR
    values: dict[str, Any] = {}
    for section in legacy_sections:
        raw = strip_bootstrap(section, toml_cfg[section])
        diff = diff_from_defaults(raw, defaults.get(section) or {})
        if diff:
            values[SECTION_PREFIX + section] = diff

    retire: list[Path] = []
    peers_path = data_dir / "federation_peers.json"
    peers_data = _read_json(peers_path)
    if isinstance(peers_data, list):
        peers_data = {"peers": peers_data}
    if isinstance(peers_data, dict):
        fed = dict(values.get(SECTION_PREFIX + "federation") or {})
        if isinstance(peers_data.get("peers"), list):
            fed["peers"] = list(peers_data["peers"])
        if peers_data.get("mode"):
            fed["mode"] = str(peers_data["mode"])
        values[SECTION_PREFIX + "federation"] = fed
        retire.append(peers_path)

    for key, filename in (
        (KEY_APARTMENT_OVERRIDES, "apartment_overrides.json"),
        (KEY_APARTMENT_PLANS, "apartment_plans.json"),
    ):
        path = data_dir / filename
        data = _read_json(path)
        if isinstance(data, dict):
            values[key] = data
            retire.append(path)

    values[KEY_IMPORTED] = {
        "ts": time.time(),
        "sections": sorted(k[len(SECTION_PREFIX):] for k in values if k.startswith(SECTION_PREFIX)),
        "files": [p.name for p in retire],
    }
    store.set_many(values)
    for path in retire:
        _retire(path)
    logger.info(
        "Imported settings into the database: sections=%s files=%s",
        ", ".join(values[KEY_IMPORTED]["sections"]) or "(none)",
        ", ".join(values[KEY_IMPORTED]["files"]) or "(none)",
    )
    return True


def load_sections(store: SettingsStore, defaults: dict[str, Any]) -> dict[str, Any]:
    """Return ``{section: stored diff}`` for every DB-managed section."""
    out: dict[str, Any] = {}
    for section in defaults:
        if section in BOOTSTRAP_SECTIONS:
            continue
        stored = store.get_section(section)
        if stored:
            out[section] = strip_bootstrap(section, stored)
    return out


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    from govee_charts import main as app_main

    parser = argparse.ArgumentParser(
        prog="python -m govee_charts.settings_store",
        description="Inspect or import DB-backed settings",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import-toml", help="Import config.toml sections into the database")
    imp.add_argument(
        "--force",
        action="store_true",
        help="Overwrite stored sections even if an import already ran",
    )
    show = sub.add_parser("show", help="Print stored settings (secrets masked)")
    show.add_argument("section", nargs="?", help="Only this section")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    toml_cfg = app_main.read_config_toml()
    store = SettingsStore(app_main.resolve_db_path(app_main.load_bootstrap_config(toml_cfg)))
    if args.cmd == "import-toml":
        ran = import_legacy_settings(store, toml_cfg, app_main.DEFAULTS, force=args.force)
        if not ran:
            print("Already imported; use --force to overwrite from config.toml.")
        return 0
    sections = load_sections(store, app_main.DEFAULTS)
    if args.section:
        sections = {args.section: sections.get(args.section, {})}
    print(json.dumps(mask_secrets(sections), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
