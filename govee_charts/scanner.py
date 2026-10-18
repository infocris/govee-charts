"""Continuous BLE scanner that stores Govee readings."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import Callable, Sequence

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from govee_charts.ble_adapters import (
    ADAPTER_HB_INTERVAL,
    adv_heartbeat_key,
    scan_heartbeat_key,
)
from govee_charts.address import build_suffix_map, is_ble_mac, register_mac, resolve_device_address
from govee_charts.db import Database
from govee_charts.decode import Reading, decode_advertisement
from govee_charts.federation import PeerPublisher

logger = logging.getLogger(__name__)

# Bound BlueZ calls: a wedged bluetoothd can leave StartDiscovery pending forever.
_START_TIMEOUT = 30.0
_STOP_TIMEOUT = 15.0
# Never restart bluetoothd more often than this, whatever the dead-cycle count.
_BLUEZ_RECOVER_MIN_INTERVAL = 900.0
_BLUEZ_RECOVER_TIMEOUT = 60.0
# An adapter silent this long counts InProgress failures and GATT-interrupted
# scans as dead cycles too (short bursts around GATT connects stay harmless).
_SILENT_DEAD_AFTER = 600.0
DEFAULT_BLUEZ_RECOVER_COMMAND = ("systemctl", "restart", "bluetooth.service")


def _scan_mode(active: bool) -> str:
    # CoreBluetooth does not support passive scanning.
    if sys.platform == "darwin":
        return "active"
    return "active" if active else "passive"


def _scanner_kwargs(adapter: str | None, mode: str) -> dict:
    kwargs: dict = {"scanning_mode": mode}
    if adapter:
        # Always pass a fresh ``bluez`` dict: bleak 3.x copies the legacy
        # ``adapter=`` kwarg into its mutable default ``bluez={}``, so the first
        # adapter would stick to every later scanner in the process (hci1 then
        # scans hci0 and gets InProgress). Legacy ``adapter=`` stays for 0.22.
        kwargs["bluez"] = {"adapter": adapter}
        kwargs["adapter"] = adapter
    return kwargs


def _format_ble_unavailable(exc: BaseException) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    lines = [f"BLE unavailable: {msg}"]
    if sys.platform == "darwin":
        # Bleak maps a stuck "Unknown" CoreBluetooth state to "turned off",
        # which is often a missing Privacy → Bluetooth grant. Interactive
        # shells inherit the terminal's TCC grant; LaunchAgents need Python
        # itself allowed under Bluetooth privacy.
        lines.append(
            "On macOS, enable Bluetooth under "
            "System Settings → Privacy & Security → Bluetooth for "
            "Python (LaunchAgent) and/or your terminal app "
            "(Terminal, iTerm, Cursor, …). Bluetooth may already be on — "
            "without that privacy grant, CoreBluetooth stays unavailable."
        )
    return "\n".join(lines)


def _is_bluez_in_progress(exc: BaseException) -> bool:
    name = str(getattr(exc, "dbus_error", "") or getattr(exc, "error_name", "") or "")
    text = f"{name} {exc}".lower()
    return "inprogress" in text.replace(".", "").replace("_", "") or (
        "in progress" in text
    )


async def _stop_scanner(scanner: BleakScanner, label: str) -> None:
    """Stop a scanner; BlueZ often returns InProgress — retry once, then ignore."""
    try:
        await asyncio.wait_for(scanner.stop(), timeout=_STOP_TIMEOUT)
        return
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger.warning("BLE stop on %s timed out after %.0fs", label, _STOP_TIMEOUT)
        return
    except Exception as exc:
        if not _is_bluez_in_progress(exc):
            logger.warning("BLE stop on %s failed: %s", label, exc)
            return
        logger.warning(
            "BLE stop on %s: BlueZ InProgress — brief wait then retry",
            label,
        )
    await asyncio.sleep(2.0)
    try:
        await asyncio.wait_for(scanner.stop(), timeout=_STOP_TIMEOUT)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger.warning("BLE stop on %s timed out after %.0fs", label, _STOP_TIMEOUT)
    except Exception as exc:
        logger.warning("BLE stop on %s still failing: %s", label, exc)


class GoveeScanner:
    def __init__(
        self,
        db: Database,
        *,
        labels: dict[str, str] | None = None,
        sample_interval: float = 60.0,
        active: bool = True,
        retention_days: float = 30.0,
        prune_interval: float = 3600.0,
        adapters: Sequence[str] | None = None,
        publisher: PeerPublisher | None = None,
        node_id: str = "local",
        suffix_map: dict[str, str] | None = None,
        # Restart if no BLE ads arrive. Default: on for macOS (CoreBluetooth can
        # stall silently), off on Linux (BlueZ restart thrashing causes InProgress).
        stale_restart_after: float | None = None,
        # Periodic recycle even while healthy (0 = disabled). Helpful on macOS.
        recycle_after: float | None = None,
        # Restart bluetoothd after this many consecutive scan cycles without a
        # single advertisement (stale restarts / start timeouts). 0 = off.
        # Default: 3 on Linux, off elsewhere (only BlueZ can be restarted).
        bluez_recover_after: int | None = None,
        bluez_recover_command: Sequence[str] | None = None,
    ) -> None:
        self.db = db
        self.labels = {k.upper(): v for k, v in (labels or {}).items()}
        self.suffix_map = suffix_map if suffix_map is not None else build_suffix_map(self.labels)
        self.sample_interval = sample_interval
        self.active = active
        self.retention_days = retention_days
        self.prune_interval = prune_interval
        if stale_restart_after is None:
            stale_restart_after = 120.0 if sys.platform == "darwin" else 0.0
        self.stale_restart_after = max(0.0, float(stale_restart_after))
        if recycle_after is None:
            # macOS CoreBluetooth long-lived scans often go quiet; recycle proactively.
            recycle_after = 1800.0 if sys.platform == "darwin" else 0.0
        self.recycle_after = max(0.0, float(recycle_after))
        if bluez_recover_after is None:
            bluez_recover_after = 3 if sys.platform.startswith("linux") else 0
        self.bluez_recover_after = max(0, int(bluez_recover_after))
        self.bluez_recover_command = tuple(
            bluez_recover_command or DEFAULT_BLUEZ_RECOVER_COMMAND
        )
        self._bluez_recover_lock = asyncio.Lock()
        self._last_bluez_recover: float | None = None
        # Empty / None → default system adapter only
        self.adapters = [a for a in (adapters or []) if a] or [None]
        self.publisher = publisher
        self.node_id = node_id
        self._last_sample: dict[str, float] = {}
        self._latest: dict[str, Reading] = {}
        # Canonical MAC → (BLEDevice, seen_at). Needed on macOS where
        # CoreBluetooth addresses are UUIDs, not the BLE MAC we store in SQLite.
        self._ble_devices: dict[str, tuple[BLEDevice, float]] = {}
        self._lock = asyncio.Lock()
        # When set, adapter loops stop scanning so GATT connects can proceed.
        self._gatt_pause = asyncio.Event()
        self._gatt_pause_depth = 0
        self._gatt_pause_lock = asyncio.Lock()
        # Wall-clock last BLE advertisement (any device) for UI health alerts.
        self._last_adv_wall: float | None = None
        self._last_ble_hb_write: float = 0.0
        self._ble_hb_interval: float = 5.0
        # Per-adapter heartbeat key → last write (throttled like the global one).
        self._adapter_hb_writes: dict[str, float] = {}
        # Platform UUID addresses already rekeyed onto a canonical MAC this run.
        self._merged_aliases: set[str] = set()

    def remember_ble_device(self, address: str, device: BLEDevice) -> None:
        self._ble_devices[address.strip().upper()] = (device, time.time())

    def get_ble_device(
        self, address: str, *, max_age: float = 900.0
    ) -> BLEDevice | None:
        """Return a recently seen BLEDevice for a canonical MAC, if any."""
        entry = self._ble_devices.get(address.strip().upper())
        if entry is None:
            return None
        device, seen_at = entry
        if max_age > 0 and time.time() - seen_at > max_age:
            return None
        return device

    def _note_ble_activity(self) -> None:
        """Record that the adapter delivered an advertisement (throttled DB write)."""
        now = time.time()
        self._last_adv_wall = now
        if now - self._last_ble_hb_write < self._ble_hb_interval:
            return
        self._last_ble_hb_write = now
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _touch() -> None:
            try:
                await self.db.touch_runtime_heartbeat("ble")
            except Exception:
                logger.debug("BLE heartbeat failed", exc_info=True)

        loop.create_task(_touch(), name="ble-heartbeat")

    def _note_adapter_heartbeat(self, key: str) -> None:
        """Throttled per-adapter heartbeat (``ble_scan:hci0`` / ``ble_adv:hci0``)."""
        now = time.time()
        if now - self._adapter_hb_writes.get(key, 0.0) < ADAPTER_HB_INTERVAL:
            return
        self._adapter_hb_writes[key] = now
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _touch() -> None:
            try:
                await self.db.touch_runtime_heartbeat(key)
            except Exception:
                logger.debug("BLE adapter heartbeat failed", exc_info=True)

        loop.create_task(_touch(), name="ble-adapter-heartbeat")

    @property
    def gatt_paused(self) -> bool:
        return self._gatt_pause.is_set()

    async def pause_for_gatt(self) -> None:
        """Temporarily stop BLE scanning (nested-safe) for a GATT session."""
        async with self._gatt_pause_lock:
            self._gatt_pause_depth += 1
            if self._gatt_pause_depth == 1:
                self._gatt_pause.set()
                await self.db.touch_runtime_heartbeat("ble_pause")
        # Give BlueZ / adapter loops time to stop.
        await asyncio.sleep(1.0)

    async def resume_after_gatt(self) -> None:
        async with self._gatt_pause_lock:
            self._gatt_pause_depth = max(0, self._gatt_pause_depth - 1)
            if self._gatt_pause_depth == 0:
                self._gatt_pause.clear()
        await asyncio.sleep(0.5)

    def display_name(self, reading: Reading) -> str:
        if reading.address in self.labels:
            return self.labels[reading.address]
        if reading.name and reading.name.upper() != reading.address.upper():
            return reading.name
        return reading.address[-8:]

    def on_advertisement(
        self,
        device: BLEDevice,
        adv: AdvertisementData,
        *,
        adapter: str | None = None,
    ) -> None:
        name = adv.local_name or device.name or ""
        reading = decode_advertisement(
            device.address,
            name,
            adv,
            device=device,
            suffix_map=self.suffix_map,
        )
        if reading is None:
            return

        register_mac(self.suffix_map, reading.address)
        self.remember_ble_device(reading.address, device)
        platform_addr = device.address.strip().upper()
        if (
            platform_addr != reading.address
            and is_ble_mac(reading.address)
            and not is_ble_mac(platform_addr)
            and platform_addr not in self._merged_aliases
        ):
            self._merged_aliases.add(platform_addr)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._merge_platform_alias(platform_addr, reading.address),
                    name=f"alias-merge-{reading.address[-8:]}",
                )
            except RuntimeError:
                pass
        self._latest[reading.address] = reading
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.db.upsert_ble_nearby(reading),
                name=f"ble-nearby-{reading.address[-8:]}",
            )
        except RuntimeError:
            pass
        now = time.time()
        last = self._last_sample.get(reading.address, 0.0)
        if now - last < self.sample_interval:
            return

        self._last_sample[reading.address] = now
        asyncio.get_running_loop().create_task(
            self._store(reading, adapter=adapter)
        )

    async def _merge_platform_alias(self, alias: str, canonical: str) -> None:
        try:
            merged = await self.db.merge_device_alias(alias, canonical)
            if merged:
                logger.info(
                    "Merged BLE alias %s → %s (macOS UUID → MAC)",
                    alias,
                    canonical,
                )
        except Exception:
            self._merged_aliases.discard(alias)
            logger.exception("Failed to merge BLE alias %s → %s", alias, canonical)

    async def _store(
        self,
        reading: Reading,
        *,
        adapter: str | None = None,
    ) -> None:
        async with self._lock:
            name = self.display_name(reading)
            ts = time.time()
            try:
                inserted = await self.db.upsert_reading(
                    reading,
                    name,
                    ts=ts,
                    source=self.node_id,
                )
                if not inserted:
                    return
                via = f" via {adapter}" if adapter else ""
                logger.info(
                    "%s (%s) %.1f°C  %.1f%%  batt=%d%%%s",
                    name,
                    reading.model,
                    reading.temperature_c,
                    reading.humidity,
                    reading.battery,
                    via,
                )
                if self.publisher is not None:
                    self.publisher.publish(reading, ts)
            except Exception:
                logger.exception("Failed to store reading for %s", reading.address)

    async def _run_adapter(
        self,
        stop_event: asyncio.Event,
        adapter: str | None,
        mode: str,
    ) -> None:
        label = adapter or "default"
        scan_key = scan_heartbeat_key(adapter)
        adv_key = adv_heartbeat_key(adapter)
        auth_failures = 0
        in_progress_failures = 0
        # Consecutive scan cycles that ended without a single advertisement.
        dead_cycles = 0
        last_adv = time.monotonic()
        # Last advertisement on this adapter; unlike last_adv, not reset per scan.
        last_heard = last_adv

        def cb(device: BLEDevice, adv: AdvertisementData) -> None:
            nonlocal last_adv, last_heard, dead_cycles
            # Any advertisement proves the backend is still delivering events.
            last_adv = time.monotonic()
            last_heard = last_adv
            dead_cycles = 0
            self._note_ble_activity()
            self._note_adapter_heartbeat(adv_key)
            self.on_advertisement(device, adv, adapter=adapter)

        while not stop_event.is_set():
            # Yield the adapter while GATT backfill needs an exclusive connect.
            while self._gatt_pause.is_set() and not stop_event.is_set():
                try:
                    await self.db.touch_runtime_heartbeat("ble_pause")
                except Exception:
                    logger.debug("ble_pause heartbeat failed", exc_info=True)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            if stop_event.is_set():
                break

            scanner = BleakScanner(
                detection_callback=cb,
                **_scanner_kwargs(adapter, mode),
            )
            try:
                await asyncio.wait_for(scanner.start(), timeout=_START_TIMEOUT)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    break
                timed_out = isinstance(exc, asyncio.TimeoutError)
                unauthorized = (
                    isinstance(exc, BleakError)
                    and "not authorized" in str(exc).lower()
                )
                if timed_out:
                    auth_failures = 0
                    in_progress_failures = 0
                    dead_cycles += 1
                    delay = 10.0
                    logger.warning(
                        "BLE scanner on %s: start timed out after %.0fs — "
                        "retry in %.0fs",
                        label,
                        _START_TIMEOUT,
                        delay,
                    )
                    await _stop_scanner(scanner, label)
                elif unauthorized:
                    auth_failures += 1
                    in_progress_failures = 0
                    # LaunchAgents often never show a TCC prompt — log clearly
                    # once, then back off so logs stay readable.
                    delay = min(300.0, 30.0 * auth_failures)
                    if auth_failures == 1:
                        logger.error("%s", _format_ble_unavailable(exc))
                        logger.error(
                            "BLE scanner on %s will retry every %.0fs until "
                            "Bluetooth access is granted",
                            label,
                            delay,
                        )
                    else:
                        logger.warning(
                            "BLE still unauthorized on %s — retry in %.0fs",
                            label,
                            delay,
                        )
                elif _is_bluez_in_progress(exc):
                    auth_failures = 0
                    # GATT connects on the same adapter cause short InProgress
                    # bursts that must not restart BlueZ; a long silence must.
                    in_progress_failures += 1
                    if time.monotonic() - last_heard >= _SILENT_DEAD_AFTER:
                        dead_cycles += 1
                    delay = min(120.0, 15.0 * in_progress_failures)
                    logger.warning(
                        "BLE scanner on %s: BlueZ InProgress — retry in %.0fs",
                        label,
                        delay,
                    )
                else:
                    auth_failures = 0
                    in_progress_failures = 0
                    delay = 10.0
                    logger.exception(
                        "BLE scanner on %s failed — retry in %.0fs",
                        label,
                        delay,
                    )
                if await self._maybe_recover_bluez(label, dead_cycles):
                    dead_cycles = 0
                    continue
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                continue

            auth_failures = 0
            in_progress_failures = 0
            last_adv = time.monotonic()
            started = last_adv
            logger.info("BLE scanner listening on %s (mode=%s)", label, mode)
            try:
                while (
                    not stop_event.is_set() and not self._gatt_pause.is_set()
                ):
                    self._note_adapter_heartbeat(scan_key)
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                    now = time.monotonic()
                    silent_for = now - last_adv
                    if (
                        self.stale_restart_after > 0
                        and silent_for >= self.stale_restart_after
                    ):
                        logger.warning(
                            "BLE scanner on %s stale (no advertisements for "
                            "%.0fs) — restarting",
                            label,
                            silent_for,
                        )
                        if last_adv <= started:
                            dead_cycles += 1
                        break
                    if (
                        self.recycle_after > 0
                        and now - started >= self.recycle_after
                    ):
                        logger.info(
                            "BLE scanner on %s periodic recycle after %.0fs",
                            label,
                            now - started,
                        )
                        break
            finally:
                await _stop_scanner(scanner, label)

            # GATT pauses can recycle the scan before the stale check fires.
            if (
                self._gatt_pause.is_set()
                and last_adv <= started
                and time.monotonic() - last_heard >= _SILENT_DEAD_AFTER
            ):
                dead_cycles += 1
            if stop_event.is_set():
                break
            if await self._maybe_recover_bluez(label, dead_cycles):
                dead_cycles = 0
                continue
            # Brief pause between intentional restarts so BlueZ can settle.
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _maybe_recover_bluez(self, label: str, dead_cycles: int) -> bool:
        """Restart bluetoothd once a scan stays dead across several restarts.

        Recreating the BleakScanner cannot unstick a wedged bluetoothd (stop
        keeps answering InProgress, start never completes); restarting the
        daemon does, and Bleak reattaches in-process. Returns True when the
        recovery command ran, so the caller can reset its counter.
        """
        if self.bluez_recover_after <= 0 or dead_cycles < self.bluez_recover_after:
            return False
        async with self._bluez_recover_lock:
            now = time.monotonic()
            if (
                self._last_bluez_recover is not None
                and now - self._last_bluez_recover < _BLUEZ_RECOVER_MIN_INTERVAL
            ):
                return False
            self._last_bluez_recover = now
            cmd = self.bluez_recover_command
            logger.warning(
                "BLE scanner on %s: no advertisements across %d restart(s) — "
                "restarting BlueZ (%s)",
                label,
                dead_cycles,
                " ".join(cmd),
            )
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as exc:
                logger.error("BlueZ recovery command could not run: %s", exc)
                return True
            try:
                out, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=_BLUEZ_RECOVER_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.error(
                    "BlueZ recovery command timed out after %.0fs",
                    _BLUEZ_RECOVER_TIMEOUT,
                )
                return True
            if proc.returncode != 0:
                logger.error(
                    "BlueZ recovery command failed (exit %s): %s — on Linux, "
                    "re-run `sudo make systemd-install` to install the polkit "
                    "rule that lets the service restart bluetooth.service",
                    proc.returncode,
                    out.decode(errors="replace").strip(),
                )
                return True
            logger.info("BlueZ restarted; resuming BLE scan on %s", label)
            # Let bluetoothd re-register its adapters before StartDiscovery.
            await asyncio.sleep(3.0)
            return True

    async def run(self, stop_event: asyncio.Event) -> None:
        mode = _scan_mode(self.active)
        names = ", ".join(a or "default" for a in self.adapters)
        logger.info(
            "BLE scanner started (adapters=[%s], mode=%s, sample_interval=%.0fs, "
            "stale_restart=%s, recycle=%s, bluez_recover=%s)",
            names,
            mode,
            self.sample_interval,
            f"{self.stale_restart_after:.0f}s"
            if self.stale_restart_after > 0
            else "off",
            f"{self.recycle_after:.0f}s" if self.recycle_after > 0 else "off",
            f"after {self.bluez_recover_after} dead cycle(s)"
            if self.bluez_recover_after > 0
            else "off",
        )
        # Baseline so UI can alert if no ads arrive after start.
        self._last_adv_wall = time.time()
        self._last_ble_hb_write = self._last_adv_wall
        try:
            await self.db.touch_runtime_heartbeat("ble")
        except Exception:
            logger.debug("Initial BLE heartbeat failed", exc_info=True)
        pruned = await self.db.prune(self.retention_days)
        if pruned:
            logger.info("Pruned %d old reading(s)", pruned)

        last_prune = time.time()
        scan_tasks = [
            asyncio.create_task(
                self._run_adapter(stop_event, adapter, mode),
                name=f"ble-scan-{adapter or 'default'}",
            )
            for adapter in self.adapters
        ]

        try:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                now = time.time()
                if now - last_prune >= self.prune_interval:
                    deleted = await self.db.prune(self.retention_days)
                    if deleted:
                        logger.info("Pruned %d old reading(s)", deleted)
                    last_prune = now
        finally:
            for task in scan_tasks:
                task.cancel()
            await asyncio.gather(*scan_tasks, return_exceptions=True)

        logger.info("BLE scanner stopped")


async def discover_once(
    duration: float = 30.0,
    *,
    active: bool = True,
    adapters: Sequence[str] | None = None,
    on_found: Callable[[Reading], None] | None = None,
    suffix_map: dict[str, str] | None = None,
) -> dict[str, Reading]:
    """Scan for `duration` seconds and return unique decoded Govee devices."""
    found: dict[str, Reading] = {}
    adapter_list = [a for a in (adapters or []) if a] or [None]
    mode = _scan_mode(active)
    names = ", ".join(a or "default" for a in adapter_list)
    logger.info("Discovery mode — %.0f seconds on [%s]…", duration, names)

    def make_cb(adapter: str | None):
        def cb(device: BLEDevice, adv: AdvertisementData) -> None:
            name = adv.local_name or device.name or ""
            reading = decode_advertisement(
                device.address,
                name,
                adv,
                device=device,
                suffix_map=suffix_map,
            )
            if reading is None:
                return
            if reading.address in found:
                return
            found[reading.address] = reading
            via = f"  via {adapter}" if adapter else ""
            logger.info(
                "Found: %s  %s  model=%s  %.1f°C  %.1f%%  batt=%d%%  rssi=%s%s",
                reading.name,
                reading.address,
                reading.model,
                reading.temperature_c,
                reading.humidity,
                reading.battery,
                reading.rssi,
                via,
            )
            if on_found:
                on_found(reading)

        return cb

    try:
        scanners = [
            BleakScanner(
                detection_callback=make_cb(adapter),
                **_scanner_kwargs(adapter, mode),
            )
            for adapter in adapter_list
        ]
    except BleakError as exc:
        raise SystemExit(_format_ble_unavailable(exc)) from exc

    started: list[tuple[BleakScanner, str]] = []
    try:
        for scanner, adapter in zip(scanners, adapter_list):
            label = adapter or "default"
            try:
                await scanner.start()
            except BleakError as exc:
                if _is_bluez_in_progress(exc):
                    raise SystemExit(
                        "BLE discovery failed: BlueZ reports InProgress.\n"
                        "Another process is likely already scanning "
                        "(govee-charts service or bluetoothctl).\n"
                        "Stop it first, e.g.: sudo systemctl stop govee-charts"
                    ) from exc
                raise SystemExit(_format_ble_unavailable(exc)) from exc
            started.append((scanner, label))
        await asyncio.sleep(duration)
    finally:
        for scanner, label in reversed(started):
            await _stop_scanner(scanner, label)

    if not found:
        logger.warning(
            "No Govee device found. Check Bluetooth adapter, range, and power."
        )
    else:
        logger.info("Done — %d device(s)", len(found))
    return found


def short_mac(address: str) -> str:
    return address.upper()[-8:]
