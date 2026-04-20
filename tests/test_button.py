"""Tests for the SAL Pixie button platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_button_entities_created(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """Mesh-wide all_on/all_off plus per-device identify buttons."""
    assert hass.states.get("button.pixie_mesh_all_on") is not None
    assert hass.states.get("button.pixie_mesh_all_off") is not None
    assert hass.states.get("button.pixie_switch_1_identify") is not None
    assert hass.states.get("button.pixie_switch_2_identify") is not None


async def test_all_on_button(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Pressing all_on broadcasts turn_on to 0xFFFF."""
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.pixie_mesh_all_on"},
        blocking=True,
    )
    mock_pixie_client.turn_on.assert_awaited_with(0xFFFF)


async def test_all_off_button(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Pressing all_off broadcasts turn_off to 0xFFFF."""
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.pixie_mesh_all_off"},
        blocking=True,
    )
    mock_pixie_client.turn_off.assert_awaited_with(0xFFFF)


async def test_identify_button_start_and_stop(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Two presses toggle the identify state (start, then stop)."""
    mock_pixie_client.find_me = AsyncMock()

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.pixie_switch_1_identify"},
        blocking=True,
    )
    mock_pixie_client.find_me.assert_awaited_with(1, start=True)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.pixie_switch_1_identify"},
        blocking=True,
    )
    mock_pixie_client.find_me.assert_awaited_with(1, start=False)
