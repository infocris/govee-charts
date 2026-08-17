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

- Each node scans locally (if `scanner.enabled`) and **pushes locally produced** readings to `federation.peers` via `POST /api/ingest`:
  - Live BLE ads: `source = node_id`
  - GATT history backfill: `source = "{node_id}/gatt"` (when `backfill.federation_share` is true)
- Ingested readings are **not** re-forwarded (no loops). Per-reading optional `source` is accepted on ingest (defaults to the peer `node_id`).
- Shared optional `federation.token` sent as `X-Govee-Token`.
- Dedup key: unique `(address, ts)` in SQLite.
- Device metadata (label, zone, height, height_cm, room) can be pushed to peers via Overview **Push meta** (`POST /api/devices/{address}/push-meta` → peer `POST /api/devices/meta`).
- Before GATT, backfill may **GET** peer `/api/history` for the gap window (`backfill.federation_pull`); pulled samples keep peer provenance and are not re-published. Remaining holes still use BLE GATT.
- GATT backfill prefers the federation node with the **best recent RSSI** for a device; weaker nodes defer and wait for ingested history.

### Multi-adapter BLE

- `scanner.adapters = ["hci0", "hci1", …]` runs parallel BlueZ scanners; empty means the system default adapter.

## Conventions

- Prefer small, focused changes; match existing module style.
- Target Python **3.9+** (use `tomli` fallback for TOML on &lt; 3.11; keep `bleak>=0.22` generally, and older `bleak` + pure-Python `dbus-fast` on `armv6l`).
- Do not commit `config.toml`, `venv/`, `*.log`, or `data/*.db`.
- Do not invent cloud/Govee HTTP APIs — collection is BLE advertisement decode only (H5075 / H5179).
- After dependency changes, update `requirements.txt`.
- Keep the UI simple: overview table + compare charts; avoid heavy frameworks.
- **Map topology graph** (`static/app.js`): keep a minimum gap between room/façade nodes so connections (edges, padlocks) stay visible, and keep the layout away from the viewBox edges so labels and icons are not clipped. See `.cursor/rules/map-graph-layout.mdc`.
- **Apartment geometry**: ceiling ≈ **2.5 m**, interior door frames ≈ **2.0 m** (`apartment.ceiling_m` / `apartment.door_height_m`). Cross-section doors run floor→lintel with a transom above; categorical high/mid/low map onto transom / mid-door / near-floor. See `.cursor/rules/apartment-geometry.mdc`.
- After adding or changing settings in `config.example.toml` / `DEFAULTS`, **also update the local gitignored `config.toml`** when it exists: merge new keys with the documented defaults (enable new optional features that are on by default in the example). Do not overwrite existing user values, secrets, labels, peers, or paths. Mention a restart if the running service must reload config.
- **Web notifications** (window alerts): HTTPS + root `/sw.js` + `registration.showNotification()`; Safari standalone quirks and diagnostic UX are documented in the personal Cursor skill `web-notifications` (see `~/.cursor/skills/web-notifications/SKILL.md`).

## Useful commands

```bash
make install                 # venv + deps + config.toml from example if missing
make run                     # collector + web UI
make serve                   # web UI only (no BLE scanner)
make discover                # 30s BLE discovery then exit
sudo make systemd-install    # Linux: systemd service, starts on boot
make launchd-install         # macOS: LaunchAgent, starts at login
make restart                 # restart background service (systemd or launchd)
```
