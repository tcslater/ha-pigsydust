"""Tests for the SAL Pixie integration setup/unload and services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pigsydust.crypto import LoginError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie import (
    SERVICE_ALL_OFF,
    SERVICE_ALL_ON,
    SERVICE_SET_INDICATOR,
)
from custom_components.sal_pixie.const import DOMAIN


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Full load/unload cycle populates and clears runtime_data."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.client is mock_pixie_client
    assert mock_config_entry.runtime_data.coordinator is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_no_device_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """No Pixie device in HA bluetooth → setup defers via ConfigEntryNotReady."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.sal_pixie.async_discovered_service_info",
        return_value=[],
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_unresolvable_ble_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Discovery sees a Pixie but async_ble_device_from_address returns None."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.sal_pixie.async_ble_device_from_address",
        return_value=None,
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_establish_connection_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """establish_connection raising → ConfigEntryNotReady."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.sal_pixie.establish_connection",
        AsyncMock(side_effect=Exception("boom")),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_login_error_triggers_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """LoginError during initial setup → ConfigEntryAuthFailed (reauth)."""
    mock_config_entry.add_to_hass(hass)
    mock_pixie_client.login.side_effect = LoginError("bad key")

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"].get("source") == "reauth" for f in flows)


async def test_setup_login_other_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Non-LoginError during login → ConfigEntryNotReady."""
    mock_config_entry.add_to_hass(hass)
    mock_pixie_client.login.side_effect = Exception("transient")

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_services_registered(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """All three domain services exist after setup."""
    assert hass.services.has_service(DOMAIN, SERVICE_ALL_ON)
    assert hass.services.has_service(DOMAIN, SERVICE_ALL_OFF)
    assert hass.services.has_service(DOMAIN, SERVICE_SET_INDICATOR)


async def test_service_all_on_reaches_client(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """all_on broadcasts to 0xFFFF."""
    await hass.services.async_call(DOMAIN, SERVICE_ALL_ON, {}, blocking=True)
    mock_pixie_client.turn_on.assert_awaited_with(0xFFFF)


async def test_service_all_off_reaches_client(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """all_off broadcasts to 0xFFFF."""
    await hass.services.async_call(DOMAIN, SERVICE_ALL_OFF, {}, blocking=True)
    mock_pixie_client.turn_off.assert_awaited_with(0xFFFF)


async def test_service_all_on_connection_error_wraps(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """ConnectionError during service call surfaces as HomeAssistantError."""
    mock_pixie_client.turn_on.side_effect = ConnectionError("offline")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_ALL_ON, {}, blocking=True)


async def test_service_all_off_connection_error_wraps(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """ConnectionError during all_off surfaces as HomeAssistantError."""
    mock_pixie_client.turn_off.side_effect = ConnectionError("offline")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_ALL_OFF, {}, blocking=True)


@pytest.mark.parametrize(
    ("mode", "attr"),
    [
        ("blue", "set_led_blue"),
        ("orange", "set_led_orange"),
        ("purple", "set_led_purple"),
    ],
)
async def test_service_set_indicator_modes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mode: str,
    attr: str,
) -> None:
    """Each indicator mode routes to its matching client method."""
    await hass.services.async_call(
        DOMAIN, SERVICE_SET_INDICATOR, {"mode": mode, "brightness": 10}, blocking=True,
    )
    getattr(mock_pixie_client, attr).assert_awaited()


async def test_service_set_indicator_off(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Off mode resets LED + clears blue + clears orange."""
    await hass.services.async_call(
        DOMAIN, SERVICE_SET_INDICATOR, {"mode": "off"}, blocking=True,
    )
    mock_pixie_client.reset_led.assert_awaited()
    mock_pixie_client.set_led_blue.assert_awaited_with(0xFFFF, False)
    mock_pixie_client.set_led_orange.assert_awaited_with(0xFFFF, 0)


async def test_service_set_indicator_connection_error_wraps(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """ConnectionError during set_indicator surfaces as HomeAssistantError."""
    mock_pixie_client.set_led_blue.side_effect = ConnectionError("offline")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_INDICATOR, {"mode": "blue"}, blocking=True,
        )


async def test_service_requires_loaded_entry(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Calling a service with no entry loaded raises HomeAssistantError."""
    # async_setup registers services at startup even without an entry.
    # Force that path by calling async_setup_component directly.
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_ALL_ON, {}, blocking=True)
