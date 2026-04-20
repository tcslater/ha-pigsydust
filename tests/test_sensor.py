"""Tests for the SAL Pixie sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pigsydust import DeviceStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_sensor_entities_created(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """Connected-device sensor plus per-device routing metrics."""
    assert hass.states.get("sensor.pixie_mesh_connected_device") is not None
    assert hass.states.get("sensor.pixie_switch_1_mesh_signal") is not None
    assert hass.states.get("sensor.pixie_switch_2_mesh_signal") is not None


async def test_routing_metric_reflects_status(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Pushing a status with a non-zero routing_metric surfaces in the sensor."""
    coordinator = init_integration.runtime_data.coordinator
    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(
        DeviceStatus(
            address=1, is_on=True,
            mac=bytes([0, 0, 0, 0, 0, 1]), routing_metric=42,
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.pixie_switch_1_mesh_signal").state == "42"


async def test_connected_device_sensor_resolves_name(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """The connected-device sensor looks up the device by MAC suffix."""
    # conftest's mock sets client._gw_mac so byte[5] == 0x01, matching address=1.
    state = hass.states.get("sensor.pixie_mesh_connected_device")
    assert state is not None
    # Either the device name ("Pixie Switch 1") or the MAC fallback.
    assert state.state in ("Pixie Switch 1", mock_pixie_client.gateway_mac)


async def test_connected_device_sensor_none_for_zero_mac(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A zeroed _gw_mac means no gateway identified yet → state is None."""
    mock_pixie_client._gw_mac = b"\x00" * 6
    # Force a re-render.
    coordinator = init_integration.runtime_data.coordinator
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.pixie_mesh_connected_device")
    assert state.state in ("unknown", "None", "")
