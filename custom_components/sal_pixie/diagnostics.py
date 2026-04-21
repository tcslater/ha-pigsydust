"""Diagnostics support for SAL Pixie."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from pigsydust import StatusByteFlags, parse_pixie_advert

from .const import CONF_MESH_PASSWORD

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

TO_REDACT = {CONF_MESH_PASSWORD}


def _status_flags_dict(flags: StatusByteFlags | None) -> dict[str, Any] | None:
    if flags is None:
        return None
    return {
        "online": flags.online,
        "alarm_dev": flags.alarm_dev,
        "version": flags.version,
    }


def _device_dict(status: Any) -> dict[str, Any]:
    """One row of the per-address diagnostics table."""
    mac = getattr(status, "mac", None)
    return {
        "address": status.address,
        "is_on": status.is_on,
        "mac": mac.hex() if isinstance(mac, (bytes, bytearray)) else mac,
        "type": getattr(status, "type", None),
        "stype": getattr(status, "stype", None),
        "device_class_name": getattr(status, "device_class_name", None),
        "status_byte": getattr(status, "status_byte", None),
        "status_flags": _status_flags_dict(getattr(status, "status_flags", None)),
        "sno": getattr(status, "sno", None),
        "ttc": getattr(status, "ttc", None),
        "hops": getattr(status, "hops", None),
    }


def _gateway_advert_dict(hass: HomeAssistant, address: str) -> dict[str, Any] | None:
    """Decoded fields of the connected gateway's BLE advert."""
    for info in async_discovered_service_info(hass, connectable=True):
        if info.address != address:
            continue
        advert = parse_pixie_advert(info.manufacturer_data)
        if advert is None:
            return None
        return {
            "mac": advert.mac.hex(),
            "type": advert.type,
            "stype": advert.stype,
            "device_class_name": advert.device_class_name,
            "status_byte": advert.status_byte,
            "status_flags": _status_flags_dict(advert.status_flags),
            "mesh_address": advert.mesh_address,
            "network_id": advert.network_id.hex(),
            "raw_manufacturer_data": advert.raw.hex(),
            "rssi": info.rssi,
        }
    return None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SalPixieConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    client = runtime.client
    coordinator = runtime.coordinator

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "connection": {
            "address": client.gateway_address,
            "mac": client.gateway_mac,
            "firmware_version": client.firmware_version,
            "hardware_version": client.hardware_version,
            "is_connected": client.is_connected,
            "gateway_advert": _gateway_advert_dict(hass, client.gateway_address),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_s": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "device_count": len(coordinator.data or {}),
            "known_addresses": sorted(coordinator._known_addresses),
            "last_seen_count": len(coordinator._last_seen),
        },
        "devices": {
            str(addr): _device_dict(status)
            for addr, status in sorted((coordinator.data or {}).items())
        },
    }
