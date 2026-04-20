"""Tests for the SAL Pixie select platform (indicator LED mode)."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_mesh_and_per_device_selects_created(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """One mesh-wide select plus one per device."""
    assert hass.states.get("select.pixie_mesh_indicators") is not None
    assert hass.states.get("select.pixie_switch_1_indicator") is not None
    assert hass.states.get("select.pixie_switch_2_indicator") is not None


async def test_mesh_select_blue_broadcasts(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Mesh-wide select → Blue broadcasts to 0xFFFF."""
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.pixie_mesh_indicators", "option": "Blue"},
        blocking=True,
    )
    mock_pixie_client.set_led_blue.assert_awaited_with(0xFFFF, True)
    assert hass.states.get("select.pixie_mesh_indicators").state == "Blue"


async def test_per_device_select_orange(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Per-device select → Orange uses the device address."""
    runtime = init_integration.runtime_data
    runtime.device_brightness[1] = 8

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.pixie_switch_1_indicator", "option": "Orange"},
        blocking=True,
    )
    mock_pixie_client.set_led_orange.assert_awaited_with(1, 8)


async def test_select_off_from_purple_resets_led(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Transitioning Purple → Off resets the LED before clearing blue/orange."""
    runtime = init_integration.runtime_data
    runtime.device_modes[1] = "Purple"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.pixie_switch_1_indicator", "option": "Off"},
        blocking=True,
    )
    mock_pixie_client.reset_led.assert_awaited_with(1)
    mock_pixie_client.set_led_blue.assert_awaited_with(1, False)
    mock_pixie_client.set_led_orange.assert_awaited_with(1, 0)


async def test_select_purple_calls_purple(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Purple uses set_led_purple with the stored brightness."""
    runtime = init_integration.runtime_data
    runtime.device_brightness[2] = 12

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.pixie_switch_2_indicator", "option": "Purple"},
        blocking=True,
    )
    mock_pixie_client.set_led_purple.assert_awaited_with(2, 12)
