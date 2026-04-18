"""Tests for the SAL Pixie number platform (indicator brightness)."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_brightness_entities_created(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """Mesh-wide plus per-device brightness sliders."""
    assert hass.states.get("number.pixie_mesh_indicator_brightness") is not None
    assert hass.states.get("number.pixie_switch_1_indicator_brightness") is not None
    assert hass.states.get("number.pixie_switch_2_indicator_brightness") is not None


async def test_mesh_brightness_no_op_when_off(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Setting brightness with mesh_mode=Off just updates state, no BLE writes."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pixie_mesh_indicator_brightness", "value": 10},
        blocking=True,
    )
    mock_pixie_client.set_led_orange.assert_not_awaited()
    mock_pixie_client.set_led_purple.assert_not_awaited()


async def test_mesh_brightness_orange_sends_set_led_orange(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """With mesh_mode=Orange, brightness → set_led_orange(0xFFFF, level)."""
    runtime = init_integration.runtime_data
    runtime.mesh_mode = "Orange"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pixie_mesh_indicator_brightness", "value": 7},
        blocking=True,
    )
    mock_pixie_client.set_led_orange.assert_awaited_with(0xFFFF, 7)


async def test_mesh_brightness_purple(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """With mesh_mode=Purple, brightness → set_led_purple(0xFFFF, level)."""
    runtime = init_integration.runtime_data
    runtime.mesh_mode = "Purple"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pixie_mesh_indicator_brightness", "value": 3},
        blocking=True,
    )
    mock_pixie_client.set_led_purple.assert_awaited_with(0xFFFF, 3)


async def test_per_device_brightness_orange(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Per-device brightness with mode=Orange → set_led_orange(address, level)."""
    runtime = init_integration.runtime_data
    runtime.device_modes[1] = "Orange"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pixie_switch_1_indicator_brightness", "value": 5},
        blocking=True,
    )
    mock_pixie_client.set_led_orange.assert_awaited_with(1, 5)


async def test_per_device_brightness_purple(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Per-device brightness with mode=Purple → set_led_purple(address, level)."""
    runtime = init_integration.runtime_data
    runtime.device_modes[2] = "Purple"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pixie_switch_2_indicator_brightness", "value": 9},
        blocking=True,
    )
    mock_pixie_client.set_led_purple.assert_awaited_with(2, 9)
