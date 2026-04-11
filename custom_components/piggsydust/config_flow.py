"""Config flow for Pixie Mesh integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from piggsydust import PixieClient
from piggsydust.crypto import LoginError

from .const import CONF_GATEWAY_ADDRESS, CONF_MESH_PASSWORD, DOMAIN, MESH_NAME

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
            assert self._discovery_info is not None
            address = self._discovery_info.address
            error = await self._test_connection(
                address, user_input[CONF_MESH_PASSWORD]
            )
            if error is None:
                return self.async_create_entry(
                    title="Pixie Mesh",
                    data={
                        CONF_GATEWAY_ADDRESS: address,
                        CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD],
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MESH_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            error = await self._test_connection(
                user_input[CONF_GATEWAY_ADDRESS],
                user_input[CONF_MESH_PASSWORD],
            )
            if error is None:
                return self.async_create_entry(
                    title="Pixie Mesh",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GATEWAY_ADDRESS): str,
                    vol.Required(CONF_MESH_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _test_connection(
        self, address: str, mesh_password: str
    ) -> str | None:
        """Test BLE connection and login. Returns error key or None."""
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection
        from homeassistant.components.bluetooth import async_ble_device_from_address

        ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
        if ble_device is None:
            client = PixieClient(address)
            try:
                await client.connect()
            except Exception:
                _LOGGER.debug("Connection failed", exc_info=True)
                return "cannot_connect"
        else:
            try:
                ble_client = await establish_connection(
                    BleakClient, ble_device, address, max_attempts=3,
                )
            except Exception:
                _LOGGER.debug("Connection failed", exc_info=True)
                return "cannot_connect"
            client = PixieClient(address)
            client.set_ble_client(ble_client)

        try:
            await client.login(MESH_NAME, mesh_password)
        except LoginError:
            return "invalid_auth"
        except Exception:
            _LOGGER.debug("Login failed", exc_info=True)
            return "cannot_connect"
        finally:
            await client.disconnect()
        return None
