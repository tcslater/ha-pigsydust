"""Repairs flow for SAL Pixie.

Surfaces a sustained mesh outage (N consecutive failed coordinator
updates, raised from ``coordinator.py``) as an actionable repair
issue. The only "fix" is to retry — HA's repair panel provides the
user-facing surface, and confirming the flow reloads the config entry
so a fresh connection attempt runs.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult


class MeshUnreachableRepairFlow(RepairsFlow):
    """Prompt the user to retry after a sustained mesh outage."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            # Reload the entry to kick off a fresh connection attempt.
            # If reconnect is genuinely impossible (adapter unplugged,
            # mesh dead), the reload will fail and a new repair issue
            # will be raised by the coordinator on its next update.
            await self.hass.config_entries.async_reload(self._entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow | None:
    if issue_id == "mesh_unreachable":
        if data is None or "entry_id" not in data:
            return None
        entry_id = data["entry_id"]
        if not isinstance(entry_id, str):
            return None
        return MeshUnreachableRepairFlow(entry_id)
    return None
