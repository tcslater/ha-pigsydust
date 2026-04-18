"""Tests for the SAL Pixie light platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pigsydust import DeviceClass, DeviceStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie.light import _derive_device_name


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


def _status(
    address: int = 1,
    minor_type: int | None = None,
    device_class: DeviceClass | None = None,
) -> DeviceStatus:
    return DeviceStatus(
        address=address,
        is_on=True,
        major_type=0x45,
        mac=bytes([0, 0, 0, 0, 0, address]),
        routing_metric=0,
        minor_type=minor_type,
        device_class=device_class,
    )


def test_derive_device_name_uses_class_label_when_available() -> None:
    """device_class + resolvable translation → '{label} {address}'."""
    labels = {"switch": "Wall Switch"}
    name = _derive_device_name(
        4, _status(address=4, device_class=DeviceClass.SWITCH), labels.get,
    )
    assert name == "Wall Switch 4"


def test_derive_device_name_falls_back_to_minor_type() -> None:
    """Known minor_type but no translation → 'Pixie device 0xNNNN {address}'."""
    name = _derive_device_name(
        2, _status(address=2, minor_type=0x2c16), lambda _key: None,
    )
    assert name == "Pixie device 0x2c16 2"


def test_derive_device_name_legacy_fallback() -> None:
    """Nothing correlated yet → legacy 'Pixie Switch {address}'."""
    name = _derive_device_name(1, _status(address=1), None)
    assert name == "Pixie Switch 1"


def test_derive_device_name_ignores_class_when_label_missing() -> None:
    """device_class set but translation lookup returns None → try minor_type."""
    name = _derive_device_name(
        7,
        _status(address=7, device_class=DeviceClass.SWITCH, minor_type=0x2c16),
        lambda _key: None,
    )
    assert name == "Pixie device 0x2c16 7"
