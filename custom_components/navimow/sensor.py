"""Sensor platform for Navimow integration."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
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
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NavimowCoordinator
from .location import vehicle_state_name


@dataclass(frozen=True, kw_only=True)
class NavimowSensorEntityDescription(SensorEntityDescription):
    """Describes Navimow sensor entity."""

    value_fn: Callable[[NavimowCoordinator], Any]
    attr_fn: Callable[[NavimowCoordinator], dict[str, Any] | None] | None = None


@dataclass(frozen=True, kw_only=True)
class NavimowZoneSensorDescription(SensorEntityDescription):
    """Describes one per-zone sensor."""

    value_fn: Callable[[dict[str, Any] | None], Any]


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _vehicle_state_code(coordinator: NavimowCoordinator) -> Any:
    loc = coordinator.get_device_location()
    if not loc:
        return None
    return loc.get("vehicle_state")


def _vehicle_state_name(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return vehicle_state_name(value)
    return vehicle_state_name(number) or f"state_{number}"


def _state_attr(coordinator: NavimowCoordinator, *names: str) -> Any:
    state = coordinator.get_device_state()
    if state is None:
        return None
    for name in names:
        if isinstance(state, dict) and name in state:
            return state.get(name)
        if hasattr(state, name):
            return getattr(state, name)
    error = None
    if isinstance(state, dict):
        error = state.get("error")
    elif hasattr(state, "error"):
        error = getattr(state, "error")
    if error is not None:
        for name in names:
            if isinstance(error, dict) and name in error:
                return error.get(name)
            if hasattr(error, name):
                return getattr(error, name)
    return None


def _error_code(coordinator: NavimowCoordinator) -> Any:
    return _state_attr(coordinator, "error_code", "errorCode", "code", "err_code", "errCode")


def _error_message(coordinator: NavimowCoordinator) -> Any:
    message = _state_attr(
        coordinator,
        "error_message",
        "errorMessage",
        "message",
        "msg",
        "description",
    )
    if message:
        return message
    code = _error_code(coordinator)
    return str(code) if code else None


def _last_event_value(coordinator: NavimowCoordinator) -> Any:
    event = coordinator.get_last_event()
    if not event:
        return None
    for key in ("event", "eventType", "type", "code", "name", "title"):
        if event.get(key) is not None:
            return event.get(key)
    return "event"


def _last_event_attrs(coordinator: NavimowCoordinator) -> dict[str, Any] | None:
    return coordinator.get_last_event()


def _zone_attrs(coordinator: NavimowCoordinator) -> dict[str, Any] | None:
    loc = coordinator.get_device_location()
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
        "vehicle_state_name": _vehicle_state_name(loc.get("vehicle_state")),
        "pose_time": loc.get("pose_time"),
        "active_task_time": loc.get("active_task_time"),
        "delay_time": loc.get("delay_time"),
        "partition_time": loc.get("partition_time"),
        "progress_time": loc.get("progress_time"),
        "mow_boundary_time": loc.get("mow_boundary_time"),
        "mow_boundary": loc.get("mow_boundary"),
        "mow_progress": loc.get("mow_progress"),
        "mow_progress_percent": loc.get("mow_progress_percent"),
        "mowing_percentage": loc.get("mowing_percentage"),
        "subtotal_area": loc.get("subtotal_area"),
        "mowing_week_area": loc.get("mowing_week_area"),
        "mow_start_type": loc.get("mow_start_type"),
        "action": loc.get("action"),
        "sub_action": loc.get("sub_action"),
        "map_work_position": loc.get("map_work_position"),
        "error_code": _error_code(coordinator),
        "error_message": _error_message(coordinator),
    }


RESTORED_SENSOR_KEYS: set[str] = {
    "zone",
    "mowing_zone",
    "mow_progress",
    "mowing_percentage",
    "subtotal_area",
    "mowing_week_area",
    "active_task",
    "vehicle_state",
    "vehicle_state_code",
    "charging_state",
}


SENSOR_DESCRIPTIONS: tuple[NavimowSensorEntityDescription, ...] = (
    NavimowSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: state.battery if (state := c.get_device_state()) else None,
    ),
    NavimowSensorEntityDescription(
        key="charging_state",
        name="Charging state",
        icon="mdi:battery-charging-medium",
        value_fn=lambda c: c.get_charging_state(),
    ),
    NavimowSensorEntityDescription(
        key="zone",
        name="Zone",
        icon="mdi:map-marker",
        value_fn=lambda c: (
            (loc.get("mow_boundary") if loc.get("mow_boundary") is not None else loc.get("partition"))
            if (loc := c.get_device_location()) else None
        ),
        attr_fn=_zone_attrs,
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
            if (loc := c.get_device_location()) and loc.get("theta") is not None else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="mowing_zone",
        name="Mowing zone",
        icon="mdi:robot-mower",
        value_fn=lambda c: (
            (loc.get("partition") if loc.get("partition") is not None else loc.get("mow_boundary"))
            if (loc := c.get_device_location()) else None
        ),
    ),
    NavimowSensorEntityDescription(
        key="dock_x",
        name="Dock X",
        native_unit_of_measurement="m",
        icon="mdi:home-map-marker",
        value_fn=lambda c: round(d["x"], 2) if (d := c.get_dock_position()) and d.get("n") else None,
        attr_fn=lambda c: c.get_dock_debug(),
    ),
    NavimowSensorEntityDescription(
        key="dock_y",
        name="Dock Y",
        native_unit_of_measurement="m",
        icon="mdi:home-map-marker",
        value_fn=lambda c: round(d["y"], 2) if (d := c.get_dock_position()) and d.get("n") else None,
        attr_fn=lambda c: c.get_dock_debug(),
    ),
    NavimowSensorEntityDescription(
        key="mow_progress",
        name="Mow progress",
        icon="mdi:progress-check",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: loc.get("mow_progress_percent") if (loc := c.get_device_location()) else None,
    ),
    NavimowSensorEntityDescription(
        key="mowing_percentage",
        name="Mowing percentage",
        icon="mdi:percent-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: loc.get("mowing_percentage") if (loc := c.get_device_location()) else None,
    ),
    NavimowSensorEntityDescription(
        key="subtotal_area",
        name="Current job area",
        icon="mdi:texture-box",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: loc.get("subtotal_area") if (loc := c.get_device_location()) else None,
    ),
    NavimowSensorEntityDescription(
        key="mowing_week_area",
        name="Weekly mowing area",
        icon="mdi:calendar-week",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: loc.get("mowing_week_area") if (loc := c.get_device_location()) else None,
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
        key="vehicle_state_code",
        name="Vehicle state code",
        icon="mdi:numeric",
        value_fn=_vehicle_state_code,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NavimowSensorEntityDescription(
        key="vehicle_state",
        name="Vehicle state",
        icon="mdi:robot-mower",
        value_fn=lambda c: _vehicle_state_name(_vehicle_state_code(c)),
    ),
    NavimowSensorEntityDescription(
        key="last_event",
        name="Last event",
        icon="mdi:message-alert-outline",
        value_fn=_last_event_value,
        attr_fn=_last_event_attrs,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NavimowSensorEntityDescription(
        key="zone_history",
        name="Zone history",
        icon="mdi:map-clock-outline",
        value_fn=lambda c: c.get_zone_history_summary().get("zone_count"),
        attr_fn=lambda c: c.get_zone_history_summary(),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NavimowSensorEntityDescription(
        key="error_code",
        name="Error code",
        icon="mdi:alert-circle-outline",
        value_fn=lambda c: _error_code(c),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NavimowSensorEntityDescription(
        key="error_message",
        name="Error message",
        icon="mdi:alert-outline",
        value_fn=lambda c: _error_message(c),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


ZONE_SENSOR_DESCRIPTIONS: tuple[NavimowZoneSensorDescription, ...] = (
    NavimowZoneSensorDescription(
        key="last_mowed",
        name="Last mowed",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda stats: _parse_dt((stats or {}).get("last_mowed")),
    ),
    NavimowZoneSensorDescription(
        key="progress",
        name="Progress",
        icon="mdi:progress-check",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: (stats or {}).get("last_progress") if stats else None,
    ),
    NavimowZoneSensorDescription(
        key="last_completed",
        name="Last completed",
        icon="mdi:check-circle-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda stats: _parse_dt((stats or {}).get("last_completed")),
    ),
    NavimowZoneSensorDescription(
        key="last_area",
        name="Last area",
        icon="mdi:texture-box",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: (stats or {}).get("last_area") if stats else None,
    ),
    NavimowZoneSensorDescription(
        key="session_count",
        name="Session count",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: (stats or {}).get("session_count"),
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

    entities: list[SensorEntity] = []
    created_zone_entities: set[tuple[str, str, str]] = set()

    def add_zone_entities(coordinator: NavimowCoordinator, zone_id: str) -> None:
        new_entities: list[SensorEntity] = []
        for description in ZONE_SENSOR_DESCRIPTIONS:
            key = (coordinator.device.id, str(zone_id), description.key)
            if key in created_zone_entities:
                continue
            created_zone_entities.add(key)
            new_entities.append(NavimowZoneSensor(coordinator, str(zone_id), description))
        if new_entities:
            async_add_entities(new_entities)

    for device in devices:
        coordinator = coordinators[device.id]
        for description in SENSOR_DESCRIPTIONS:
            if description.key in ("dock_x", "dock_y"):
                cls = NavimowDockSensor
            elif description.key in RESTORED_SENSOR_KEYS:
                cls = NavimowRestoredSensor
            else:
                # Position X/Y/heading intentionally use the plain live sensor
                # and read the same live MQTT location cache as the earlier fork.
                # They do not restore from HA Recorder, but they also do not use
                # the separate pose-only cache introduced during testing.
                cls = NavimowSensor
            entities.append(cls(coordinator=coordinator, entity_description=description))
        for zone_id in coordinator.known_zone_ids():
            for description in ZONE_SENSOR_DESCRIPTIONS:
                created_zone_entities.add((device.id, str(zone_id), description.key))
                entities.append(NavimowZoneSensor(coordinator, str(zone_id), description))
        coordinator.register_zone_discovery_callback(
            lambda zone_id, coord=coordinator: add_zone_entities(coord, zone_id)
        )

    async_add_entities(entities)


class NavimowSensor(CoordinatorEntity[NavimowCoordinator], SensorEntity):
    """Representation of a Navimow sensor."""

    entity_description: NavimowSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: NavimowCoordinator, entity_description: NavimowSensorEntityDescription) -> None:
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
        if self.coordinator.get_device_state() is not None or self.coordinator.has_recent_good_data():
            return True
        return super().available

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn:
            return self.entity_description.attr_fn(self.coordinator)
        return None


class NavimowRestoredSensor(NavimowSensor, RestoreSensor):
    """Sensor that restores the last known value after Home Assistant restarts."""

    _restored_value: Any = None
    _has_restored_value: bool = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            self._restored_value = data.native_value
            self._has_restored_value = data.native_value is not None

    @property
    def native_value(self) -> Any:
        live = self.entity_description.value_fn(self.coordinator)
        if live is not None:
            return live
        return self._restored_value if self._has_restored_value else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = super().extra_state_attributes
        if attrs is not None:
            attrs = dict(attrs)
            attrs["source"] = "live"
            return attrs
        if self._has_restored_value:
            return {"source": "restored"}
        return None


class NavimowDockSensor(NavimowSensor, RestoreSensor):
    """Dock position sensor that survives HA restarts and supports lock/debug."""

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
        attrs = self.entity_description.attr_fn(self.coordinator) if self.entity_description.attr_fn else {}
        if self._restored_value is not None and not (self.coordinator.get_dock_position() or {}).get("n"):
            attrs = dict(attrs or {})
            attrs["source"] = "restored"
        return attrs


class NavimowZoneSensor(CoordinatorEntity[NavimowCoordinator], RestoreSensor):
    """Per-zone history sensor with last-known-good restore support."""

    _attr_has_entity_name = True
    entity_description: NavimowZoneSensorDescription
    _restored_value: Any = None
    _has_restored_value: bool = False

    def __init__(
        self,
        coordinator: NavimowCoordinator,
        zone_id: str,
        entity_description: NavimowZoneSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.zone_id = str(zone_id)
        self.entity_description = entity_description
        device = coordinator.device
        self._attr_unique_id = f"{DOMAIN}_{device.id}_zone_{self.zone_id}_{entity_description.key}"
        self._attr_name = f"Zone {self.zone_id} {entity_description.name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Navimow",
            model=device.model or "Unknown",
            sw_version=device.firmware_version or None,
            serial_number=device.serial_number or device.id,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            self._restored_value = data.native_value
            self._has_restored_value = data.native_value is not None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.get_zone_stats(self.zone_id) is not None
            or self._has_restored_value
            or self.coordinator.has_recent_good_data()
        )

    @property
    def native_value(self) -> Any:
        live = self.entity_description.value_fn(self.coordinator.get_zone_stats(self.zone_id))
        if live is not None:
            self._restored_value = live
            self._has_restored_value = True
            return live
        return self._restored_value if self._has_restored_value else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        stats = self.coordinator.get_zone_stats(self.zone_id)
        if not stats:
            attrs: dict[str, Any] = {"zone_id": self.zone_id}
            if self._has_restored_value:
                attrs["source"] = "restored"
            return attrs
        attrs = dict(stats)
        attrs["zone_id"] = self.zone_id
        attrs["source"] = "live"
        return attrs
