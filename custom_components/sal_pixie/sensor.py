"""Sensor platform for SAL Pixie routing metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_INFO, DOMAIN, MESH_DEVICE_INFO, SIGNAL_NEW_DEVICE
from .coordinator import PixieCoordinator

if TYPE_CHECKING:
    from . import SalPixieConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "SalPixieConfigEntry",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator

    entities: list[SensorEntity] = [PixieConnectedDeviceSensor(entry, coordinator)]
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
        entry: "SalPixieConfigEntry",
        address: int,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}_routing_metric"
        self._attr_device_info = DEVICE_INFO(
            entry, address, coordinator.data.get(address) if coordinator.data else None,
        )

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        status = self.coordinator.data.get(self._address)
        if status is None:
            return None
        return status.sno


class PixieConnectedDeviceSensor(CoordinatorEntity[PixieCoordinator], SensorEntity):
    """The mesh switch HA is currently talking to over BLE.

    Any Pixie switch can act as the radio entry point — the integration
    picks whichever one has the best RSSI at setup time. This sensor
    reports which one that is right now, which is useful when diagnosing
    range or reconnect issues.
    """

    has_entity_name = True
    _attr_name = "Connected device"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: "SalPixieConfigEntry",
        coordinator: PixieCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_mesh_connected_device"
        self._attr_device_info = MESH_DEVICE_INFO(entry)

    @property
    def native_value(self) -> str | None:
        client = self.coordinator.client
        mac = client._gw_mac
        if mac == b"\x00" * 6:
            return None
        dev_addr = mac[5]

        from homeassistant.helpers import device_registry as dr
        dev_registry = dr.async_get(self.hass)
        for entry in dev_registry.devices.values():
            for identifier in entry.identifiers:
                if identifier[0] == DOMAIN and identifier[1].endswith(f"_{dev_addr}"):
                    return entry.name
        return client.gateway_mac

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        client = self.coordinator.client
        return {
            "mac": client.gateway_mac,
            "ble_address": client.gateway_address,
        }
