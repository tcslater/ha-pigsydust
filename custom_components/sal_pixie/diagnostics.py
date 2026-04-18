"""Diagnostics support for SAL Pixie."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from pigsydust import parse_pixie_advert

from .const import CONF_MESH_PASSWORD

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

TO_REDACT = {CONF_MESH_PASSWORD}


def _device_dict(status: Any) -> dict[str, Any]:
    """One row of the per-address table.

    ``major_type`` is the packed byte from the status notification payload.
    Its bit layout is not established (Stage 0 disassembly covered the
    *advertisement* byte[14], which is a different byte from a different
    packet); we expose the raw value for future investigation.
    """
    mac = getattr(status, "mac", None)
    return {
        "address": status.address,
        "is_on": status.is_on,
        "mac": mac.hex() if isinstance(mac, (bytes, bytearray)) else mac,
        "major_type": getattr(status, "major_type", None),
        "routing_metric": getattr(status, "routing_metric", None),
    }


def _gateway_advert_dict(hass: HomeAssistant, address: str) -> dict[str, Any] | None:
    """Look up the BLE manufacturer-data advert for the connected gateway
    and return its decoded fields.
    """
    for info in async_discovered_service_info(hass, connectable=True):
        if info.address != address:
            continue
        advert = parse_pixie_advert(info.manufacturer_data)
        if advert is None:
            return None
        return {
            "mac": advert.mac.hex(),
            "major_type_raw": advert.major_type,
            "major_type_decoded": dataclasses.asdict(advert.major_type_flags),
            "minor_type": advert.minor_type,
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
