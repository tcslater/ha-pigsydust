"""Tests for SAL Pixie diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from pigsydust import DeviceClass, DeviceStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.sal_pixie.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_password(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """The stored home key must be scrubbed from the dump."""
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert result["entry"]["data"]["home_key"] == "**REDACTED**"


async def test_diagnostics_includes_devices(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Per-address status rows appear under ``devices``.

    Also asserts presence of the Stage 6a-backfill fields (``minor_type``,
    ``device_class``, ``raw_manufacturer_data``) — their values may be
    ``None`` until the coordinator correlates advert→status, but the keys
    must always be emitted so a users's diagnostics dump has a stable shape.
    """
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert set(result["devices"].keys()) == {"1", "2"}
    assert result["devices"]["1"]["is_on"] is True
    assert result["devices"]["2"]["is_on"] is False
    for row in result["devices"].values():
        assert "minor_type" in row
        assert "device_class" in row
        assert "raw_manufacturer_data" in row
        assert "major_type_decoded" in row


async def test_diagnostics_emits_device_class_when_populated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A DeviceStatus with device_class set surfaces as the lowercased enum id."""
    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(
        DeviceStatus(
            address=5,
            is_on=True,
            major_type=0x45,
            mac=bytes([0, 0, 0xAA, 0xBB, 0xCC, 5]),
            routing_metric=0,
            minor_type=DeviceClass.SWITCH.value,
            device_class=DeviceClass.SWITCH,
            raw_manufacturer_data=b"\x00\x01\x02\x03",
        )
    )
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, init_integration)
    row = result["devices"]["5"]
    assert row["device_class"] == "switch"
    assert row["minor_type"] == DeviceClass.SWITCH.value
    assert row["raw_manufacturer_data"] == "00010203"


async def test_diagnostics_includes_gateway_advert(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """The connected-gateway advert is decoded via parse_pixie_advert."""
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    advert = result["connection"]["gateway_advert"]
    assert advert is not None
    # major_type 0x45 in the mock blob → online set, alarm_dev clear.
    assert advert["major_type_decoded"]["online"] is True
    assert advert["major_type_decoded"]["alarm_dev"] is False


async def test_diagnostics_gateway_advert_missing_when_discovery_empty(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """If discovery yields nothing for the gateway address, advert is None."""
    with patch(
        "custom_components.sal_pixie.diagnostics.async_discovered_service_info",
        return_value=[],
    ):
        result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert result["connection"]["gateway_advert"] is None


async def test_diagnostics_snapshot(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Full diagnostics shape is stable (syrupy snapshot).

    Strips the entry_id and coordinator timing fields that vary per test run.
    """
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert result == snapshot(
        exclude=props(
            "entry_id", "created_at", "modified_at",
            "last_update_success", "discovery_keys", "subentries",
        )
    )
