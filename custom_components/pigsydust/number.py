"""Number platform for Pixie Mesh indicator LED brightness."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MESH_DEVICE_INFO
from .coordinator import PixieCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up indicator brightness number entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PixieCoordinator = data["coordinator"]

    entities: list[NumberEntity] = []

    # Mesh-wide brightness.
    entities.append(PixieMeshBrightness(entry, data["client"]))

    # Per-device brightness.
    for address in (coordinator.data or {}):
        entities.append(PixieIndicatorBrightness(coordinator, entry, address))

    async_add_entities(entities, update_before_add=False)


class PixieMeshBrightness(NumberEntity):
    """Mesh-wide indicator LED brightness (0-15)."""

    has_entity_name = True
    _attr_name = "Indicator brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 0
    _attr_native_max_value = 15
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry, client) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mesh_indicator_brightness"
        self._attr_device_info = MESH_DEVICE_INFO(entry)
        self._level: int = 15

    @property
    def native_value(self) -> float:
        return float(self._level)

    async def async_set_native_value(self, value: float) -> None:
        self._level = int(value)

        # Find the mesh indicator select to get current mode.
        mode = self._get_mesh_mode()

        if mode == "Orange":
            await self._client.set_led_orange(0xFFFF, self._level)
        elif mode == "Purple":
            await self._client.set_led_purple(0xFFFF, self._level)

        # Update the mesh select's cached brightness.
        mesh_select = self._get_mesh_select()
        if mesh_select:
            mesh_select._brightness = self._level

        self.async_write_ha_state()

    def _get_mesh_select(self):
        from .select import PixieMeshIndicator
        registry = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return registry.get("mesh_indicator")

    def _get_mesh_mode(self) -> str:
        select = self._get_mesh_select()
        return select._mode if select else "Off"


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
        entry: ConfigEntry,
        address: int,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{address}_indicator_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
        )
        self._level: int = 15

    @property
    def native_value(self) -> float:
        return float(self._level)

    async def async_set_native_value(self, value: float) -> None:
        self._level = int(value)

        # Find the per-device indicator select to get current mode.
        indicator_modes = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("indicator_modes", {})
        )
        mode_entity = indicator_modes.get(self._address)

        if mode_entity:
            mode_entity._orange_level = self._level
            if mode_entity.current_option == "Orange":
                await self.coordinator.client.set_led_orange(self._address, self._level)
            elif mode_entity.current_option == "Purple":
                await self.coordinator.client.set_led_purple(self._address, self._level)

        self.async_write_ha_state()
