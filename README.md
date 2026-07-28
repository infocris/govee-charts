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

On Raspberry Pi OS with Python &lt; 3.10, `bleak` 3.x is unavailable; this project
accepts `bleak` 0.22+ on most platforms. On **armv6l** (Pi Zero / early Pi),
requirements pin `bleak` 0.19.x (pure-Python `dbus-next`) because `dbus-fast`
has no armv6 wheels.

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
