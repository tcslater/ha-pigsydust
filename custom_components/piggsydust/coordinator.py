"""Data update coordinator for SAL Pixie."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from piggsydust import DeviceStatus, PixieClient
from piggsydust.crypto import LoginError

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)


class PixieCoordinator(DataUpdateCoordinator[dict[int, DeviceStatus]]):
    """Coordinate data updates from a Pixie mesh."""

    def __init__(self, hass: HomeAssistant, client: PixieClient) -> None:
        """Initialise coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="SAL Pixie",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._unsubscribe = client.on_status_update(self._on_push_update)

    def _on_push_update(self, status: DeviceStatus) -> None:
        """Handle a push status notification from the mesh."""
        if self.data is None:
            self.data = {}
        self.data[status.address] = status
        self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> dict[int, DeviceStatus]:
        """Poll all device statuses."""
        try:
            return await self.client.query_status()
        except LoginError as err:
            raise ConfigEntryAuthFailed from err
        except Exception as err:
            raise UpdateFailed(f"Error querying status: {err}") from err

    async def async_shutdown(self) -> None:
        """Clean up on shutdown."""
        self._unsubscribe()
        await super().async_shutdown()
