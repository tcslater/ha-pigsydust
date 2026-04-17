"""Constants for the SAL Pixie integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

DOMAIN = "sal_pixie"

MESH_NAME = "Smart Light"  # Fixed — firmware default, not user-configurable.

CONF_MESH_PASSWORD = "home_key"

SIGNAL_NEW_DEVICE = f"{DOMAIN}_new_device_{{entry_id}}"


def MESH_DEVICE_INFO(entry: SalPixieConfigEntry) -> DeviceInfo:
    """Device info for the mesh-wide virtual device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_mesh")},
        name="Pixie Mesh",
        manufacturer="SAL",
        model="Pixie Mesh",
    )
