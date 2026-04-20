"""Tests for the SAL Pixie repairs flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie.repairs import (
    MeshUnreachableRepairFlow,
    async_create_fix_flow,
)


async def test_create_fix_flow_returns_handler_for_mesh_unreachable(
    hass: HomeAssistant, init_integration: MockConfigEntry,
) -> None:
    """The factory returns a MeshUnreachableRepairFlow for the correct issue_id."""
    flow = await async_create_fix_flow(
        hass, "mesh_unreachable", {"entry_id": init_integration.entry_id},
    )
    assert isinstance(flow, MeshUnreachableRepairFlow)


async def test_create_fix_flow_unknown_issue(hass: HomeAssistant) -> None:
    """Unknown issue IDs fall through to None."""
    flow = await async_create_fix_flow(hass, "something_else", {})
    assert flow is None


async def test_create_fix_flow_missing_entry_id(hass: HomeAssistant) -> None:
    """Without entry_id in data the factory returns None."""
    assert await async_create_fix_flow(hass, "mesh_unreachable", None) is None
    assert await async_create_fix_flow(hass, "mesh_unreachable", {}) is None


async def test_create_fix_flow_non_string_entry_id(hass: HomeAssistant) -> None:
    """Non-string entry_id → None (defensive against bad issue data)."""
    flow = await async_create_fix_flow(hass, "mesh_unreachable", {"entry_id": 42})
    assert flow is None


async def test_repair_flow_confirm_reloads_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Confirming the repair triggers async_reload on the entry."""
    flow = await async_create_fix_flow(
        hass, "mesh_unreachable", {"entry_id": init_integration.entry_id},
    )
    flow.hass = hass

    # Init step just routes to confirm.
    init_result = await flow.async_step_init()
    assert init_result["type"] is FlowResultType.FORM
    assert init_result["step_id"] == "confirm"

    with patch.object(
        hass.config_entries, "async_reload",
    ) as reload_mock:
        confirm_result = await flow.async_step_confirm({})

    reload_mock.assert_called_with(init_integration.entry_id)
    assert confirm_result["type"] is FlowResultType.CREATE_ENTRY
