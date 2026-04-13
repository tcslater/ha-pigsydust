"""Config flow for Pixie Mesh integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from pigsydust.crypto import LoginError

from .const import CONF_MESH_PASSWORD, DOMAIN, MESH_NAME

_LOGGER = logging.getLogger(__name__)


class PixieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pixie Mesh."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm Bluetooth discovery and get credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._test_connection_any(user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title="Pixie Mesh",
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
    ) -> FlowResult:
        """Handle manual setup — just asks for the home key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            error = await self._test_connection_any(user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title="Pixie Mesh",
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MESH_PASSWORD): str}),
            errors=errors,
        )

    async def _test_connection_any(self, mesh_password: str) -> str | None:
        """Try connecting to each visible Pixie device until one works."""
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection
        from homeassistant.components.bluetooth import async_ble_device_from_address
        from pigsydust import PixieClient

        # Collect all Pixie devices, sorted by RSSI (strongest first).
        candidates = []
        for info in async_discovered_service_info(self.hass, connectable=True):
            if 0x0211 in (info.manufacturer_data or {}):
                candidates.append((info.rssi, info.address, info.name))

        candidates.sort(reverse=True)  # strongest RSSI first

        if not candidates:
            _LOGGER.warning("No Pixie devices found in HA bluetooth cache")
            return "cannot_connect"

        _LOGGER.warning("Found %d Pixie candidates: %s", len(candidates),
                        [(a, r) for r, a, _ in candidates])

        for rssi, address, name in candidates:
            ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
            if ble_device is None:
                continue

            _LOGGER.warning("Trying %s (%s, RSSI=%d)", address, name, rssi)
            try:
                ble_client = await establish_connection(
                    BleakClient, ble_device, address, max_attempts=2,
                )
            except Exception:
                _LOGGER.warning("Connection to %s failed, trying next", address)
                continue

            _LOGGER.warning("Connected to %s, attempting login", address)
            client = PixieClient(address)
            client.set_ble_client(ble_client)

            try:
                await client.login(MESH_NAME, mesh_password)
                _LOGGER.warning("Login to %s successful", address)
                return None  # success
            except LoginError:
                return "invalid_auth"  # wrong password, don't try others
            except Exception:
                _LOGGER.warning("Login to %s failed, trying next", address, exc_info=True)
            finally:
                await client.disconnect()

        return "cannot_connect"
