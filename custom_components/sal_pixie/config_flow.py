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
from pigsydust import PixieClient
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
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

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
        """Try connecting to Pixie devices using standalone BleakClient."""
        # Get addresses from HA's bluetooth discovery cache.
        candidates = []
        for info in async_discovered_service_info(self.hass, connectable=True):
            if 0x0211 in (info.manufacturer_data or {}):
                candidates.append((info.rssi, info.address, info.name))

        candidates.sort(reverse=True)

        if not candidates:
            _LOGGER.warning("No Pixie devices found in HA bluetooth cache")
            return "cannot_connect"

        _LOGGER.info("Found %d Pixie candidates: %s", len(candidates),
                      [(a, r) for r, a, _ in candidates])

        for rssi, address, name in candidates:
            _LOGGER.info("Trying %s (%s, RSSI=%d)", address, name, rssi)

            # Use standalone PixieClient — bypasses HA's BLE wrapper.
            client = PixieClient(address)
            try:
                await client.connect()
            except Exception:
                _LOGGER.info("Connection to %s failed, trying next", address)
                continue

            _LOGGER.info("Connected to %s, attempting login", address)
            try:
                await client.login(MESH_NAME, mesh_password)
                _LOGGER.info("Login to %s successful", address)
                await client.disconnect()
                return None
            except LoginError:
                await client.disconnect()
                return "invalid_auth"
            except Exception:
                _LOGGER.info("Login to %s failed, trying next", address, exc_info=True)
                await client.disconnect()

        return "cannot_connect"
