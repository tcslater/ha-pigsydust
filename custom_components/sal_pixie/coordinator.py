"""Data update coordinator for SAL Pixie."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pigsydust import DeviceStatus, PixieClient
from pigsydust.crypto import LoginError

from .const import CONF_MESH_PASSWORD, DOMAIN, SIGNAL_NEW_DEVICE

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

_LOGGER = logging.getLogger(__name__)

# Poll is a fallback — push notifications are the primary state source.
# Only poll if no push updates have been received recently.
SCAN_INTERVAL = timedelta(minutes=5)

_COMMAND_GRACE_SECS = 5
_PUSH_FRESH_SECS = 120  # skip poll if push data arrived within this window

# Consecutive failed updates before we raise a user-visible repair issue.
# At SCAN_INTERVAL=5min this is ~25 minutes of sustained outage.
_UNREACHABLE_THRESHOLD = 5
_UNREACHABLE_ISSUE_ID = "mesh_unreachable"

# A device absent from every poll/push for longer than this is considered
# removed from the mesh and gets pruned from the device registry.
# Uses time.monotonic, so the clock effectively restarts on HA reload —
# a device that was already gone before a restart gets a fresh 24h grace
# window to reappear before we prune it.
_STALE_THRESHOLD = timedelta(hours=24)

# Per-device availability knobs. When a known device is missing from a
# broadcast poll, unicast-ping it to distinguish "lost in mesh noise" from
# "actually offline". Keep the timeout tight — pings run sequentially per
# missing device, so N_missing * _PING_TIMEOUT bounds the extra poll time.
_PING_TIMEOUT = 1.0
# Misses accrued before dropping a device from the merged data (flipping
# its light entity to unavailable). At SCAN_INTERVAL=5min this is ~15min
# of silence before a device ghosts out of the UI — long enough that a
# transient BLE glitch doesn't flap availability, short enough that a
# genuinely-dead device doesn't linger with stale state for 24h until
# registry prune.
_MISSES_BEFORE_OFFLINE = 3


class PixieCoordinator(DataUpdateCoordinator[dict[int, DeviceStatus]]):
    """Coordinate data updates from a Pixie mesh."""

    config_entry: "SalPixieConfigEntry"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: "SalPixieConfigEntry",
        client: PixieClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="SAL Pixie",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
            always_update=False,
        )
        self.client = client
        self._unsubscribe = client.on_status_update(self._on_push_update)
        self._command_timestamps: dict[int, float] = {}
        self._last_push: float = 0
        self._disconnected: bool = False
        self._known_addresses: set[int] = set()
        self._consecutive_failures: int = 0
        self._issue_raised: bool = False
        self._last_seen: dict[int, float] = {}
        self._miss_counts: dict[int, int] = {}

    def mark_commanded(self, address: int) -> None:
        """Mark a device as recently commanded (suppresses poll overwrite)."""
        self._command_timestamps[address] = time.monotonic()

    def seed_from_registry(self) -> None:
        """Seed ``_last_seen`` and ``_known_addresses`` from the device registry.

        Called once before the first refresh so that devices the registry
        remembers from a previous HA session start with a fresh 24h clock
        *and* are eligible for unicast-ping gap-fill if they don't respond
        to the initial 0xDC broadcast. Without the ``_known_addresses``
        seed, a device offline at startup would stay unavailable until it
        happened to push a status itself — quiet devices could sit dark
        for the full 24h prune window.
        """
        now = time.monotonic()
        registry = dr.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        prefix = f"{entry_id}_"
        for device in dr.async_entries_for_config_entry(registry, entry_id):
            for domain, identifier in device.identifiers:
                if domain != DOMAIN or not identifier.startswith(prefix):
                    continue
                suffix = identifier[len(prefix):]
                # The mesh-level device uses "{entry_id}_mesh" — skip it.
                if suffix == "mesh":
                    continue
                try:
                    address = int(suffix)
                except ValueError:
                    continue
                self._last_seen.setdefault(address, now)
                self._known_addresses.add(address)

    def _prune_stale_devices(self, now: float, active: dict[int, DeviceStatus]) -> None:
        """Remove device registry entries for addresses absent longer
        than ``_STALE_THRESHOLD``.

        Only runs after a successful poll (complete picture of the mesh).
        An address present in ``active`` has just been stamped and cannot
        be stale — the ``addr not in active`` guard is belt-and-braces.
        """
        threshold = now - _STALE_THRESHOLD.total_seconds()
        stale = [
            addr
            for addr, last_seen in self._last_seen.items()
            if last_seen < threshold and addr not in active
        ]
        if not stale:
            return

        registry = dr.async_get(self.hass)
        for address in stale:
            identifier = (DOMAIN, f"{self.config_entry.entry_id}_{address}")
            device = registry.async_get_device(identifiers={identifier})
            age = now - self._last_seen[address]
            if device is not None:
                _LOGGER.info(
                    "Pruning stale device: address=%d (last seen %.0fh ago)",
                    address, age / 3600,
                )
                registry.async_remove_device(device.id)
            self._last_seen.pop(address, None)
            self._known_addresses.discard(address)
            if self.data is not None:
                self.data.pop(address, None)

    def _note_failure(self) -> None:
        """Track a failed update; raise a repair issue once the threshold is hit."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= _UNREACHABLE_THRESHOLD and not self._issue_raised:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                _UNREACHABLE_ISSUE_ID,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=_UNREACHABLE_ISSUE_ID,
                data={"entry_id": self.config_entry.entry_id},
            )
            self._issue_raised = True

    def _note_success(self) -> None:
        """Clear the failure counter and resolve the repair issue if one is up."""
        self._consecutive_failures = 0
        if self._issue_raised:
            ir.async_delete_issue(self.hass, DOMAIN, _UNREACHABLE_ISSUE_ID)
            self._issue_raised = False

    def _check_new_devices(self, data: dict[int, DeviceStatus]) -> None:
        """Fire a dispatcher signal for each newly discovered device.

        Accumulate into ``_known_addresses`` rather than replacing it —
        any single poll or push may only carry a subset of the mesh,
        so wholesale-replace would drop and then re-add every device
        that happened to be absent from the current data, firing a
        spurious "new device" event on every such round trip.
        Stale-device pruning is a separate concern (Stage 6c).
        """
        new = set(data) - self._known_addresses
        if not new:
            return
        self._known_addresses.update(new)
        for address in new:
            _LOGGER.info("New device discovered: address=%d", address)
            async_dispatcher_send(
                self.hass,
                SIGNAL_NEW_DEVICE.format(entry_id=self.config_entry.entry_id),
                address,
            )

    def _on_push_update(self, status: DeviceStatus) -> None:
        now = time.monotonic()
        self._last_push = now
        self._last_seen[status.address] = now
        self._miss_counts.pop(status.address, None)
        if self.data is None:
            self.data = {}
        existing = self.data.get(status.address)
        if existing is not None and status.is_on is None and existing.is_on is not None:
            status = replace(status, is_on=existing.is_on)
        self.data[status.address] = status
        self._check_new_devices(self.data)
        self.async_set_updated_data(self.data)

    def _on_disconnect(self, *_args: Any) -> None:
        """Called when the BLE connection drops."""
        self._disconnected = True
        # Flip last_update_success=False so every CoordinatorEntity.available
        # returns False within this tick. Keep self.data intact — a transient
        # BLE glitch shouldn't erase last-known state for quiet devices that
        # may not reappear in the reconnect's initial login burst.
        self.async_set_update_error(UpdateFailed("BLE disconnected"))
        # Without this, the reconnect only fires on the next scheduled
        # poll (up to SCAN_INTERVAL = 5 minutes away). Requesting a
        # refresh now collapses that window to a few seconds.
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> dict[int, DeviceStatus]:
        # If disconnected, reconnect immediately.
        if self._disconnected:
            self._disconnected = False
            _LOGGER.debug("Attempting reconnect after disconnect")
            await self._try_reconnect()
            if not self.client.is_connected:
                if self.last_update_success:
                    _LOGGER.warning("SAL Pixie mesh connection lost")
                self._note_failure()
                raise UpdateFailed("BLE disconnected — reconnecting")

        # Skip poll only if *every* known device has pushed within the
        # freshness window. A chatty subset isn't evidence the quiet ones
        # are still alive — if we skip based on the chatty ones' pushes,
        # quiet devices never get refreshed and eventually fall off
        # (_STALE_THRESHOLD prunes them from the registry after 24h).
        now = time.monotonic()
        stale_cutoff = now - _PUSH_FRESH_SECS
        all_fresh = bool(self.data) and bool(self._known_addresses) and all(
            self._last_seen.get(addr, 0) > stale_cutoff
            for addr in self._known_addresses
        )
        _LOGGER.debug(
            "Poll check: data=%d devices, known=%d, all_fresh=%s",
            len(self.data) if self.data else 0,
            len(self._known_addresses),
            all_fresh,
        )
        if all_fresh:
            _LOGGER.debug("Skipping poll — all %d known devices fresh", len(self._known_addresses))
            return self.data

        try:
            result = await self.client.query_status()
        except LoginError as err:
            raise ConfigEntryAuthFailed from err
        except ConnectionError as err:
            # last_update_success still reflects the *previous* call's
            # outcome at this point, so logging it here gates the warning
            # to the moment we transition from healthy to unhealthy.
            if self.last_update_success:
                _LOGGER.warning("SAL Pixie mesh connection lost: %s", err)
            await self._try_reconnect()
            self._note_failure()
            raise UpdateFailed(f"BLE connection lost: {err}") from err
        except Exception as err:
            self._note_failure()
            raise UpdateFailed(f"Error querying status: {err}") from err

        # If we're here, the poll succeeded — log the recovery transition
        # (only on the edge from unhealthy to healthy) and clear any
        # mesh-unreachable repair issue.
        if not self.last_update_success:
            _LOGGER.info("SAL Pixie mesh connection restored")
        self._note_success()

        # Fill gaps with unicast pings. A device missing from the 0xDC
        # burst may have just lost its slot in the broadcast response —
        # a unicast 0xDA → 0xDB round-trip distinguishes that from a
        # genuinely offline device. Missing addresses that also fail to
        # ping accrue a miss count and eventually drop out of merged
        # data (flipping the light entity to unavailable).
        missing = [
            addr for addr in self._known_addresses
            if addr not in result
            and now - self._command_timestamps.get(addr, 0) > _COMMAND_GRACE_SECS
        ]
        if missing:
            await self._fill_gaps_with_ping(missing, result)

        # Stamp every address that responded in this poll. Devices that
        # didn't respond keep their old timestamp and will eventually
        # cross the stale threshold. Pushes also stamp, so a heartbeat
        # alone is enough to keep a device alive.
        for addr in result:
            self._last_seen[addr] = now

        # Merge with existing data. Skip poll results for recently
        # commanded devices (grace period prevents stale overwrite).
        if self.data:
            merged = dict(self.data)
            for addr, status in result.items():
                cmd_time = self._command_timestamps.get(addr, 0)
                if now - cmd_time > _COMMAND_GRACE_SECS:
                    merged[addr] = status
        else:
            merged = dict(result)

        # Drop addresses that have exceeded the miss threshold. Keep the
        # entry in _last_seen (stale-prune still runs on the 24h clock),
        # but evicting from merged makes PixieLight.available return
        # False on the next coordinator tick.
        for addr, misses in list(self._miss_counts.items()):
            if misses >= _MISSES_BEFORE_OFFLINE:
                merged.pop(addr, None)

        self._prune_stale_devices(now, merged)
        self._check_new_devices(merged)
        return merged

    async def _fill_gaps_with_ping(
        self, missing: list[int], result: dict[int, DeviceStatus]
    ) -> None:
        """Unicast-ping each *missing* address and fold replies into *result*.

        Mutates *result* in place with any replies; updates ``_miss_counts``
        for timeouts. Pings run sequentially because the BLE command
        channel is single-threaded — parallel sends would interleave
        writes on the same characteristic and the stack doesn't queue.
        """
        for addr in missing:
            try:
                status = await self.client.ping_device(addr, timeout=_PING_TIMEOUT)
            except Exception:
                _LOGGER.debug("ping_device(%d) raised", addr, exc_info=True)
                status = None
            if status is not None:
                result[addr] = status
                self._miss_counts.pop(addr, None)
            else:
                self._miss_counts[addr] = self._miss_counts.get(addr, 0) + 1
                _LOGGER.debug(
                    "ping_device(%d) timed out (miss %d/%d)",
                    addr, self._miss_counts[addr], _MISSES_BEFORE_OFFLINE,
                )

    async def _try_reconnect(self) -> None:
        """Attempt to reconnect to the best available Pixie device."""
        from . import _connect_and_login

        password = self.config_entry.data[CONF_MESH_PASSWORD]
        runtime = self.config_entry.runtime_data

        # Silence the old client's disconnect callback before closing the
        # old bleak_client; otherwise our deliberate disconnect bounces
        # back through PixieClient._on_ble_disconnect into
        # coordinator._on_disconnect, which re-flips _disconnected=True
        # after we clear it below, causing a second reconnect cycle.
        runtime.client.set_disconnect_callback(lambda *_: None)

        # Close the old PixieClient first: on Linux it owns a raw HCI
        # socket reader and a heartbeat task, and without this they
        # linger alongside the new session's reader, double-receiving
        # every mesh packet. The old session key can't decrypt the new
        # packets → TagMismatchError spam in the log.
        try:
            await runtime.client.disconnect()
        except Exception:
            _LOGGER.debug("Disconnecting stale PixieClient failed", exc_info=True)

        if runtime.bleak_client.is_connected:
            try:
                await runtime.bleak_client.disconnect()
            except Exception:
                _LOGGER.debug("Disconnecting stale bleak_client failed", exc_info=True)

        try:
            new_client, new_bleak_client = await _connect_and_login(self.hass, password)
        except Exception:
            _LOGGER.debug("Reconnect failed, will retry next poll", exc_info=True)
            return

        new_client.set_disconnect_callback(self._on_disconnect)
        self._unsubscribe()
        self.client = new_client
        self._unsubscribe = new_client.on_status_update(self._on_push_update)
        runtime.client = new_client
        runtime.bleak_client = new_bleak_client
        self._disconnected = False
        _LOGGER.info("Reconnected successfully")

    async def reconnect_and_retry(
        self, action: Callable[[PixieClient], Awaitable[Any]]
    ) -> None:
        """Reconnect then retry an action (for use by entity commands)."""
        await self._try_reconnect()
        if self.client.is_connected:
            await action(self.client)
        else:
            raise ConnectionError("Could not reconnect to mesh")

    async def async_shutdown(self) -> None:
        self._unsubscribe()
        await super().async_shutdown()
