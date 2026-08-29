"""GATT download of onboard SwitchBot Meter family minute history.

Uses undocumented BLE commands (0x3A / 0x3B / 0x3C) observed in the official app;
see OpenWonderLabs/SwitchBotAPI-BLE issue #37.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice

from govee_charts.history_gatt import (
    HistoryDownloadResult,
    HistorySample,
    _find_device_resolved,
)

logger = logging.getLogger(__name__)

UUID_WRITE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
UUID_READ = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

SWITCHBOT_MAGIC = 0x57
CMD_BASIC_INFO = 0x02
CMD_EXTEND = 0x0F
CMD_HISTORY_INIT = 0x3A
CMD_HISTORY_META = 0x3B
CMD_HISTORY_FETCH = 0x3C

# Onboard span (minutes): Meter 36d; Plus / Outdoor / Pro 68d.
MAX_HISTORY_MINUTES_METER = 36 * 1440
MAX_HISTORY_MINUTES_PLUS = 68 * 1440
MAX_HISTORY_MINUTES = MAX_HISTORY_MINUTES_PLUS

_SWITCHBOT_BACKFILL_MODELS = frozenset(
    {
        "switchbot-meter",
        "switchbot-meter-plus",
        "switchbot-meter-pro",
        "switchbot-meter-pro-co2",
        "switchbot-meter-outdoor",
    }
)

ProgressCallback = Callable[[HistorySample, int], None]


def is_switchbot_backfill_model(model: str | None) -> bool:
    return str(model or "").lower() in _SWITCHBOT_BACKFILL_MODELS


def max_history_minutes_for_model(model: str | None) -> int:
    m = str(model or "").lower()
    if m in ("switchbot-meter-plus", "switchbot-meter-outdoor", "switchbot-meter-pro",
             "switchbot-meter-pro-co2"):
        return MAX_HISTORY_MINUTES_PLUS
    if m == "switchbot-meter":
        return MAX_HISTORY_MINUTES_METER
    return MAX_HISTORY_MINUTES


def build_extend_command(subcmd: int, payload: bytes = b"") -> bytes:
    body = bytes([subcmd]) + payload
    if len(body) > 18:
        raise ValueError("SwitchBot GATT payload too long")
    pkt = bytearray(2 + len(body))
    pkt[0] = SWITCHBOT_MAGIC
    pkt[1] = CMD_EXTEND
    pkt[2:] = body
    return bytes(pkt)


def build_history_fetch(mode: int, offset: int, count: int) -> bytes:
    if not 0 <= mode <= 255:
        raise ValueError("mode out of range")
    if not 0 <= offset <= 0xFFFF:
        raise ValueError("offset out of range")
    if not 1 <= count <= 255:
        raise ValueError("count out of range")
    return build_extend_command(
        CMD_HISTORY_FETCH,
        bytes([mode & 0xFF, (offset >> 8) & 0xFF, offset & 0xFF, count & 0xFF]),
    )


def decode_history_record(block: bytes) -> tuple[float, float] | None:
    """Decode one 3-byte history tuple when humidity is present (LE milli-°C + %)."""
    if len(block) != 3:
        return None
    temp_milli = block[0] | (block[1] << 8)
    humidity = _history_humidity_byte(block[2])
    if humidity is None:
        return None
    temp_c = temp_milli / 1000.0
    if not (-40.0 <= temp_c <= 60.0):
        return None
    return temp_c, humidity


def _history_humidity_byte(raw: int) -> float | None:
    if 0 <= raw <= 100:
        return float(raw)
    masked = raw & 0x7F
    if 0 <= masked <= 100:
        return float(masked)
    return None


def decode_history_payload(
    payload: bytes,
    *,
    fallback_humidity: float | None = None,
) -> list[tuple[float, float]]:
    """Parse a history-fetch notification payload (status byte already stripped)."""
    out: list[tuple[float, float]] = []
    i = 0
    if payload and payload[0] in (0x97, 0x52):
        i = 1
    while i + 1 < len(payload):
        temp_milli = payload[i] | (payload[i + 1] << 8)
        temp_c = temp_milli / 1000.0
        if not (-40.0 <= temp_c <= 60.0):
            break
        hum: float | None = None
        if i + 2 < len(payload):
            hum = _history_humidity_byte(payload[i + 2])
            i += 3
        else:
            i += 2
        if hum is None:
            if fallback_humidity is not None:
                hum = float(fallback_humidity)
            else:
                break
        out.append((temp_c, hum))
    return out


def parse_history_meta(payload: bytes) -> dict[str, int]:
    """Parse 0x3B metadata (status byte already stripped)."""
    if len(payload) < 12:
        raise ValueError("short SwitchBot history meta payload")
    head = int.from_bytes(payload[0:2], "big")
    tail = int.from_bytes(payload[2:4], "big")
    batch = int.from_bytes(payload[8:10], "big")
    slot = int.from_bytes(payload[10:12], "big")
    if batch <= 0:
        batch = 10
    if slot <= 0:
        slot = 120
    return {"head": head, "tail": tail, "batch": batch, "slot": slot}


def _response_ok(status: int) -> bool:
    return status in (0x00, 0x01)


async def download_switchbot_history(
    address: str,
    *,
    start_min: int,
    end_min: int = 1,
    timeout: float = 25.0,
    fallback_battery: int | None = None,
    fallback_humidity: float | None = None,
    on_sample: ProgressCallback | None = None,
    now: float | None = None,
    device: BLEDevice | None = None,
    suffix_map: dict[str, str] | None = None,
    model: str | None = None,
) -> HistoryDownloadResult:
    """
    Connect and download minute history for [end_min, start_min] minutes ago.

    ``start_min`` is the older bound (larger minutes-ago value); ``end_min`` is newer.
    """
    address = address.strip().upper()
    result = HistoryDownloadResult(address=address)
    t_wall = float(now if now is not None else time.time())
    t0 = time.perf_counter()

    if end_min < 1:
        end_min = 1
    if start_min < end_min:
        result.error = "invalid minute window"
        result.duration_s = time.perf_counter() - t0
        return result

    cap = max_history_minutes_for_model(model)
    start_min = min(start_min, cap)
    end_min = min(end_min, start_min)

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
    notif_count = 0
    battery_val: int | None = None

    async def _exchange(
        client: BleakClient,
        command: bytes,
        *,
        wait_s: float = 8.0,
    ) -> bytes:
        nonlocal notif_count
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bytes] = loop.create_future()

        def _on_notify(_handle: int, data: bytearray) -> None:
            nonlocal notif_count
            if fut.done():
                return
            notif_count += 1
            fut.set_result(bytes(data))

        await client.start_notify(UUID_READ, _on_notify)
        try:
            await client.write_gatt_char(UUID_WRITE, command, response=False)
            return await asyncio.wait_for(fut, timeout=wait_s)
        finally:
            try:
                await client.stop_notify(UUID_READ)
            except Exception:
                pass

    try:
        async with BleakClient(device, timeout=timeout) as client:
            try:
                batt_resp = await _exchange(
                    client, bytes([SWITCHBOT_MAGIC, CMD_BASIC_INFO]), wait_s=4.0
                )
                if len(batt_resp) >= 2 and _response_ok(batt_resp[0]):
                    batt = int(batt_resp[1])
                    if 0 <= batt <= 100:
                        battery_val = batt
            except Exception as exc:
                logger.debug("SwitchBot battery query failed on %s: %s", address, exc)

            try:
                init_resp = await _exchange(
                    client, build_extend_command(CMD_HISTORY_INIT), wait_s=6.0
                )
                if not (len(init_resp) >= 1 and _response_ok(init_resp[0])):
                    logger.debug(
                        "SwitchBot history init unexpected on %s: %s",
                        address,
                        init_resp.hex(),
                    )
            except Exception as exc:
                result.error = f"history init failed: {exc}"
                result.duration_s = time.perf_counter() - t0
                return result

            try:
                meta_resp = await _exchange(
                    client,
                    build_extend_command(CMD_HISTORY_META, bytes([0x01])),
                    wait_s=8.0,
                )
            except Exception as exc:
                result.error = f"history meta failed: {exc}"
                result.duration_s = time.perf_counter() - t0
                return result

            if len(meta_resp) < 2 or not _response_ok(meta_resp[0]):
                result.error = f"history meta rejected: {meta_resp[:1].hex()}"
                result.duration_s = time.perf_counter() - t0
                return result

            try:
                meta = parse_history_meta(meta_resp[1:])
            except ValueError as exc:
                result.error = f"history meta parse: {exc}"
                result.duration_s = time.perf_counter() - t0
                return result

            batch = meta["batch"]
            offset_base = 0
            current_min = end_min
            wait_s = max(
                20.0,
                min(90.0, (start_min - end_min + 1) * 0.25 + 15.0),
            )
            deadline = time.perf_counter() + wait_s

            while current_min <= start_min and time.perf_counter() < deadline:
                offset = current_min - end_min
                count = min(batch, start_min - current_min + 1)
                cmd = build_history_fetch(0x01, offset, count)
                try:
                    fetch_resp = await _exchange(client, cmd, wait_s=10.0)
                except asyncio.TimeoutError:
                    logger.debug(
                        "SwitchBot history fetch timeout %s off=%d cnt=%d",
                        address,
                        offset,
                        count,
                    )
                    break
                except Exception as exc:
                    logger.debug(
                        "SwitchBot history fetch failed %s: %s", address, exc
                    )
                    break

                if len(fetch_resp) < 2 or not _response_ok(fetch_resp[0]):
                    break

                records = decode_history_payload(
                    fetch_resp[1:],
                    fallback_humidity=fallback_humidity,
                )
                if not records:
                    break

                for i, (temp_c, hum) in enumerate(records):
                    minutes_ago = current_min + i
                    if minutes_ago > start_min:
                        break
                    samples_raw.append((minutes_ago, temp_c, hum))
                    if on_sample is not None:
                        sample = HistorySample(
                            ts=t_wall - minutes_ago * 60.0,
                            temperature_c=temp_c,
                            humidity=hum,
                            minutes_ago=minutes_ago,
                        )
                        try:
                            on_sample(sample, notif_count)
                        except Exception:
                            logger.exception("switchbot on_sample callback failed")

                if len(records) < count:
                    break
                current_min += len(records)

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
