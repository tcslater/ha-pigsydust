"""Data update coordinator for Pixie Mesh."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pigsydust import DeviceStatus, PixieClient
from pigsydust.crypto import LoginError

_LOGGER = logging.getLogger(__name__)

# Poll is a fallback — push notifications are the primary state source.
# Only poll if no push updates have been received recently.
SCAN_INTERVAL = timedelta(minutes=5)

_COMMAND_GRACE_SECS = 5
_PUSH_FRESH_SECS = 120  # skip poll if push data arrived within this window


class PixieCoordinator(DataUpdateCoordinator[dict[int, DeviceStatus]]):
    """Coordinate data updates from a Pixie mesh."""

    def __init__(
        self, hass: HomeAssistant, client: PixieClient, entry_id: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Pixie Mesh",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._entry_id = entry_id
        self._unsubscribe = client.on_status_update(self._on_push_update)
        self._command_timestamps: dict[int, float] = {}
        self._last_push: float = 0
        self._disconnected: bool = False
        self._known_addresses: set[int] = set()

    def mark_commanded(self, address: int) -> None:
        """Mark a device as recently commanded (suppresses poll overwrite)."""
        self._command_timestamps[address] = time.monotonic()

    def _check_new_devices(self, data: dict[int, DeviceStatus]) -> None:
        """Fire a dispatcher signal for each newly discovered device."""
        from .const import SIGNAL_NEW_DEVICE

        new = set(data) - self._known_addresses
        self._known_addresses = set(data)
        for address in new:
            _LOGGER.info("New device discovered: address=%d", address)
            async_dispatcher_send(
                self.hass,
                SIGNAL_NEW_DEVICE.format(entry_id=self._entry_id),
                address,
            )

    def _on_push_update(self, status: DeviceStatus) -> None:
        self._last_push = time.monotonic()
        if self.data is None:
            self.data = {}
        self.data[status.address] = status
        self._check_new_devices(self.data)
        self.async_set_updated_data(self.data)

    def _on_disconnect(self, *_args) -> None:
        """Called when the BLE connection drops."""
        _LOGGER.warning("BLE connection lost (disconnect callback)")
        self._disconnected = True

    async def _async_update_data(self) -> dict[int, DeviceStatus]:
        # If disconnected, reconnect immediately.
        if self._disconnected:
            self._disconnected = False
            _LOGGER.info("Attempting reconnect after disconnect")
            await self._try_reconnect()
            if not self.client.is_connected:
                raise UpdateFailed("BLE disconnected — reconnecting")

        # Skip poll if push data is fresh — avoid unnecessary BLE traffic.
        # The set_utc burst during login populates data before the first
        # coordinator poll, so this also handles the initial refresh.
        now = time.monotonic()
        data_count = len(self.data) if self.data else 0
        push_age = now - self._last_push if self._last_push else -1
        _LOGGER.debug("Poll check: data=%d devices, push_age=%.1fs", data_count, push_age)
        if self.data and self._last_push and (now - self._last_push) < _PUSH_FRESH_SECS:
            _LOGGER.debug("Skipping poll — have %d devices from push", len(self.data))
            return self.data

        try:
            result = await self.client.query_status()
        except LoginError as err:
            raise ConfigEntryAuthFailed from err
        except ConnectionError:
            _LOGGER.warning("BLE connection lost, attempting reconnect")
            await self._try_reconnect()
            raise UpdateFailed("BLE connection lost — reconnecting")
        except Exception as err:
            raise UpdateFailed(f"Error querying status: {err}") from err

        # Merge with existing data. Skip poll results for recently
        # commanded devices (grace period prevents stale overwrite).
        if self.data:
            merged = dict(self.data)
            for addr, status in result.items():
                cmd_time = self._command_timestamps.get(addr, 0)
                if now - cmd_time > _COMMAND_GRACE_SECS:
                    merged[addr] = status
            self._check_new_devices(merged)
            return merged
        self._check_new_devices(result)
        return result

    async def _try_reconnect(self) -> None:
        """Attempt to reconnect to the best available Pixie device."""
        from .const import DOMAIN

        for data in self.hass.data.get(DOMAIN, {}).values():
            if data.get("client") is self.client:
                password = data["password"]
                break
        else:
            return

        try:
            from . import _connect_and_login
            new_client = await _connect_and_login(
                self.hass, password, disconnect_callback=self._on_disconnect
            )
            self._unsubscribe()
            self.client = new_client
            self._unsubscribe = new_client.on_status_update(self._on_push_update)
            data["client"] = new_client
            self._disconnected = False
            _LOGGER.info("Reconnected successfully")
        except Exception:
            _LOGGER.debug("Reconnect failed, will retry next poll", exc_info=True)

    async def reconnect_and_retry(self, action) -> None:
        """Reconnect then retry an action (for use by entity commands)."""
        await self._try_reconnect()
        if self.client.is_connected:
            await action(self.client)
        else:
            raise ConnectionError("Could not reconnect to mesh")

    async def async_shutdown(self) -> None:
        self._unsubscribe()
        await super().async_shutdown()
