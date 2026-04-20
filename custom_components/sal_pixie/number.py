"""Number platform for SAL Pixie indicator LED brightness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_INFO, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator
from .select import LED_ORANGE, LED_PURPLE

if TYPE_CHECKING:
    from . import SalPixieConfigEntry, SalPixieRuntimeData

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "SalPixieConfigEntry",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up indicator brightness number entities."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator

    entities: list[NumberEntity] = [PixieMeshBrightness(entry, runtime)]
    for address in (coordinator.data or {}):
        entities.append(PixieIndicatorBrightness(coordinator, entry, runtime, address))

    async_add_entities(entities, update_before_add=False)

    @callback
    def _async_add_new_device(address: int) -> None:
        async_add_entities(
            [PixieIndicatorBrightness(coordinator, entry, runtime, address)],
            update_before_add=False,
        )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_DEVICE.format(entry_id=entry.entry_id),
            _async_add_new_device,
        )
    )


class PixieMeshBrightness(NumberEntity):
    """Mesh-wide indicator LED brightness (0-15)."""

    has_entity_name = True
    _attr_name = "Indicator brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 0
    _attr_native_max_value = 15
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: "SalPixieConfigEntry", runtime: "SalPixieRuntimeData") -> None:
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_mesh_indicator_brightness"
        self._attr_device_info = MESH_DEVICE_INFO(entry)

    @property
    def native_value(self) -> float:
        return float(self._runtime.mesh_brightness)

    async def async_set_native_value(self, value: float) -> None:
        level = int(value)
        self._runtime.mesh_brightness = level

        if self._runtime.mesh_mode == LED_ORANGE:
            await self._runtime.client.set_led_orange(0xFFFF, level)
        elif self._runtime.mesh_mode == LED_PURPLE:
            await self._runtime.client.set_led_purple(0xFFFF, level)

        self.async_write_ha_state()


class PixieIndicatorBrightness(CoordinatorEntity[PixieCoordinator], NumberEntity):
    """Per-device indicator LED brightness (0-15)."""

    has_entity_name = True
    _attr_name = "Indicator brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 15
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: PixieCoordinator,
        entry: "SalPixieConfigEntry",
        runtime: "SalPixieRuntimeData",
        address: int,
    ) -> None:
        super().__init__(coordinator)
        self._runtime = runtime
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}_indicator_brightness"
        self._attr_device_info = DEVICE_INFO(
            entry, address, coordinator.data.get(address) if coordinator.data else None,
        )

    @property
    def native_value(self) -> float:
        return float(self._runtime.device_brightness.get(self._address, 15))

    async def async_set_native_value(self, value: float) -> None:
        level = int(value)
        self._runtime.device_brightness[self._address] = level

        mode = self._runtime.device_modes.get(self._address)
        if mode == LED_ORANGE:
            await self.coordinator.client.set_led_orange(self._address, level)
        elif mode == LED_PURPLE:
            await self.coordinator.client.set_led_purple(self._address, level)

        self.async_write_ha_state()
