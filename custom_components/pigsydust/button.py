"""Button platform for Pixie Mesh actions."""

from __future__ import annotations

import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    coordinator: PixieCoordinator = data["coordinator"]

    entities: list[ButtonEntity] = []

    # Mesh-wide buttons.
    entities.append(PixieMeshButton(
        entry, client,
        key="all_on", name="All on", icon="mdi:lightbulb-group",
        action=lambda c: c.turn_on(0xFFFF),
    ))
    entities.append(PixieMeshButton(
        entry, client,
        key="all_off", name="All off", icon="mdi:lightbulb-group-off",
        action=lambda c: c.turn_off(0xFFFF),
    ))

    # Per-device identify button.
    for address in (coordinator.data or {}):
        entities.append(PixieIdentifyButton(coordinator, entry, address))

    async_add_entities(entities, update_before_add=False)

    @callback
    def _async_add_new_device(address: int) -> None:
        async_add_entities(
            [PixieIdentifyButton(coordinator, entry, address)],
            update_before_add=False,
        )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_DEVICE.format(entry_id=entry.entry_id),
            _async_add_new_device,
        )
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


class PixieIdentifyButton(CoordinatorEntity[PixieCoordinator], ButtonEntity):
    """Per-device identify button — flashes the LED for 15 seconds.

    Press once to start, press again to stop early.
    """

    has_entity_name = True
    _attr_name = "Identify"
    _attr_icon = "mdi:flash-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: PixieCoordinator,
        entry: ConfigEntry,
        address: int,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}_identify"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
        )
        self._active = False
        self._reset_handle: asyncio.TimerHandle | None = None

    async def async_press(self) -> None:
        if self._active:
            await self.coordinator.client.find_me(self._address, start=False)
            self._cancel_timer()
            self._active = False
        else:
            await self.coordinator.client.find_me(self._address, start=True)
            self._active = True
            # Auto-reset after 15 seconds (device stops blinking on its own).
            self._cancel_timer()
            loop = self.hass.loop
            self._reset_handle = loop.call_later(15, self._auto_reset)

    def _cancel_timer(self) -> None:
        if self._reset_handle is not None:
            self._reset_handle.cancel()
            self._reset_handle = None

    def _auto_reset(self) -> None:
        self._active = False
        self._reset_handle = None
