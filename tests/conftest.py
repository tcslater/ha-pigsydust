"""Shared fixtures for SAL Pixie tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pigsydust import DeviceStatus
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie.const import CONF_MESH_PASSWORD, DOMAIN

MOCK_ADDRESS = "AA:BB:CC:DD:EE:01"
MOCK_PASSWORD = "1234"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable custom_components loading for every test."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A MockConfigEntry for the sal_pixie domain."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MESH_PASSWORD: MOCK_PASSWORD},
        unique_id=DOMAIN,
        title="SAL Pixie",
    )


@pytest.fixture
def mock_device_statuses() -> dict[int, DeviceStatus]:
    """Two switches: one on, one off."""
    return {
        1: DeviceStatus(
            address=1,
            is_on=True,
            mac=bytes([0, 0, 0xAA, 0xBB, 0xCC, 0x01]),
            routing_metric=0,
        ),
        2: DeviceStatus(
            address=2,
            is_on=False,
            mac=bytes([0, 0, 0xAA, 0xBB, 0xCC, 0x02]),
            routing_metric=0,
        ),
    }


@pytest.fixture
def mock_service_info() -> MagicMock:
    """A BluetoothServiceInfoBleak-shaped mock carrying Pixie manuf data.

    The manufacturer blob layout matters for ``parse_pixie_advert`` used by
    diagnostics and by ``_gateway_mac_for`` on macOS: bytes 2..5 are the
    low four MAC octets in reverse order, bytes 6..7 are ``type``/``stype``
    (wire-halved), byte 8 is the packed status byte, byte 9 is the mesh
    address, and bytes 11..14 are the network ID.
    """
    info = MagicMock()
    info.address = MOCK_ADDRESS
    info.name = "Pixie Switch"
    info.rssi = -50
    info.connectable = True
    # 17 bytes: [0x11,0x02, 0x01,0xCC,0xBB,0xAA, 0x16,0x0C, 0x45, 0x01, 0x00,
    #            0x1A,0xE7,0x1D,0x19, 0x00, 0x00]
    info.manufacturer_data = {
        0x0211: bytes([
            0x11, 0x02,
            0x01, 0xCC, 0xBB, 0xAA,
            0x16, 0x0C,
            0x45,
            0x01,
            0x00,
            0x1A, 0xE7, 0x1D, 0x19,
            0x00, 0x00,
        ])
    }
    return info


@pytest.fixture
def mock_ble_device() -> MagicMock:
    """BLEDevice-shaped mock for async_ble_device_from_address."""
    device = MagicMock()
    device.address = MOCK_ADDRESS
    device.name = "Pixie Switch"
    return device


@pytest.fixture
def mock_bleak_client() -> MagicMock:
    """Stand-in for the BleakClient that establish_connection returns."""
    client = MagicMock()
    client.is_connected = True
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def mock_pixie_client(
    mock_device_statuses: dict[int, DeviceStatus],
) -> Generator[MagicMock, None, None]:
    """Patch ``PixieClient`` where both ``__init__.py`` and ``config_flow.py``
    reach for it. ``autospec=True`` would pull in the real signature, but
    also make async attributes cumbersome; stub the surface by hand.
    """
    instance = MagicMock()
    instance.connect = AsyncMock()
    instance.disconnect = AsyncMock()
    instance.login = AsyncMock()
    instance.query_status = AsyncMock(return_value=mock_device_statuses)
    instance.ping_device = AsyncMock(return_value=None)
    instance.turn_on = AsyncMock()
    instance.turn_off = AsyncMock()
    instance.set_led_blue = AsyncMock()
    instance.set_led_orange = AsyncMock()
    instance.set_led_purple = AsyncMock()
    instance.reset_led = AsyncMock()
    instance.set_ble_client = MagicMock()
    instance.set_disconnect_callback = MagicMock()
    instance.on_status_update = MagicMock(return_value=lambda: None)
    instance._on_ble_disconnect = MagicMock()
    instance.is_connected = True
    instance.gateway_address = MOCK_ADDRESS
    instance.gateway_mac = "AA:BB:CC:DD:EE:01"
    instance.firmware_version = "1.0"
    instance.hardware_version = "1.0"
    instance._gw_mac = bytes([0, 0, 0xAA, 0xBB, 0xCC, 0x01])

    with patch(
        "custom_components.sal_pixie.PixieClient", return_value=instance,
    ), patch(
        "custom_components.sal_pixie.config_flow.PixieClient", return_value=instance,
    ):
        yield instance


@pytest.fixture
def mock_bluetooth(
    mock_service_info: MagicMock,
    mock_ble_device: MagicMock,
    mock_bleak_client: MagicMock,
) -> Generator[dict[str, MagicMock], None, None]:
    """Patch HA's Bluetooth helpers + bleak_retry_connector at both import sites."""
    with patch(
        "custom_components.sal_pixie.async_discovered_service_info",
        return_value=[mock_service_info],
    ), patch(
        "custom_components.sal_pixie.config_flow.async_discovered_service_info",
        return_value=[mock_service_info],
    ), patch(
        "custom_components.sal_pixie.diagnostics.async_discovered_service_info",
        return_value=[mock_service_info],
    ), patch(
        "custom_components.sal_pixie.async_ble_device_from_address",
        return_value=mock_ble_device,
    ), patch(
        "custom_components.sal_pixie.config_flow.async_ble_device_from_address",
        return_value=mock_ble_device,
    ), patch(
        "custom_components.sal_pixie.establish_connection",
        AsyncMock(return_value=mock_bleak_client),
    ), patch(
        "custom_components.sal_pixie.config_flow.establish_connection",
        AsyncMock(return_value=mock_bleak_client),
    ):
        yield {
            "service_info": mock_service_info,
            "ble_device": mock_ble_device,
            "bleak_client": mock_bleak_client,
        }


@pytest.fixture
async def init_integration(
    hass,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> MockConfigEntry:
    """A fully loaded integration ready for platform tests."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
