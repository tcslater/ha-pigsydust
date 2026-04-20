"""Tests for SAL Pixie diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from pigsydust import DeviceStatus, StatusByteFlags
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

    The ``type``, ``stype``, ``status_byte``, and ``status_flags`` keys
    are emitted with a stable shape regardless of whether a 0xdb
    response has been seen yet — populated values come from the library
    parser, ``None`` before the first response.
    """
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert set(result["devices"].keys()) == {"1", "2"}
    assert result["devices"]["1"]["is_on"] is True
    assert result["devices"]["2"]["is_on"] is False
    for row in result["devices"].values():
        assert "type" in row
        assert "stype" in row
        assert "device_class_name" in row
        assert "status_byte" in row
        assert "status_flags" in row


async def test_diagnostics_emits_status_fields_when_populated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A DeviceStatus with type/stype/status_byte set surfaces verbatim."""
    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(
        DeviceStatus(
            address=5,
            is_on=True,
            mac=bytes([0, 0, 0xAA, 0xBB, 0xCC, 5]),
            routing_metric=0,
            type=0x16,
            stype=0x0C,
            status_byte=0x47,
            status_flags=StatusByteFlags.from_byte(0x47),
        )
    )
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, init_integration)
    row = result["devices"]["5"]
    assert row["type"] == 0x16
    assert row["stype"] == 0x0C
    assert row["device_class_name"] == "SWITCH_G2"
    assert row["status_byte"] == 0x47
    assert row["status_flags"] == {"online": True, "alarm_dev": True, "version": 0x11}


async def test_diagnostics_includes_gateway_advert(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """The connected-gateway advert is decoded via parse_pixie_advert."""
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    advert = result["connection"]["gateway_advert"]
    assert advert is not None
    # status byte 0x45 in the mock blob → online set, alarm_dev clear.
    assert advert["status_byte"] == 0x45
    assert advert["status_flags"]["online"] is True
    assert advert["status_flags"]["alarm_dev"] is False
    assert advert["type"] == 0x16
    assert advert["stype"] == 0x0C
    assert advert["device_class_name"] == "SWITCH_G2"


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
