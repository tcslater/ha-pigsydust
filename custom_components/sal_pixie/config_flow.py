"""Config flow for SAL Pixie integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from pigsydust import PixieClient
from pigsydust.crypto import LoginError

from . import _gateway_mac_for
from .const import CONF_MESH_PASSWORD, DOMAIN, MESH_NAME

_LOGGER = logging.getLogger(__name__)


class PixieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SAL Pixie."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        # Every Pixie switch advertises the same mesh, so without
        # dedup-by-unique-id HA spawns one discovery card per switch.
        # single_config_entry:true stops a second entry being *created*
        # but doesn't dedupe in-flight flows.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._test_connection_any(user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title="SAL Pixie",
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_MESH_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._test_connection_any(user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title="SAL Pixie",
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MESH_PASSWORD): str}),
            errors=errors,
        )

    async def _test_connection_any(self, mesh_password: str) -> str | None:
        """Try connecting to Pixie devices via HA's Bluetooth stack."""
        candidates: list[tuple[int, str, str | None]] = []
        for info in async_discovered_service_info(self.hass, connectable=True):
            if 0x0211 in (info.manufacturer_data or {}):
                candidates.append((info.rssi, info.address, info.name))

        candidates.sort(reverse=True)

        if not candidates:
            _LOGGER.debug("No Pixie devices found in HA bluetooth cache")
            return "cannot_connect"

        _LOGGER.debug(
            "Found %d Pixie candidates: %s",
            len(candidates), [(a, r) for r, a, _ in candidates],
        )

        for rssi, address, name in candidates:
            _LOGGER.debug("Trying %s (%s, RSSI=%d)", address, name, rssi)

            ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
            if ble_device is None:
                _LOGGER.debug("BLE device %s not resolvable, trying next", address)
                continue

            try:
                bleak_client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    name=ble_device.name or "SAL Pixie",
                    use_services_cache=False,
                )
            except Exception:
                _LOGGER.debug("Connection to %s failed, trying next", address)
                continue

            pixie = PixieClient(address)
            mac = _gateway_mac_for(self.hass, address)
            if mac is not None:
                pixie._gw_mac = mac
            pixie.set_ble_client(bleak_client)

            _LOGGER.debug("Connected to %s, attempting login", address)
            try:
                await pixie.login(MESH_NAME, mesh_password)
                _LOGGER.debug("Login to %s successful", address)
                if bleak_client.is_connected:
                    await bleak_client.disconnect()
                return None
            except LoginError:
                if bleak_client.is_connected:
                    await bleak_client.disconnect()
                return "invalid_auth"
            except Exception:
                _LOGGER.debug("Login to %s failed, trying next", address, exc_info=True)
                if bleak_client.is_connected:
                    await bleak_client.disconnect()

        return "cannot_connect"
