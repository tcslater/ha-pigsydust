"""Select platform for Pixie Mesh indicator LED mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator

PARALLEL_UPDATES = 1

LED_OFF = "Off"
LED_BLUE = "Blue"
LED_ORANGE = "Orange"
LED_PURPLE = "Purple"
LED_OPTIONS = [LED_OFF, LED_BLUE, LED_ORANGE, LED_PURPLE]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up indicator LED select entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PixieCoordinator = data["coordinator"]

    entities: list[SelectEntity] = []

    # Mesh-wide indicator select.
    mesh_indicator = PixieMeshIndicator(entry, data["client"])
    data["mesh_indicator"] = mesh_indicator
    entities.append(mesh_indicator)

    # Per-device indicator selects.
    for address in (coordinator.data or {}):
        entity = PixieIndicatorMode(coordinator, entry, address)
        entities.append(entity)

    async_add_entities(entities, update_before_add=False)

    @callback
    def _async_add_new_device(address: int) -> None:
        entity = PixieIndicatorMode(coordinator, entry, address)
        async_add_entities([entity], update_before_add=False)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_DEVICE.format(entry_id=entry.entry_id),
            _async_add_new_device,
        )
    )


class PixieMeshIndicator(SelectEntity):
    """Mesh-wide indicator LED colour mode."""

    has_entity_name = True
    _attr_name = "Indicators"
    _attr_icon = "mdi:led-on"
    _attr_options = LED_OPTIONS

    def __init__(self, entry: ConfigEntry, client) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mesh_indicator"
        self._attr_device_info = MESH_DEVICE_INFO(entry)
        self._mode: str = LED_OFF
        self._brightness: int = 15

    @property
    def current_option(self) -> str:
        return self._mode

    async def async_select_option(self, option: str) -> None:
        prev = self._mode

        if prev == LED_PURPLE and option != LED_PURPLE:
            await self._client.reset_led(0xFFFF)

        if option == LED_OFF:
            await self._client.set_led_blue(0xFFFF, False)
            await self._client.set_led_orange(0xFFFF, 0)
        elif option == LED_BLUE:
            await self._client.set_led_blue(0xFFFF, True)
        elif option == LED_ORANGE:
            await self._client.set_led_orange(0xFFFF, self._brightness)
        elif option == LED_PURPLE:
            await self._client.set_led_purple(0xFFFF, self._brightness)

        self._mode = option
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
        entry: ConfigEntry,
        address: int,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}_indicator"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
        )
        self._mode: str = LED_OFF
        self._orange_level: int = 15

        hass_data = coordinator.hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        indicator_modes = hass_data.get("indicator_modes", {})
        indicator_modes[address] = self

    @property
    def current_option(self) -> str:
        return self._mode

    async def async_select_option(self, option: str) -> None:
        client = self.coordinator.client
        prev = self._mode

        if prev == LED_PURPLE and option != LED_PURPLE:
            await client.reset_led(self._address)

        if option == LED_OFF:
            await client.set_led_blue(self._address, False)
            await client.set_led_orange(self._address, 0)
        elif option == LED_BLUE:
            await client.set_led_blue(self._address, True)
        elif option == LED_ORANGE:
            await client.set_led_orange(self._address, self._orange_level)
        elif option == LED_PURPLE:
            await client.set_led_purple(self._address, self._orange_level)

        self._mode = option
        self.async_write_ha_state()
