"""Tests for the SAL Pixie config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pigsydust.crypto import LoginError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie.const import CONF_MESH_PASSWORD, DOMAIN

from .conftest import MOCK_ADDRESS, MOCK_PASSWORD


def _bluetooth_discovery_info(service_info: MagicMock) -> BluetoothServiceInfoBleak:
    """Build a BluetoothServiceInfoBleak that the discovery step accepts."""
    return BluetoothServiceInfoBleak(
        name=service_info.name,
        address=service_info.address,
        rssi=service_info.rssi,
        manufacturer_data=service_info.manufacturer_data,
        service_data={},
        service_uuids=[],
        source="local",
        device=service_info,
        advertisement=MagicMock(),
        connectable=True,
        time=0.0,
        tx_power=None,
    )


async def test_user_flow_happy_path(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Valid home key creates an entry titled 'SAL Pixie'."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: MOCK_PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SAL Pixie"
    assert result["data"] == {CONF_MESH_PASSWORD: MOCK_PASSWORD}
    # One login during _test_connection + one during async_setup_entry
    assert mock_pixie_client.login.await_count >= 1


async def test_user_flow_invalid_auth(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Wrong home key re-shows the form with invalid_auth."""
    mock_pixie_client.login.side_effect = LoginError("bad key")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect_no_devices(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """No Pixie devices in discovery → cannot_connect error."""
    from unittest.mock import patch

    with patch(
        "custom_components.sal_pixie.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MESH_PASSWORD: MOCK_PASSWORD}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_cannot_connect_unresolvable_ble(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Discovery finds the device but async_ble_device_from_address returns None."""
    from unittest.mock import patch

    with patch(
        "custom_components.sal_pixie.config_flow.async_ble_device_from_address",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MESH_PASSWORD: MOCK_PASSWORD}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_cannot_connect_establish_failure(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """establish_connection raises → cannot_connect."""
    from unittest.mock import patch

    with patch(
        "custom_components.sal_pixie.config_flow.establish_connection",
        AsyncMock(side_effect=Exception("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MESH_PASSWORD: MOCK_PASSWORD}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_login_error_other_exception(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Non-LoginError exceptions during login → keep trying, fall through to cannot_connect."""
    mock_pixie_client.login.side_effect = Exception("flakey")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: MOCK_PASSWORD}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_single_config_entry_blocks_second_user_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """``single_config_entry: true`` aborts a second user-initiated flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_bluetooth_discovery_happy_path(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """BLE discovery → confirm step → successful entry creation."""
    discovery = _bluetooth_discovery_info(mock_bluetooth["service_info"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: MOCK_PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SAL Pixie"


async def test_bluetooth_discovery_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Discovery when an entry already exists → abort."""
    mock_config_entry.add_to_hass(hass)
    discovery = _bluetooth_discovery_info(mock_bluetooth["service_info"])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery
    )
    assert result["type"] is FlowResultType.ABORT
    # single_config_entry:true pre-empts the unique_id check
    assert result["reason"] in ("already_configured", "single_instance_allowed")


async def test_bluetooth_discovery_invalid_auth(
    hass: HomeAssistant,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Bluetooth confirm step surfaces invalid_auth the same way the user step does."""
    discovery = _bluetooth_discovery_info(mock_bluetooth["service_info"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery
    )

    mock_pixie_client.login.side_effect = LoginError("bad key")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_happy_path(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Reauth with a valid key updates the entry and reloads."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "new-key"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_MESH_PASSWORD] == "new-key"


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Wrong key during reauth → form re-shown."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    mock_pixie_client.login.side_effect = LoginError("bad key")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_happy_path(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Reconfigure with a valid key updates entry data and reloads."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "rotated"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_MESH_PASSWORD] == "rotated"


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_bluetooth: dict[str, MagicMock],
) -> None:
    """Wrong key during reconfigure → form re-shown, entry unchanged."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    mock_pixie_client.login.side_effect = LoginError("bad key")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_MESH_PASSWORD] == MOCK_PASSWORD
