"""Data update coordinator for Pixie Mesh."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from piggsydust import DeviceStatus, PixieClient
from piggsydust.crypto import LoginError

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

# After a command, ignore poll results for this device for N seconds
# to prevent stale broadcast data from overwriting optimistic state.
_COMMAND_GRACE_SECS = 5


class PixieCoordinator(DataUpdateCoordinator[dict[int, DeviceStatus]]):
    """Coordinate data updates from a Pixie mesh."""

    def __init__(self, hass: HomeAssistant, client: PixieClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Pixie Mesh",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._unsubscribe = client.on_status_update(self._on_push_update)
        self._command_timestamps: dict[int, float] = {}  # addr -> time.monotonic()

    def mark_commanded(self, address: int) -> None:
        """Mark a device as recently commanded (suppresses poll overwrite)."""
        self._command_timestamps[address] = time.monotonic()

    def _on_push_update(self, status: DeviceStatus) -> None:
        if self.data is None:
            self.data = {}
        self.data[status.address] = status
        self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> dict[int, DeviceStatus]:
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

        # Merge with existing data. Skip poll results for devices that
        # were recently commanded (grace period prevents stale broadcast
        # data from overwriting optimistic state).
        now = time.monotonic()
        if self.data:
            merged = dict(self.data)
            for addr, status in result.items():
                cmd_time = self._command_timestamps.get(addr, 0)
                if now - cmd_time > _COMMAND_GRACE_SECS:
                    merged[addr] = status
            return merged
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
            new_client = await _connect_and_login(self.hass, password)
            self._unsubscribe()
            self.client = new_client
            self._unsubscribe = new_client.on_status_update(self._on_push_update)
            data["client"] = new_client
            _LOGGER.info("Reconnected to %s", address)
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
