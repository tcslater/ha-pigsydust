"""Sensor platform for Pixie Mesh routing metrics."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PixieCoordinator = data["coordinator"]
    client = data["client"]

    entities: list[SensorEntity] = []

    # Mesh-wide: current gateway sensor.
    entities.append(PixieGatewaySensor(entry, client, coordinator))

    # Per-device: routing metric.
    for address in (coordinator.data or {}):
        entities.append(PixieRoutingMetric(coordinator, entry, address))

    async_add_entities(entities, update_before_add=False)

    @callback
    def _async_add_new_device(address: int) -> None:
        async_add_entities(
            [PixieRoutingMetric(coordinator, entry, address)],
            update_before_add=False,
        )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_DEVICE.format(entry_id=entry.entry_id),
            _async_add_new_device,
        )
    )


class PixieRoutingMetric(CoordinatorEntity[PixieCoordinator], SensorEntity):
    """Mesh routing metric for a device (signal/hop indicator)."""

    has_entity_name = True
    _attr_name = "Mesh signal"
    _attr_icon = "mdi:signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = None

    def __init__(
        self,
        coordinator: PixieCoordinator,
        entry: ConfigEntry,
        address: int,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}_routing_metric"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{address}")},
        )

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        status = self.coordinator.data.get(self._address)
        if status is None:
            return None
        return status.routing_metric


class PixieGatewaySensor(CoordinatorEntity[PixieCoordinator], SensorEntity):
    """Shows which mesh device is the current BLE gateway."""

    has_entity_name = True
    _attr_name = "Gateway"
    _attr_icon = "mdi:router-wireless"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, client, coordinator: PixieCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_mesh_gateway"
        self._attr_device_info = MESH_DEVICE_INFO(entry)

    @property
    def native_value(self) -> str | None:
        # The gateway's device address is the last byte of its MAC.
        client = self.coordinator.client
        mac = client._gw_mac
        if mac == b"\x00" * 6:
            return None
        dev_addr = mac[5]

        # Look up the HA device name from the device registry.
        from homeassistant.helpers import device_registry as dr
        dev_registry = dr.async_get(self.hass)
        for entry in dev_registry.devices.values():
            for identifier in entry.identifiers:
                if identifier[0] == DOMAIN and identifier[1].endswith(f"_{dev_addr}"):
                    return entry.name
        return client.gateway_mac

    @property
    def extra_state_attributes(self) -> dict:
        client = self.coordinator.client
        return {
            "mac": client.gateway_mac,
            "ble_address": client.gateway_address,
        }
