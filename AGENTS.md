# Agent guidelines

## Language

All project documentation **and code** must be written in **English**.

This includes:

- `README.md`, `AGENTS.md`, and other Markdown docs
- Code comments and module/function docstrings
- Comments in `config.example.toml` and similar config templates
- User-facing strings (web UI, log messages, CLI help, API error details)
- Commit messages (prefer English)

Friendly device **labels** in the user's local `config.toml` may remain in any language.

Chat replies to the repository owner may follow their preferred language; project artifacts stay English.

## Architecture

- **Python package** `govee_charts/`: BLE scanner (Bleak), SQLite store (`aiosqlite`), FastAPI dashboard + JSON API, optional federation publisher (`httpx`).
- **Static UI** in `static/` (vanilla JS + Chart.js CDN). No frontend build step.
- **Entry point**: `python -m govee_charts.main` (see `Makefile`).
- **Local config**: `config.toml` (gitignored). Template: `config.example.toml`.

### Federation

- Each node scans locally (if `scanner.enabled`) and **pushes only locally scanned** readings to `federation.peers` via `POST /api/ingest`.
- Ingested readings are stored with `source = peer node_id` and are **not** re-forwarded (no loops).
- Shared optional `federation.token` sent as `X-Govee-Token`.
- Dedup key: unique `(address, ts)` in SQLite.

### Multi-adapter BLE

- `scanner.adapters = ["hci0", "hci1", …]` runs parallel BlueZ scanners; empty means the system default adapter.

## Conventions

- Prefer small, focused changes; match existing module style.
- Target Python **3.9+** (use `tomli` fallback for TOML on &lt; 3.11; keep `bleak>=0.22` generally, and older `bleak` + pure-Python `dbus-fast` on `armv6l`).
- Do not commit `config.toml`, `venv/`, `*.log`, or `data/*.db`.
- Do not invent cloud/Govee HTTP APIs — collection is BLE advertisement decode only (H5075 / H5179).
- After dependency changes, update `requirements.txt`.
- Keep the UI simple: overview table + compare charts; avoid heavy frameworks.

## Useful commands

```bash
make install    # venv + deps + config.toml from example if missing
make run        # collector + web UI
make serve      # web UI only (no BLE scanner)
make discover   # 30s BLE discovery then exit
```
