"""Continuous BLE scanner that stores Govee readings."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from govee_charts.db import Database
from govee_charts.decode import Reading, decode_advertisement
from govee_charts.federation import PeerPublisher

logger = logging.getLogger(__name__)


def _scanner_kwargs(adapter: str | None, mode: str) -> dict:
    # Use legacy ``adapter=`` so bleak 0.22+ and 3.x both work (Pi / older Python).
    kwargs: dict = {"scanning_mode": mode}
    if adapter:
        kwargs["adapter"] = adapter
    return kwargs


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
    ) -> None:
        self.db = db
        self.labels = {k.upper(): v for k, v in (labels or {}).items()}
        self.sample_interval = sample_interval
        self.active = active
        self.retention_days = retention_days
        self.prune_interval = prune_interval
        # Empty / None → default system adapter only
        self.adapters = [a for a in (adapters or []) if a] or [None]
        self.publisher = publisher
        self.node_id = node_id
        self._last_sample: dict[str, float] = {}
        self._latest: dict[str, Reading] = {}
        self._lock = asyncio.Lock()

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
        reading = decode_advertisement(device.address, name, adv, device=device)
        if reading is None:
            return

        self._latest[reading.address] = reading
        now = time.time()
        last = self._last_sample.get(reading.address, 0.0)
        if now - last < self.sample_interval:
            return

        self._last_sample[reading.address] = now
        asyncio.get_running_loop().create_task(
            self._store(reading, adapter=adapter)
        )

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
                    self.publisher.publish(reading, name, ts)
            except Exception:
                logger.exception("Failed to store reading for %s", reading.address)

    async def _run_adapter(
        self,
        stop_event: asyncio.Event,
        adapter: str | None,
        mode: str,
    ) -> None:
        label = adapter or "default"

        def cb(device: BLEDevice, adv: AdvertisementData) -> None:
            self.on_advertisement(device, adv, adapter=adapter)

        while not stop_event.is_set():
            try:
                async with BleakScanner(
                    detection_callback=cb,
                    **_scanner_kwargs(adapter, mode),
                ):
                    logger.info("BLE scanner listening on %s (mode=%s)", label, mode)
                    while not stop_event.is_set():
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception:
                if stop_event.is_set():
                    break
                logger.exception(
                    "BLE scanner on %s failed — retry in 10s",
                    label,
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    pass

    async def run(self, stop_event: asyncio.Event) -> None:
        mode = "active" if self.active else "passive"
        names = ", ".join(a or "default" for a in self.adapters)
        logger.info(
            "BLE scanner started (adapters=[%s], mode=%s, sample_interval=%.0fs)",
            names,
            mode,
            self.sample_interval,
        )
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
) -> dict[str, Reading]:
    """Scan for `duration` seconds and return unique decoded Govee devices."""
    found: dict[str, Reading] = {}
    adapter_list = [a for a in (adapters or []) if a] or [None]
    mode = "active" if active else "passive"
    names = ", ".join(a or "default" for a in adapter_list)
    logger.info("Discovery mode — %.0f seconds on [%s]…", duration, names)

    def make_cb(adapter: str | None):
        def cb(device: BLEDevice, adv: AdvertisementData) -> None:
            name = adv.local_name or device.name or ""
            reading = decode_advertisement(device.address, name, adv, device=device)
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

    scanners = [
        BleakScanner(
            detection_callback=make_cb(adapter),
            **_scanner_kwargs(adapter, mode),
        )
        for adapter in adapter_list
    ]

    try:
        for scanner in scanners:
            await scanner.__aenter__()
        await asyncio.sleep(duration)
    finally:
        for scanner in reversed(scanners):
            await scanner.__aexit__(None, None, None)

    if not found:
        logger.warning(
            "No Govee device found. Check Bluetooth adapter, range, and power."
        )
    else:
        logger.info("Done — %d device(s)", len(found))
    return found


def short_mac(address: str) -> str:
    return address.upper()[-8:]
