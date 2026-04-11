"""Pixie Mesh BLE integration for Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol
from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from piggsydust import PixieClient

from .const import CONF_MESH_PASSWORD, DOMAIN, MESH_NAME
from .coordinator import PixieCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.SELECT, Platform.NUMBER, Platform.BUTTON, Platform.SENSOR]

ATTR_MODE = "mode"
ATTR_BRIGHTNESS = "brightness"
SERVICE_SET_INDICATOR = "set_indicator"
SERVICE_ALL_ON = "all_on"
SERVICE_ALL_OFF = "all_off"


def _find_best_pixie_device(hass: HomeAssistant) -> str | None:
    """Find the strongest Pixie BLE device visible to HA's bluetooth stack."""
    from homeassistant.components.bluetooth import async_discovered_service_info

    best_address = None
    best_rssi = -999

    for info in async_discovered_service_info(hass, connectable=True):
        if 0x0211 in (info.manufacturer_data or {}):
            if info.rssi > best_rssi:
                best_rssi = info.rssi
                best_address = info.address
                _LOGGER.debug(
                    "Pixie candidate: %s (%s) RSSI=%d",
                    info.address, info.name, info.rssi,
                )

    if best_address:
        _LOGGER.info("Selected Pixie device: %s (RSSI=%d)", best_address, best_rssi)
    return best_address


async def _connect_and_login(
    hass: HomeAssistant, password: str, disconnect_callback=None
) -> PixieClient:
    """Connect to the best available Pixie device and login."""
    address = _find_best_pixie_device(hass)
    if address is None:
        raise ConfigEntryNotReady("No Pixie mesh device found via HA bluetooth")

    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"Device {address} disappeared during connect")

    ble_client = await establish_connection(
        client_class=BleakClient,
        device=ble_device,
        name=address,
        max_attempts=3,
        disconnected_callback=disconnect_callback,
    )

    client = PixieClient(address)
    client.set_ble_client(ble_client)

    try:
        await client.login(MESH_NAME, password)
    except Exception as err:
        await ble_client.disconnect()
        raise ConfigEntryNotReady(f"Login failed: {err}") from err

    return client


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pixie Mesh from a config entry."""
    password = entry.data[CONF_MESH_PASSWORD]

    client = await _connect_and_login(hass, password)

    coordinator = PixieCoordinator(hass, client)

    # Register disconnect callback now that coordinator exists.
    if client._client is not None:
        client._client.set_disconnected_callback(coordinator._on_disconnect)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "indicator_modes": {},
        "password": password,
    }

    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["coordinator"].async_shutdown()
        await data["client"].disconnect()
    return unload_ok


def _get_client(hass: HomeAssistant) -> PixieClient:
    """Get the PixieClient from the first config entry."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        return entry_data["client"]
    raise ValueError("No Pixie Mesh integration configured")


def _register_services(hass: HomeAssistant) -> None:
    """Register custom services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_INDICATOR):
        return

    async def handle_set_indicator(call: ServiceCall) -> None:
        """Set the indicator LED on all mesh devices."""
        client = _get_client(hass)
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
        """Turn on all mesh devices."""
        client = _get_client(hass)
        await client.turn_on(0xFFFF)

    async def handle_all_off(call: ServiceCall) -> None:
        """Turn off all mesh devices."""
        client = _get_client(hass)
        await client.turn_off(0xFFFF)

    hass.services.async_register(DOMAIN, SERVICE_ALL_ON, handle_all_on)
    hass.services.async_register(DOMAIN, SERVICE_ALL_OFF, handle_all_off)
