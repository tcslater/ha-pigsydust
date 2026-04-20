"""Constants for the SAL Pixie integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def derive_device_name(address: int, status: Any | None) -> str:
    """Per-device name: spec class identifier when resolvable, else wire hex.

    Falls back to ``Pixie Switch {address}`` when the device hasn't yet
    been correlated to a wire ``(type, stype)`` pair (no 0xdb response).
    """
    name = getattr(status, "device_class_name", None)
    if name:
        return f"Pixie {name} {address}"
    type_ = getattr(status, "type", None)
    stype = getattr(status, "stype", None)
    if type_ is not None and stype is not None:
        return f"Pixie device {type_:02x}{stype:02x} {address}"
    return f"Pixie Switch {address}"


def DEVICE_INFO(
    entry: SalPixieConfigEntry, address: int, status: Any | None
) -> DeviceInfo:
    """DeviceInfo for a per-device entity, shared across all platforms.

    Every per-device entity must supply ``name`` so that HA's device
    registry names the device consistently regardless of which platform
    registers it first (newer HA revisions no longer backfill the name
    from a later entity's DeviceInfo).
    """
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
        name=derive_device_name(address, status),
        manufacturer="SAL",
        model="Pixie",
    )
