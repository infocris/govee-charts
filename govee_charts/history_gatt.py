"""GATT download of onboard Govee H5075/H5179 minute history."""

from __future__ import annotations

import asyncio
import logging
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from govee_charts.address import (
    is_ble_mac,
    mac_address_suffix,
    name_mac_suffix,
    register_mac,
)
from govee_charts.decode import decode_advertisement
from govee_charts.gatt_crypto import (
    PRESHARED_KEY,
    UUID_AUTH_NOTIFY,
    UUID_AUTH_SERVICE,
    UUID_AUTH_WRITE,
    open_packet,
    seal,
)

logger = logging.getLogger(__name__)

UUID_CTRL = "494e5445-4c4c-495f-524f-434b535f2011"
UUID_REQ = "494e5445-4c4c-495f-524f-434b535f2012"
UUID_DATA = "494e5445-4c4c-495f-524f-434b535f2013"

# Max onboard span documented for H5075-class devices (~20 days).
MAX_HISTORY_MINUTES = 0x7080  # 28800


def xor_checksum(payload: bytes) -> int:
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF


def build_history_request(start_min: int, end_min: int) -> bytearray:
    """start_min >= end_min (both minutes ago). end_min=1 → until 1 min ago."""
    if start_min < end_min:
        raise ValueError("start_min must be >= end_min")
    if start_min > MAX_HISTORY_MINUTES:
        start_min = MAX_HISTORY_MINUTES
    if end_min < 1:
        end_min = 1
    pkt = bytearray(20)
    pkt[0] = 0x33
    pkt[1] = 0x01
    pkt[2:4] = struct.pack(">H", int(start_min))
    pkt[4:6] = struct.pack(">H", int(end_min))
    pkt[19] = xor_checksum(pkt[:19])
    return pkt


def build_keepalive() -> bytearray:
    pkt = bytearray(20)
    pkt[0] = 0xAA
    pkt[1] = 0x01
    pkt[19] = xor_checksum(pkt[:19])
    return pkt


def build_battery_request() -> bytearray:
    pkt = bytearray(20)
    pkt[0] = 0xAA
    pkt[1] = 0x08
    pkt[19] = xor_checksum(pkt[:19])
    return pkt


def decode_measurement(raw3: bytes) -> tuple[float, float] | None:
    if len(raw3) != 3 or raw3 == b"\xff\xff\xff":
        return None
    # Trailing padding / unused slots often look like 0x000000.
    if raw3 == b"\x00\x00\x00":
        return None
    raw = int.from_bytes(b"\x00" + raw3, "big")
    negative = bool(raw & 0x800000)
    if negative:
        raw ^= 0x800000
    temp_c = int(raw / 1000) / 10.0
    if negative:
        temp_c = -temp_c
    humidity = (raw % 1000) / 10.0
    # Indoor/outdoor Govee history; keep tighter than the absolute sensor limits
    # so ciphertext mis-decoded as measurements is dropped.
    if not (-30.0 <= temp_c <= 55.0 and 1.0 <= humidity <= 99.0):
        return None
    return temp_c, humidity


@dataclass
class HistorySample:
    ts: float
    temperature_c: float
    humidity: float
    minutes_ago: int


@dataclass
class HistoryDownloadResult:
    address: str
    samples: list[HistorySample] = field(default_factory=list)
    battery: int | None = None
    rssi: int | None = None
    duration_s: float = 0.0
    notifications: int = 0
    error: str | None = None


ProgressCallback = Callable[[HistorySample, int], None]


async def download_history(
    address: str,
    *,
    start_min: int,
    end_min: int = 1,
    timeout: float = 25.0,
    fallback_battery: int | None = None,
    on_sample: ProgressCallback | None = None,
    now: float | None = None,
    device: BLEDevice | None = None,
    suffix_map: dict[str, str] | None = None,
) -> HistoryDownloadResult:
    """
    Connect and download minute history for [end_min, start_min] minutes ago.

    Timestamps are absolute unix seconds derived from `now` (default: time.time()).

    ``device`` may be a recently seen Bleak BLEDevice (preferred on macOS, where
    CoreBluetooth addresses are UUIDs rather than the canonical BLE MAC).
    """
    address = address.strip().upper()
    result = HistoryDownloadResult(address=address)
    t_wall = float(now if now is not None else time.time())
    t0 = time.perf_counter()

    if device is None:
        try:
            device, last_exc = await _find_device_resolved(
                address, timeout=timeout, suffix_map=suffix_map
            )
            if last_exc is not None and device is None:
                result.error = f"scan failed: {last_exc}"
                result.duration_s = time.perf_counter() - t0
                return result
        except Exception as exc:
            result.error = f"scan failed: {exc}"
            result.duration_s = time.perf_counter() - t0
            return result

    if device is None:
        result.error = "not found in scan"
        result.duration_s = time.perf_counter() - t0
        return result

    rssi = getattr(device, "rssi", None)
    if rssi is not None and rssi != 0:
        try:
            result.rssi = int(rssi)
        except (TypeError, ValueError):
            result.rssi = None

    samples_raw: list[tuple[int, float, float]] = []
    done = asyncio.Event()
    ack = asyncio.Event()
    battery_event = asyncio.Event()
    auth_rx1 = asyncio.Event()
    auth_rx2 = asyncio.Event()
    notif_count = 0
    keepalives = 0
    battery_val: int | None = None
    session_key: bytes | None = None

    def _decrypt_data(raw: bytes) -> bytes:
        """History data packets: always decrypt when a session key is active.

        Do not heuristic-match on the first byte — for offsets ≥ 256 it is
        0x01/0x02/… and an older check wrongly fell back to ciphertext, which
        decoded as absurd temperatures.
        """
        if session_key is None or len(raw) != 20:
            return raw
        try:
            return open_packet(raw, session_key)
        except Exception:
            return raw

    def _decrypt_command(raw: bytes) -> bytes:
        """Command notifications (ack / ee 01 / aa …): decrypt + checksum check."""
        if session_key is None or len(raw) != 20:
            return raw
        try:
            plain = open_packet(raw, session_key)
            if xor_checksum(plain[:19]) == plain[19]:
                return plain
        except Exception:
            pass
        if xor_checksum(raw[:19]) == raw[19]:
            return raw
        return raw

    def on_data(_handle: int, data: bytearray) -> None:
        nonlocal notif_count
        notif_count += 1
        raw = _decrypt_data(bytes(data))
        if len(raw) < 5:
            return
        offset = int.from_bytes(raw[0:2], "big")
        payload = raw[2:]
        for i in range(0, min(len(payload), 18), 3):
            chunk = payload[i : i + 3]
            if len(chunk) < 3:
                break
            decoded = decode_measurement(chunk)
            if decoded is None:
                continue
            minutes_ago = offset - (i // 3)
            if minutes_ago < 0:
                continue
            samples_raw.append((minutes_ago, decoded[0], decoded[1]))
            if on_sample is not None:
                sample = HistorySample(
                    ts=t_wall - minutes_ago * 60.0,
                    temperature_c=decoded[0],
                    humidity=decoded[1],
                    minutes_ago=minutes_ago,
                )
                try:
                    on_sample(sample, notif_count)
                except Exception:
                    logger.exception("history on_sample callback failed")

    def on_req(_handle: int, data: bytearray) -> None:
        nonlocal battery_val
        raw = _decrypt_command(bytes(data))
        if len(raw) >= 2 and raw[0] == 0x33 and raw[1] == 0x01:
            ack.set()
        if len(raw) >= 2 and raw[0] == 0xEE and raw[1] == 0x01:
            done.set()
        if len(raw) >= 3 and raw[0] == 0xAA and raw[1] == 0x08:
            batt = int(raw[2])
            if 0 <= batt <= 100:
                battery_val = batt
                battery_event.set()

    def on_ctrl(_handle: int, data: bytearray) -> None:
        nonlocal battery_val
        raw = _decrypt_command(bytes(data))
        if len(raw) >= 3 and raw[0] == 0xAA and raw[1] == 0x08:
            batt = int(raw[2])
            if 0 <= batt <= 100:
                battery_val = batt
                battery_event.set()

    def on_auth(_handle: int, data: bytearray) -> None:
        nonlocal session_key
        raw = bytes(data)
        if len(raw) != 20:
            return
        try:
            plain = open_packet(raw, PRESHARED_KEY)
        except Exception:
            return
        if plain[0] == 0xE7 and plain[1] == 0x01:
            session_key = bytes(plain[2:18])
            auth_rx1.set()
        elif plain[0] == 0xE7 and plain[1] == 0x02:
            auth_rx2.set()

    async def keepalive_loop(client: BleakClient) -> None:
        nonlocal keepalives
        while not done.is_set():
            await asyncio.sleep(2.0)
            if done.is_set() or not client.is_connected:
                break
            if notif_count > 0 and notif_count // 75 >= keepalives:
                try:
                    await client.write_gatt_char(
                        UUID_REQ,
                        seal(build_keepalive(), session_key),
                        response=False,
                    )
                    keepalives += 1
                except Exception as exc:
                    logger.debug("keepalive failed: %s", exc)
                    break

    async def auth_handshake(client: BleakClient) -> None:
        nonlocal session_key
        services = client.services
        if services.get_service(UUID_AUTH_SERVICE) is None:
            return
        if services.get_characteristic(UUID_AUTH_WRITE) is None:
            return
        if services.get_characteristic(UUID_AUTH_NOTIFY) is None:
            return
        await client.start_notify(UUID_AUTH_NOTIFY, on_auth)
        try:
            await client.write_gatt_char(
                UUID_AUTH_WRITE,
                seal(bytearray([0xE7, 0x01]), PRESHARED_KEY),
                response=False,
            )
            await asyncio.wait_for(auth_rx1.wait(), timeout=8.0)
            await client.write_gatt_char(
                UUID_AUTH_WRITE,
                seal(bytearray([0xE7, 0x02]), PRESHARED_KEY),
                response=False,
            )
            try:
                await asyncio.wait_for(auth_rx2.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                # TX2 ack is nice-to-have; session key from RX1 is enough.
                pass
            if session_key is not None:
                logger.info(
                    "GATT auth OK for %s (encrypted session)",
                    address,
                )
        except asyncio.TimeoutError as exc:
            raise RuntimeError("GATT auth handshake timeout") from exc

    try:
        async with BleakClient(device, timeout=timeout) as client:
            await client.start_notify(UUID_DATA, on_data)
            await client.start_notify(UUID_REQ, on_req)
            try:
                await client.start_notify(UUID_CTRL, on_ctrl)
            except Exception:
                logger.debug("CTRL notify unavailable on %s", address)

            try:
                await auth_handshake(client)
            except Exception as exc:
                result.error = f"gatt auth failed: {exc}"
                result.duration_s = time.perf_counter() - t0
                return result

            # Battery once per session.
            try:
                await client.write_gatt_char(
                    UUID_CTRL,
                    seal(build_battery_request(), session_key),
                    response=False,
                )
                try:
                    await asyncio.wait_for(battery_event.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    pass
            except Exception as exc:
                logger.debug("battery query failed on %s: %s", address, exc)

            req = seal(build_history_request(start_min, end_min), session_key)
            try:
                await client.write_gatt_char(UUID_REQ, req, response=False)
            except Exception:
                await client.write_gatt_char(UUID_REQ, req, response=True)

            try:
                await asyncio.wait_for(ack.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.debug("No 33 01 ack from %s", address)

            ka_task = asyncio.create_task(keepalive_loop(client))
            wait_s = max(20.0, min(600.0, (start_min - end_min) * 0.35 + 25.0))
            try:
                await asyncio.wait_for(done.wait(), timeout=wait_s)
            except asyncio.TimeoutError:
                result.error = "timeout waiting for ee 01"
            finally:
                done.set()
                ka_task.cancel()
                try:
                    await ka_task
                except asyncio.CancelledError:
                    pass

            try:
                await client.stop_notify(UUID_DATA)
                await client.stop_notify(UUID_REQ)
            except Exception:
                pass
            try:
                await client.stop_notify(UUID_CTRL)
            except Exception:
                pass
            try:
                await client.stop_notify(UUID_AUTH_NOTIFY)
            except Exception:
                pass
    except Exception as exc:
        detail = str(exc).strip() or repr(exc)
        result.error = f"gatt failed: {type(exc).__name__}: {detail}"
        result.duration_s = time.perf_counter() - t0
        return result

    by_min: dict[int, tuple[float, float]] = {}
    for minutes_ago, temp, hum in samples_raw:
        by_min.setdefault(minutes_ago, (temp, hum))

    ordered = sorted(by_min.items(), key=lambda x: -x[0])
    result.samples = [
        HistorySample(
            ts=t_wall - minutes_ago * 60.0,
            temperature_c=temp,
            humidity=hum,
            minutes_ago=minutes_ago,
        )
        for minutes_ago, (temp, hum) in ordered
    ]
    result.notifications = notif_count
    result.battery = battery_val if battery_val is not None else fallback_battery
    result.duration_s = time.perf_counter() - t0
    if not result.samples and result.error is None:
        result.error = "no samples decoded"
    return result


async def _find_device_resolved(
    address: str,
    *,
    timeout: float,
    suffix_map: dict[str, str] | None = None,
) -> tuple[BLEDevice | None, Exception | None]:
    """
    Locate a sensor by canonical BLE MAC.

    Tries a direct address match first (Linux BlueZ), then a detection-callback
    scan that resolves Govee ads to MAC (required on macOS CoreBluetooth).
    """
    address = address.strip().upper()
    last_exc: Exception | None = None

    # Direct match works when the platform address *is* the MAC (BlueZ).
    # On macOS CoreBluetooth, addresses are UUIDs — skip the useless MAC lookup.
    if not (sys.platform == "darwin" and is_ble_mac(address)):
        for attempt in range(2):
            try:
                device = await BleakScanner.find_device_by_address(
                    address, timeout=min(8.0, timeout)
                )
                if device is not None:
                    return device, None
                break
            except Exception as exc:
                last_exc = exc
                if "inprogress" in str(exc).lower().replace(" ", "") and attempt < 1:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                break

    # MAC-aware scan: match decoded Govee advertisement identity / name suffix.
    loop = asyncio.get_running_loop()
    found: asyncio.Future[BLEDevice] = loop.create_future()
    local_map = dict(suffix_map or {})
    try:
        target_suffix = mac_address_suffix(address) if is_ble_mac(address) else None
    except ValueError:
        target_suffix = None

    def cb(device: BLEDevice, adv: AdvertisementData) -> None:
        if found.done():
            return
        name = adv.local_name or device.name or ""
        reading = decode_advertisement(
            device.address,
            name,
            adv,
            device=device,
            suffix_map=local_map,
        )
        if reading is None:
            return
        register_mac(local_map, reading.address)
        name_suf = name_mac_suffix(name)
        matched = reading.address.upper() == address or (
            target_suffix is not None and name_suf == target_suffix
        )
        if matched and not found.done():
            found.set_result(device)

    scan_kwargs: dict[str, Any] = {"detection_callback": cb}
    if sys.platform == "darwin":
        scan_kwargs["scanning_mode"] = "active"
    scanner = BleakScanner(**scan_kwargs)
    try:
        await scanner.start()
    except Exception as exc:
        return None, last_exc or exc
    try:
        device = await asyncio.wait_for(asyncio.shield(found), timeout=timeout)
        return device, None
    except asyncio.TimeoutError:
        return None, last_exc
    except Exception as exc:
        return None, last_exc or exc
    finally:
        try:
            await scanner.stop()
        except Exception:
            pass


async def find_device(
    address: str,
    *,
    timeout: float = 15.0,
    suffix_map: dict[str, str] | None = None,
) -> tuple[BLEDevice | None, int | None]:
    """Scan for a device by canonical MAC; return (device, rssi)."""
    device, _exc = await _find_device_resolved(
        address, timeout=timeout, suffix_map=suffix_map
    )
    if device is None:
        return None, None
    rssi = getattr(device, "rssi", None)
    try:
        rssi_i = int(rssi) if rssi not in (None, 0) else None
    except (TypeError, ValueError):
        rssi_i = None
    return device, rssi_i
