"""SAL Pixie BLE mesh integration for Home Assistant."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from pigsydust import PixieClient

from .const import CONF_MESH_PASSWORD, DOMAIN, MESH_NAME

if TYPE_CHECKING:
    from .coordinator import PixieCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.SELECT, Platform.NUMBER, Platform.BUTTON, Platform.SENSOR]

ATTR_MODE = "mode"
ATTR_BRIGHTNESS = "brightness"
SERVICE_SET_INDICATOR = "set_indicator"
SERVICE_ALL_ON = "all_on"
SERVICE_ALL_OFF = "all_off"

LED_OFF = "Off"
LED_BLUE = "Blue"
LED_ORANGE = "Orange"
LED_PURPLE = "Purple"


@dataclass
class SalPixieRuntimeData:
    """Runtime state attached to the config entry."""

    client: PixieClient
    coordinator: "PixieCoordinator"
    password: str
    mesh_mode: str = LED_OFF
    mesh_brightness: int = 15
    device_modes: dict[int, str] = field(default_factory=dict)
    device_brightness: dict[int, int] = field(default_factory=dict)


type SalPixieConfigEntry = ConfigEntry[SalPixieRuntimeData]


def _find_best_pixie_device(hass: HomeAssistant) -> str | None:
    """Find the highest-RSSI Pixie device visible to HA's bluetooth stack."""
    best_address: str | None = None
    best_rssi = -999

    for info in async_discovered_service_info(hass, connectable=True):
        if 0x0211 not in (info.manufacturer_data or {}):
            continue

        _LOGGER.debug(
            "Pixie candidate: %s (%s) RSSI=%d",
            info.address, info.name, info.rssi,
        )

        if info.rssi > best_rssi:
            best_rssi = info.rssi
            best_address = info.address

    if best_address:
        _LOGGER.debug("Selected Pixie device: %s (RSSI=%d)", best_address, best_rssi)
    return best_address


async def _connect_and_login(
    hass: HomeAssistant,
    password: str,
    disconnect_callback: Callable[..., None] | None = None,
) -> PixieClient:
    """Connect to the best available Pixie device."""
    address = _find_best_pixie_device(hass)
    if address is None:
        raise ConfigEntryNotReady("No Pixie mesh device found via HA bluetooth")

    client = PixieClient(address, disconnect_callback=disconnect_callback)
    try:
        await client.connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Connection to {address} failed: {err}") from err

    try:
        await client.login(MESH_NAME, password)
    except Exception as err:
        await client.disconnect()
        raise ConfigEntryNotReady(f"Login failed: {err}") from err

    return client


async def async_setup_entry(hass: HomeAssistant, entry: SalPixieConfigEntry) -> bool:
    """Set up SAL Pixie from a config entry."""
    from .coordinator import PixieCoordinator

    password = entry.data[CONF_MESH_PASSWORD]

    client = await _connect_and_login(hass, password)

    coordinator = PixieCoordinator(hass, entry, client)
    client.set_disconnect_callback(coordinator._on_disconnect)
    await coordinator.async_config_entry_first_refresh()
    coordinator._known_addresses = set(coordinator.data or {})

    entry.runtime_data = SalPixieRuntimeData(
        client=client,
        coordinator=coordinator,
        password=password,
    )

    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SalPixieConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = entry.runtime_data
        await runtime.coordinator.async_shutdown()
        await runtime.client.disconnect()
    return unload_ok


def _get_runtime(hass: HomeAssistant) -> SalPixieRuntimeData:
    """Return the loaded runtime data, or raise if the integration isn't loaded."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ValueError("SAL Pixie integration is not configured or not yet loaded")
    return entries[0].runtime_data


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_INDICATOR):
        return

    async def handle_set_indicator(call: ServiceCall) -> None:
        client = _get_runtime(hass).client
        mode = call.data[ATTR_MODE]
        brightness = call.data.get(ATTR_BRIGHTNESS, 15)

        if mode == "off":
            await client.reset_led()
            await client.set_led_blue(0xFFFF, False)
            await client.set_led_orange(0xFFFF, 0)
        elif mode == "blue":
            await client.set_led_blue(0xFFFF, True)
        elif mode == "orange":
            await client.set_led_orange(0xFFFF, brightness)
        elif mode == "purple":
            await client.set_led_purple(0xFFFF, brightness)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INDICATOR,
        handle_set_indicator,
        schema=vol.Schema(
            {
                vol.Required(ATTR_MODE): vol.In(["off", "blue", "orange", "purple"]),
                vol.Optional(ATTR_BRIGHTNESS, default=15): vol.All(
                    int, vol.Range(min=0, max=15)
                ),
            }
        ),
    )

    async def handle_all_on(call: ServiceCall) -> None:
        await _get_runtime(hass).client.turn_on(0xFFFF)

    async def handle_all_off(call: ServiceCall) -> None:
        await _get_runtime(hass).client.turn_off(0xFFFF)

    hass.services.async_register(DOMAIN, SERVICE_ALL_ON, handle_all_on)
    hass.services.async_register(DOMAIN, SERVICE_ALL_OFF, handle_all_off)
