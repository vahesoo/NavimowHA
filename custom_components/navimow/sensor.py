"""Sensor platform for Navimow integration."""
from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NavimowCoordinator
from .location import vehicle_state_name


@dataclass(frozen=True, kw_only=True)
class NavimowSensorEntityDescription(SensorEntityDescription):
    """Describes Navimow sensor entity."""

    value_fn: Callable[[NavimowCoordinator], Any]


SENSOR_DESCRIPTIONS: tuple[NavimowSensorEntityDescription, ...] = (
    NavimowSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: (
            state.battery if (state := coordinator.get_device_state()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="zone",
        name="Zone",
        icon="mdi:map-marker",
        value_fn=lambda c: (
            (
                loc.get("mow_boundary")
                if loc.get("mow_boundary") is not None
                else loc.get("partition")
            )
            if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="position_x",
        name="Position X",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (loc.get("x") if (loc := c.get_device_location()) else None),
    ),
    NavimowSensorEntityDescription(
        key="position_y",
        name="Position Y",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (loc.get("y") if (loc := c.get_device_location()) else None),
    ),
    NavimowSensorEntityDescription(
        key="heading",
        name="Heading",
        native_unit_of_measurement="°",
        icon="mdi:compass",
        value_fn=lambda c: (
            round(math.degrees(loc["theta"]) % 360, 1)
            if (loc := c.get_device_location()) and loc.get("theta") is not None
            else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="mowing_zone",
        name="Mowing zone",
        icon="mdi:robot-mower",
        value_fn=lambda c: (
            (
                loc.get("partition")
                if loc.get("partition") is not None
                else loc.get("mow_boundary")
            )
            if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="dock_x",
        name="Dock X",
        native_unit_of_measurement="m",
        icon="mdi:home-map-marker",
        value_fn=lambda c: (
            round(d["x"], 2) if (d := c.get_dock_position()) and d.get("n") else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="dock_y",
        name="Dock Y",
        native_unit_of_measurement="m",
        icon="mdi:home-map-marker",
        value_fn=lambda c: (
            round(d["y"], 2) if (d := c.get_dock_position()) and d.get("n") else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="mow_progress",
        name="Mow progress",
        icon="mdi:progress-check",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (
            (loc.get("mow_progress") or 0) / 100
            if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="mowing_percentage",
        name="Mowing percentage",
        icon="mdi:percent-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (
            loc.get("mowing_percentage") if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="subtotal_area",
        name="Current job area",
        icon="mdi:texture-box",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (
            loc.get("subtotal_area") if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="mowing_week_area",
        name="Weekly mowing area",
        icon="mdi:calendar-week",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (
            loc.get("mowing_week_area") if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="active_task",
        name="Task delay raw",
        icon="mdi:timer-alert-outline",
        value_fn=lambda c: (
            str(loc.get("active_task")).lower()
            if (loc := c.get_device_location()) and loc.get("active_task") is not None else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="vehicle_state",
        name="Vehicle state",
        icon="mdi:robot-mower",
        value_fn=lambda c: (
            vehicle_state_name(loc.get("vehicle_state"))
            if (loc := c.get_device_location()) else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navimow sensors from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]

    entities: list[NavimowSensor] = []
    for device in devices:
        coordinator = coordinators[device.id]
        for description in SENSOR_DESCRIPTIONS:
            cls = (
                NavimowDockSensor
                if description.key in ("dock_x", "dock_y")
                else NavimowSensor
            )
            entities.append(
                cls(
                    coordinator=coordinator,
                    entity_description=description,
                )
            )
    async_add_entities(entities)


class NavimowSensor(CoordinatorEntity[NavimowCoordinator], SensorEntity):
    """Representation of a Navimow sensor."""

    entity_description: NavimowSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NavimowCoordinator,
        entity_description: NavimowSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = entity_description

        device = coordinator.device
        self._attr_unique_id = f"{DOMAIN}_{device.id}_{entity_description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Navimow",
            model=device.model or "Unknown",
            sw_version=device.firmware_version or None,
            serial_number=device.serial_number or device.id,
        )

    @property
    def available(self) -> bool:
        if self.coordinator.get_device_state() is not None:
            return True
        return super().available

    @property
    def native_value(self) -> Any:
        """Return sensor value from coordinator."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the extra real-time location fields on the zone sensor."""
        if self.entity_description.key != "zone":
            return None
        loc = self.coordinator.get_device_location()
        if not loc:
            return None
        return {
            "partition_ids": loc.get("partition_ids"),
            "partition": loc.get("partition"),
            "active_mowing_zone": loc.get("mow_boundary"),
            "zone_source": "partitionIds" if loc.get("partition") is not None else "currentMowBoundary",
            "active_task": loc.get("active_task"),
            "task_delay_raw": loc.get("task_delay"),
            "vehicle_state": loc.get("vehicle_state"),
            "vehicle_state_name": vehicle_state_name(loc.get("vehicle_state")),
            "pose_time": loc.get("pose_time"),
            "active_task_time": loc.get("active_task_time"),
            "delay_time": loc.get("delay_time"),
            "partition_time": loc.get("partition_time"),
            "progress_time": loc.get("progress_time"),
            "mow_boundary_time": loc.get("mow_boundary_time"),
            "mow_boundary": loc.get("mow_boundary"),
            "mow_progress": loc.get("mow_progress"),
            "mowing_percentage": loc.get("mowing_percentage"),
            "subtotal_area": loc.get("subtotal_area"),
            "mowing_week_area": loc.get("mowing_week_area"),
            "mow_start_type": loc.get("mow_start_type"),
            "action": loc.get("action"),
            "sub_action": loc.get("sub_action"),
            "map_work_position": loc.get("map_work_position"),
        }


class NavimowDockSensor(NavimowSensor, RestoreSensor):
    """Dock position sensor that survives HA restarts.

    The dock estimate is learned in-memory by the coordinator while the mower
    is docked/charging. After a restart, the previously learned value is
    restored from HA's state storage and shown until live samples replace it.
    """

    _restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            try:
                self._restored_value = float(data.native_value)
            except (TypeError, ValueError):
                self._restored_value = None

    @property
    def native_value(self) -> Any:
        live = self.entity_description.value_fn(self.coordinator)
        return live if live is not None else self._restored_value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        d = self.coordinator.get_dock_position()
        return {
            "samples": (d or {}).get("n", 0),
            "source": "live" if d and d.get("n") else (
                "restored" if self._restored_value is not None else "none"
            ),
        }
