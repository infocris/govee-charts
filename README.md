# Govee Charts (BLE)

Collect temperature and humidity from nearby Govee BLE thermometers, store
history in SQLite, and show charts in a local HTML dashboard.

Multiple instances can federate on the LAN: each node scans near itself and
pushes its readings to the others.

## Supported sensors

- **H5075** / H5072 (manufacturer ID `0xEC88`)
- **H5179** (manufacturer ID `0x8801`)

Auto-discovery: any Govee device advertising these payloads appears without
manual pairing.

## Requirements

- Python 3.9+ (3.11+ recommended; 3.9–3.10 need `tomli` from requirements)
- Linux Bluetooth adapter (`hci0`) within range of the sensors (unless the node
  is a hub with scanning disabled)
- Optional: second USB dongle (`hci1`) closer to distant sensors
- macOS (development): Bluetooth on, and your terminal app allowed under
  **System Settings → Privacy & Security → Bluetooth**

On Raspberry Pi OS with Python &lt; 3.10, `bleak` 3.x is unavailable; this project
accepts `bleak` 0.22+ on most platforms. On **armv6l** (Pi Zero / early Pi),
requirements pin older `bleak` + pure-Python `dbus-fast` (&lt; 1.18) because newer
`dbus-fast` has no armv6 wheels. On macOS with Python 3.9, PyObjC is capped
below 12.x (12 dropped 3.9 support).

## Install

```bash
cd ~/govee-charts
make install
# optional: edit config.toml (labels, port, retention, federation)
```

## Usage

```bash
make discover   # scan 30s, list detected Govee devices
make run        # collector + web UI
make serve      # web UI only (no BLE scanner)
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080).

## Run in the background

After `make install` and editing `config.toml`:

### Linux (systemd)

```bash
# BLE collector + web UI (starts on boot)
sudo make systemd-install

# Hub only (no local BLE scan)
sudo ./scripts/install-systemd.sh --hub install
```

Logs: `journalctl -u govee-charts -f` and `govee-charts.log` in the project directory.

Remove: `sudo make systemd-uninstall`

On Raspberry Pi, ensure the service user is in the `bluetooth` group:

```bash
sudo usermod -aG bluetooth "$USER"
```

### macOS (launchd)

```bash
# BLE collector + web UI (starts at login, no sudo)
make launchd-install

# Hub only (no local BLE scan)
./scripts/install-launchd.sh --hub install
```

Restart / status / remove:

```bash
make restart
make service-status
make launchd-uninstall
```

Logs: `govee-charts.log` and `govee-charts.launchd.log` in the project directory.

Allow Bluetooth for **Python** under
**System Settings → Privacy & Security → Bluetooth**. A LaunchAgent does not
inherit Cursor/Terminal’s Bluetooth grant — without this toggle, the web UI
stays up but local scanning fails with `BLE is not authorized`. Then:
`make restart`.

## Federation (multiple machines)

On each machine, install the project and cross-link peer URLs in `[federation]`:

```toml
[federation]
node_id = "basement"          # unique per machine
token = "shared-secret"
peers = ["http://192.168.1.10:8080"]   # the other instance
```

On the other node, `peers` points back here. Only **locally scanned** samples
are pushed to peers; ingested data is not re-forwarded (no loops).

Hub without Bluetooth (central UI only):

```toml
[scanner]
enabled = false
```

## Configuration

See `config.example.toml`:

- `scanner.enabled` — enable/disable local BLE scanning
- `scanner.sample_interval` — minimum seconds between stored samples (default 60)
- `scanner.retention_days` — history retention (default 30)
- `scanner.adapters` — BlueZ adapters (`["hci0", "hci1"]`)
- `federation.peers` — URLs of other instances
- `federation.token` — shared secret for `POST /api/ingest`
- `[labels]` — friendly names keyed by BLE MAC

## API

- `GET /api/devices` — known devices + latest reading
- `GET /api/history?address=…&hours=24` — time series
- `POST /api/ingest` — accept peer readings (`X-Govee-Token` header)
- `GET /api/health` — health + `node_id`

## Notes

- Soft-blocked Bluetooth: `rfkill unblock bluetooth`
- No Govee cloud API — BLE only
