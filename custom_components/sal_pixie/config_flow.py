"""Config flow for SAL Pixie integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from pigsydust import PixieClient
from pigsydust.crypto import LoginError

from . import _gateway_mac_for
from .const import CONF_MESH_PASSWORD, DOMAIN, MESH_NAME

_LOGGER = logging.getLogger(__name__)

_STEP_SCHEMA = vol.Schema({vol.Required(CONF_MESH_PASSWORD): str})


async def _test_connection(hass: HomeAssistant, mesh_password: str) -> str | None:
    """Try to reach the mesh with the given password.

    Returns ``None`` on success, or an error key (``"cannot_connect"`` /
    ``"invalid_auth"``) on failure. Shared across the user,
    bluetooth_confirm, reauth_confirm, and reconfigure steps.
    """
    candidates: list[tuple[int, str, str | None]] = []
    for info in async_discovered_service_info(hass, connectable=True):
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

        ble_device = async_ble_device_from_address(hass, address, connectable=True)
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
        mac = _gateway_mac_for(hass, address)
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
            error = await _test_connection(self.hass, user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title="SAL Pixie",
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=_STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _test_connection(self.hass, user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title="SAL Pixie",
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Entry point when the coordinator raises ConfigEntryAuthFailed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _test_connection(self.hass, user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the stored home key without removing the entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _test_connection(self.hass, user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_STEP_SCHEMA,
            errors=errors,
        )
