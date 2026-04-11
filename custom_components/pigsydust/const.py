"""Constants for the Pixie Mesh integration."""

from homeassistant.helpers.device_registry import DeviceInfo

DOMAIN = "pigsydust"

MESH_NAME = "Smart Light"  # Fixed — firmware default, not user-configurable.

CONF_MESH_PASSWORD = "home_key"


def MESH_DEVICE_INFO(entry) -> DeviceInfo:
    """Device info for the mesh-wide virtual device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_mesh")},
        name="Pixie Mesh",
        manufacturer="SAL",
        model="Pixie Mesh",
    )
