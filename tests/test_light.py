"""Tests for the SAL Pixie light platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_light_entities_created(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """One light per mesh device from the initial poll."""
    assert hass.states.get("light.pixie_switch_1") is not None
    assert hass.states.get("light.pixie_switch_2") is not None


async def test_light_reflects_coordinator_data(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """Initial state mirrors mock_device_statuses (1→on, 2→off)."""
    assert hass.states.get("light.pixie_switch_1").state == "on"
    assert hass.states.get("light.pixie_switch_2").state == "off"


async def test_light_turn_on_calls_client(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """turn_on service routes to the mesh address."""
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.pixie_switch_2"}, blocking=True,
    )
    mock_pixie_client.turn_on.assert_awaited_with(2)
    assert hass.states.get("light.pixie_switch_2").state == "on"


async def test_light_turn_off_calls_client(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """turn_off service routes to the mesh address."""
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": "light.pixie_switch_1"}, blocking=True,
    )
    mock_pixie_client.turn_off.assert_awaited_with(1)
    assert hass.states.get("light.pixie_switch_1").state == "off"


async def test_light_unavailable_when_absent_from_coordinator(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """Dropping a device from coordinator.data → entity unavailable."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator.async_set_updated_data({})
    await hass.async_block_till_done()

    assert hass.states.get("light.pixie_switch_1").state == "unavailable"


async def test_light_turn_on_reconnects_on_connection_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A ConnectionError triggers coordinator.reconnect_and_retry."""
    coordinator = init_integration.runtime_data.coordinator
    mock_pixie_client.turn_on.side_effect = [ConnectionError("dropped"), None]

    async def _retry(action):
        await action(mock_pixie_client)

    from unittest.mock import AsyncMock, patch
    with patch.object(
        coordinator, "reconnect_and_retry", AsyncMock(side_effect=_retry),
    ):
        await hass.services.async_call(
            "light", "turn_on", {"entity_id": "light.pixie_switch_2"}, blocking=True,
        )

    assert mock_pixie_client.turn_on.await_count == 2
