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

### Device identity: MAC vs macOS UUID (recurring pitfall)

**Symptom on macOS nodes:** new sensors show up as UUID addresses (e.g. `A889CA39-71C5-…`) and duplicate federation peers that already store the real BLE MAC. GATT `find_device_by_address(MAC)` also fails while live ads still decode.

**Cause:** CoreBluetooth / Bleak on Darwin expose opaque peripheral **UUIDs**, not the public BLE MAC. BlueZ on Linux exposes the real MAC. Dedup and federation key on `(address, ts)`, so UUID ≠ MAC splits one physical sensor into two rows.

**Canonical resolution (do not regress):**

| Family | How the real MAC is recovered | Code |
| --- | --- | --- |
| Govee H5075 / H5179 | Last four hex chars of the local name (`GVH5075_2E08` → `…:2E:08`), mapped via `labels` / known MACs | `govee_charts/address.py` (`resolve_device_address`, `suffix_map`) |
| SwitchBot Meter family | First 6 bytes of manufacturer data company id `0x0969` (Bleak already strips the company id) | `govee_charts/switchbot_decode.py` (`mac_from_manufacturer`) |

- Store and federate the **canonical MAC** only; never persist a Darwin UUID as the device primary key once a MAC is known.
- On first sight of UUID → MAC, the scanner merges the alias row (`Database.merge_device_alias` / `_rekey_device`) so history follows the MAC.
- GATT on macOS must reuse the cached `BLEDevice` from the scanner (or a MAC-aware scan), not `find_device_by_address(MAC)` alone — see `history_gatt.py` / `scanner.remember_ble_device`.
- When adding a **new BLE brand**, assume macOS will hand you a UUID and plan an embedded-MAC or name-suffix path before shipping decode support. A Linux-only smoke test will miss this bug.

## Conventions

- Prefer small, focused changes; match existing module style.
- Target Python **3.9+** (use `tomli` fallback for TOML on &lt; 3.11; keep `bleak>=0.22` generally, and older `bleak` + pure-Python `dbus-fast` on `armv6l`).
- Do not commit `config.toml`, `venv/`, `*.log`, or `data/*.db`.
- Do not invent cloud/Govee HTTP APIs — collection is BLE advertisement decode only (H5075 / H5179 / SwitchBot Meter family).
- After dependency changes, update `requirements.txt`.
- Keep the UI simple: overview table + compare charts; avoid heavy frameworks.
- **Map topology graph** (`static/app.js`): no overlapping nodes, no crossing connections, keep labels/locks off the viewBox edges, and show **façade nodes only for rooms with exterior windows** (beside those rooms). See `.cursor/rules/map-graph-layout.mdc`.
- **Apartment geometry**: ceiling ≈ **2.5 m**, interior door frames ≈ **2.0 m** (`apartment.ceiling_m` / `apartment.door_height_m`). Cross-section doors run floor→lintel with a transom above; categorical high/mid/low map onto transom / mid-door / near-floor. See `.cursor/rules/apartment-geometry.mdc`.
- After adding or changing settings in `config.example.toml` / `DEFAULTS`, **also update the local gitignored `config.toml`** when it exists: merge new keys with the documented defaults (enable new optional features that are on by default in the example). Do not overwrite existing user values, secrets, labels, peers, or paths. Mention a restart if the running service must reload config.
- **Web notifications** (window alerts): HTTPS + root `/sw.js` + `registration.showNotification()`; Safari standalone quirks and diagnostic UX are documented in the personal Cursor skill `web-notifications` (see `~/.cursor/skills/web-notifications/SKILL.md`).

## Useful commands

```bash
make install                 # venv + deps + config.toml from example if missing
make run                     # stop local instance if any, then collector + web UI
make serve                   # stop local instance if any, then web UI only
make stop-local              # stop leftover local govee_charts.main processes
make discover                # 30s BLE discovery then exit
sudo make systemd-install    # Linux: systemd service, starts on boot
make launchd-install         # macOS: LaunchAgent, starts at login
make restart                 # restart background service (systemd or launchd)
```
