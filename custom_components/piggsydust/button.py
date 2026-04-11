"""Button platform for Pixie Mesh mesh-wide actions."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MESH_DEVICE_INFO


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up mesh-wide action buttons."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]

    async_add_entities(
        [
            PixieMeshButton(
                entry, client,
                key="all_on",
                name="All on",
                icon="mdi:lightbulb-group",
                action=lambda c: c.turn_on(0xFFFF),
            ),
            PixieMeshButton(
                entry, client,
                key="all_off",
                name="All off",
                icon="mdi:lightbulb-group-off",
                action=lambda c: c.turn_off(0xFFFF),
            ),
        ]
    )


class PixieMeshButton(ButtonEntity):
    """A mesh-wide action button."""

    has_entity_name = True

    def __init__(self, entry, client, key, name, icon, action) -> None:
        self._client = client
        self._action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_mesh_{key}"
        self._attr_device_info = MESH_DEVICE_INFO(entry)

    async def async_press(self) -> None:
        result = self._action(self._client)
        if hasattr(result, "__await__"):
            await result
