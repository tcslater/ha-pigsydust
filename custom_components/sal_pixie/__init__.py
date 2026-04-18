"""SAL Pixie BLE mesh integration for Home Assistant."""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import voluptuous as vol
from bleak import BleakClient
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.typing import ConfigType
from pigsydust import PixieClient, parse_pixie_advert
from pigsydust.crypto import LoginError

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
    bleak_client: BleakClient
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


def _gateway_mac_for(hass: HomeAssistant, address: str) -> bytes | None:
    """Return the 6-byte mesh MAC for the given BLE address."""
    if platform.system() != "Darwin":
        # Linux/BlueZ: the BLE address string is the MAC.
        parts = address.split(":")
        if len(parts) == 6:
            try:
                return bytes(int(p, 16) for p in parts)
            except ValueError:
                return None
        return None

    # macOS/CoreBluetooth: the "address" is a CoreBluetooth UUID, so
    # recover the MAC from the manufacturer-data advert.
    for info in async_discovered_service_info(hass, connectable=True):
        if info.address != address:
            continue
        advert = parse_pixie_advert(info.manufacturer_data)
        return advert.mac if advert else None
    return None


async def _connect_and_login(
    hass: HomeAssistant,
    password: str,
) -> tuple[PixieClient, BleakClient]:
    """Resolve a BLEDevice via HA, open a connection through
    bleak-retry-connector, and hand it to PixieClient for login.

    Returns ``(pixie, bleak_client)``. The caller owns the ``bleak_client``
    and must disconnect it on unload — PixieClient's ``disconnect()`` is a
    no-op in this HA-managed mode.
    """
    address = _find_best_pixie_device(hass)
    if address is None:
        raise ConfigEntryNotReady("No Pixie mesh device found via HA bluetooth")

    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(
            f"BLE device {address} not resolvable via HA bluetooth"
        )

    # Construct PixieClient up front so we can thread its _on_ble_disconnect
    # into establish_connection as the disconnected callback.
    pixie = PixieClient(address)
    mac = _gateway_mac_for(hass, address)
    if mac is not None:
        pixie._gw_mac = mac

    try:
        bleak_client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            name=ble_device.name or "SAL Pixie",
            disconnected_callback=pixie._on_ble_disconnect,
            use_services_cache=False,
        )
    except Exception as err:
        raise ConfigEntryNotReady(f"Connection to {address} failed: {err}") from err

    pixie.set_ble_client(bleak_client)

    try:
        await pixie.login(MESH_NAME, password)
    except LoginError as err:
        # Wrong home key — surface as an auth failure so HA triggers the
        # reauth flow instead of retrying forever with the bad credential.
        if bleak_client.is_connected:
            await bleak_client.disconnect()
        raise ConfigEntryAuthFailed("Invalid home key") from err
    except Exception as err:
        if bleak_client.is_connected:
            await bleak_client.disconnect()
        raise ConfigEntryNotReady(f"Login failed: {err}") from err

    return pixie, bleak_client


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-level services once at HA startup.

    Registering here (rather than in async_setup_entry) means services
    persist across entry reloads.
    """
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SalPixieConfigEntry) -> bool:
    """Set up SAL Pixie from a config entry."""
    from .coordinator import PixieCoordinator

    password = entry.data[CONF_MESH_PASSWORD]

    client, bleak_client = await _connect_and_login(hass, password)

    coordinator = PixieCoordinator(hass, entry, client)
    client.set_disconnect_callback(coordinator._on_disconnect)
    await coordinator.async_config_entry_first_refresh()
    coordinator._known_addresses = set(coordinator.data or {})
    coordinator.seed_last_seen()

    entry.runtime_data = SalPixieRuntimeData(
        client=client,
        bleak_client=bleak_client,
        coordinator=coordinator,
        password=password,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SalPixieConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = entry.runtime_data
        await runtime.coordinator.async_shutdown()
        await runtime.client.disconnect()
        if runtime.bleak_client.is_connected:
            await runtime.bleak_client.disconnect()
    return unload_ok


def _get_runtime_data(hass: HomeAssistant) -> SalPixieRuntimeData:
    """Return the loaded runtime data, or raise if the integration isn't loaded."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError(
            "SAL Pixie integration is not configured or not yet loaded"
        )
    return cast(SalPixieRuntimeData, entries[0].runtime_data)


def _register_services(hass: HomeAssistant) -> None:
    async def handle_set_indicator(call: ServiceCall) -> None:
        client = _get_runtime_data(hass).client
        mode = call.data[ATTR_MODE]
        brightness = call.data.get(ATTR_BRIGHTNESS, 15)
        try:
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
        except ConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="mesh_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err

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
        client = _get_runtime_data(hass).client
        try:
            await client.turn_on(0xFFFF)
        except ConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def handle_all_off(call: ServiceCall) -> None:
        client = _get_runtime_data(hass).client
        try:
            await client.turn_off(0xFFFF)
        except ConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    hass.services.async_register(DOMAIN, SERVICE_ALL_ON, handle_all_on)
    hass.services.async_register(DOMAIN, SERVICE_ALL_OFF, handle_all_off)
