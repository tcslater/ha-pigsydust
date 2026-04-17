"""Button platform for SAL Pixie actions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pigsydust import PixieClient

from .const import DOMAIN, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "SalPixieConfigEntry",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    runtime = entry.runtime_data
    client = runtime.client
    coordinator = runtime.coordinator

    entities: list[ButtonEntity] = [
        PixieMeshButton(
            entry, client,
            key="all_on", name="All on", icon="mdi:lightbulb-group",
            action=lambda c: c.turn_on(0xFFFF),
        ),
        PixieMeshButton(
            entry, client,
            key="all_off", name="All off", icon="mdi:lightbulb-group-off",
            action=lambda c: c.turn_off(0xFFFF),
        ),
    ]

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

    def __init__(
        self,
        entry: "SalPixieConfigEntry",
        client: PixieClient,
        key: str,
        name: str,
        icon: str,
        action: Callable[[PixieClient], Awaitable[None]],
    ) -> None:
        self._client = client
        self._action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_mesh_{key}"
        self._attr_device_info = MESH_DEVICE_INFO(entry)

    async def async_press(self) -> None:
        await self._action(self._client)


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
        entry: "SalPixieConfigEntry",
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
