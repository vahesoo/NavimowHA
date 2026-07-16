"""Binary sensors for Navimow."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .channel import NavimowChannelBox, channels_from_options
from .const import DOMAIN
from .coordinator import NavimowCoordinator


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navimow binary sensors."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]
    channels = channels_from_options(config_entry.options)

    entities: list[BinarySensorEntity] = []
    for device in devices:
        coordinator = coordinators[device.id]
        entities.append(NavimowMqttConnectionSensor(coordinator))
        entities.append(NavimowBatteryChargingSensor(coordinator))
        for box in channels.get(device.id, []):
            entities.append(NavimowChannelSensor(coordinator, box))

    async_add_entities(entities)


class _NavimowBaseBinarySensor(CoordinatorEntity[NavimowCoordinator], BinarySensorEntity):
    """Common device metadata for Navimow binary sensors."""

    _attr_has_entity_name = True

    def _set_device_attrs(self, suffix: str, name: str) -> None:
        device = self.coordinator.device
        self._attr_unique_id = f"{DOMAIN}_{device.id}_{suffix}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Navimow",
            model=device.model or "Unknown",
            sw_version=device.firmware_version or None,
            serial_number=device.serial_number or device.id,
        )


class NavimowMqttConnectionSensor(_NavimowBaseBinarySensor):
    """Diagnostic MQTT connection sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._set_device_attrs("mqtt_connection", "MQTT connection")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_mqtt_connected()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator.get_mqtt_connection_info()


class NavimowBatteryChargingSensor(_NavimowBaseBinarySensor):
    """Inferred battery charging state."""

    _attr_icon = "mdi:battery-charging"

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._set_device_attrs("battery_charging", "Battery charging")

    @property
    def available(self) -> bool:
        return self.coordinator.get_device_state() is not None or self.coordinator.has_recent_good_data()

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.is_battery_charging()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"charging_state": self.coordinator.get_charging_state()}


class NavimowChannelSensor(CoordinatorEntity[NavimowCoordinator], BinarySensorEntity):
    """True while mower X/Y is inside a configured channel box."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gate-arrow-right"

    def __init__(self, coordinator: NavimowCoordinator, channel: NavimowChannelBox) -> None:
        super().__init__(coordinator)
        self.channel = channel
        device = coordinator.device
        self._attr_unique_id = f"{DOMAIN}_{device.id}_channel_{channel.slug}"
        self._attr_name = f"{channel.name} channel"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Navimow",
            model=device.model or "Unknown",
            sw_version=device.firmware_version or None,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.get_device_location() is not None or self.coordinator.has_recent_good_data()

    @property
    def is_on(self) -> bool:
        loc = self.coordinator.get_device_location()
        if not loc:
            return False
        return self.channel.contains(loc.get("x"), loc.get("y"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        loc = self.coordinator.get_device_location() or {}
        return {
            "channel_name": self.channel.name,
            "x_min": self.channel.x_min,
            "x_max": self.channel.x_max,
            "y_min": self.channel.y_min,
            "y_max": self.channel.y_max,
            "position_x": loc.get("x"),
            "position_y": loc.get("y"),
        }
