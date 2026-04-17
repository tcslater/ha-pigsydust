"""Light platform for SAL Pixie devices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pigsydust import DeviceStatus, PixieClient

from .const import DOMAIN, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "SalPixieConfigEntry",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up light entities from a config entry."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    client = runtime.client

    entities = [
        PixieLight(coordinator, entry, address, status, client)
        for address, status in (coordinator.data or {}).items()
    ]
    async_add_entities(entities, update_before_add=False)

    @callback
    def _async_add_new_device(address: int) -> None:
        status = coordinator.data.get(address) if coordinator.data else None
        if status is None:
            return
        async_add_entities(
            [PixieLight(coordinator, entry, address, status, client)],
            update_before_add=False,
        )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_DEVICE.format(entry_id=entry.entry_id),
            _async_add_new_device,
        )
    )


class PixieLight(CoordinatorEntity[PixieCoordinator], LightEntity):
    """A SAL Pixie wall switch exposed as a light."""

    has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: PixieCoordinator,
        entry: "SalPixieConfigEntry",
        address: int,
        status: DeviceStatus,
        client: PixieClient,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
            name=f"Pixie Switch {address}",
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
        self._optimistic_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.turn_off(self._address)
        except ConnectionError:
            await self.coordinator.reconnect_and_retry(
                lambda c: c.turn_off(self._address)
            )
        self._optimistic_set(False)

    def _optimistic_set(self, is_on: bool) -> None:
        """Update local state immediately after sending a command."""
        self.coordinator.mark_commanded(self._address)
        if self.coordinator.data is None:
            return
        current = self.coordinator.data.get(self._address)
        if current is not None:
            self.coordinator.data[self._address] = DeviceStatus(
                address=current.address,
                is_on=is_on,
                device_type=current.device_type,
                mac=current.mac,
            )
        self.async_write_ha_state()
