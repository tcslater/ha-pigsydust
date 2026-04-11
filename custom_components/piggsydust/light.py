"""Light platform for SAL Pixie devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from piggsydust import DeviceStatus
from piggsydust.const import DEVICE_TYPE_GATEWAY

from .const import DOMAIN
from .coordinator import PixieCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up light entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PixieCoordinator = data["coordinator"]
    client = data["client"]

    entities = [
        PixieLight(coordinator, entry, address, status, client)
        for address, status in (coordinator.data or {}).items()
    ]
    async_add_entities(entities, update_before_add=False)


class PixieLight(CoordinatorEntity[PixieCoordinator], LightEntity):
    """A SAL Pixie wall switch exposed as a light."""

    has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: PixieCoordinator,
        entry: ConfigEntry,
        address: int,
        status: DeviceStatus,
        client,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}"

        is_gateway = status.device_type == DEVICE_TYPE_GATEWAY
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
            name=f"Pixie {'Gateway' if is_gateway else 'Switch'} {address}",
            manufacturer="SAL",
            model="Pixie",
            sw_version=client.firmware_version,
            hw_version=client.hardware_version,
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        status = self.coordinator.data.get(self._address)
        if status is None:
            return None
        return status.is_on

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self.coordinator.data is None:
            return False
        return self._address in self.coordinator.data

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.turn_on(self._address)
        except ConnectionError:
            await self.coordinator.reconnect_and_retry(
                lambda c: c.turn_on(self._address)
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.turn_off(self._address)
        except ConnectionError:
            await self.coordinator.reconnect_and_retry(
                lambda c: c.turn_off(self._address)
            )
