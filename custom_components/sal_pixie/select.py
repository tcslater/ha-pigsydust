"""Select platform for SAL Pixie indicator LED mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pigsydust import PixieClient

from .const import DEVICE_INFO, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator

if TYPE_CHECKING:
    from . import SalPixieConfigEntry, SalPixieRuntimeData

PARALLEL_UPDATES = 1

LED_OFF = "Off"
LED_BLUE = "Blue"
LED_ORANGE = "Orange"
LED_PURPLE = "Purple"
LED_OPTIONS = [LED_OFF, LED_BLUE, LED_ORANGE, LED_PURPLE]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "SalPixieConfigEntry",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up indicator LED select entities."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator

    entities: list[SelectEntity] = [PixieMeshIndicator(entry, runtime)]
    for address in (coordinator.data or {}):
        entities.append(PixieIndicatorMode(coordinator, entry, runtime, address))

    async_add_entities(entities, update_before_add=False)

    @callback
    def _async_add_new_device(address: int) -> None:
        async_add_entities(
            [PixieIndicatorMode(coordinator, entry, runtime, address)],
            update_before_add=False,
        )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_DEVICE.format(entry_id=entry.entry_id),
            _async_add_new_device,
        )
    )


async def _apply_mode(
    client: PixieClient, address: int, prev: str, option: str, brightness: int
) -> None:
    """Send the BLE writes needed to transition from prev → option at address."""
    if prev == LED_PURPLE and option != LED_PURPLE:
        await client.reset_led(address)

    if option == LED_OFF:
        await client.set_led_blue(address, False)
        await client.set_led_orange(address, 0)
    elif option == LED_BLUE:
        await client.set_led_blue(address, True)
    elif option == LED_ORANGE:
        await client.set_led_orange(address, brightness)
    elif option == LED_PURPLE:
        await client.set_led_purple(address, brightness)


class PixieMeshIndicator(SelectEntity):
    """Mesh-wide indicator LED colour mode."""

    has_entity_name = True
    _attr_name = "Indicators"
    _attr_icon = "mdi:led-on"
    _attr_options = LED_OPTIONS

    def __init__(self, entry: "SalPixieConfigEntry", runtime: "SalPixieRuntimeData") -> None:
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_mesh_indicator"
        self._attr_device_info = MESH_DEVICE_INFO(entry)

    @property
    def current_option(self) -> str:
        return self._runtime.mesh_mode

    async def async_select_option(self, option: str) -> None:
        await _apply_mode(
            self._runtime.client,
            0xFFFF,
            self._runtime.mesh_mode,
            option,
            self._runtime.mesh_brightness,
        )
        self._runtime.mesh_mode = option
        self.async_write_ha_state()


class PixieIndicatorMode(CoordinatorEntity[PixieCoordinator], SelectEntity):
    """Per-device indicator LED colour mode."""

    has_entity_name = True
    _attr_name = "Indicator"
    _attr_icon = "mdi:led-on"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = LED_OPTIONS

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
        self._attr_unique_id = f"{entry.entry_id}_{address}_indicator"
        self._attr_device_info = DEVICE_INFO(
            entry, address, coordinator.data.get(address) if coordinator.data else None,
        )

    @property
    def current_option(self) -> str:
        return self._runtime.device_modes.get(self._address, LED_OFF)

    async def async_select_option(self, option: str) -> None:
        prev = self._runtime.device_modes.get(self._address, LED_OFF)
        brightness = self._runtime.device_brightness.get(self._address, 15)
        await _apply_mode(self.coordinator.client, self._address, prev, option, brightness)
        self._runtime.device_modes[self._address] = option
        self.async_write_ha_state()
