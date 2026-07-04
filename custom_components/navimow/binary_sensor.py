"""Binary sensors for Navimow configurable channels."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
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
    """Set up Navimow channel binary sensors from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]
    channels = channels_from_options(config_entry.options)

    entities: list[NavimowChannelSensor] = []
    for device in devices:
        for box in channels.get(device.id, []):
            coordinator = coordinators[device.id]
            entities.append(NavimowChannelSensor(coordinator, box))

    async_add_entities(entities)


class NavimowChannelSensor(CoordinatorEntity[NavimowCoordinator], BinarySensorEntity):
    """True while mower X/Y is inside a configured channel box."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gate-arrow-right"

    def __init__(self, coordinator: NavimowCoordinator, channel: NavimowChannelBox) -> None:
        """Initialize channel sensor."""
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
    def is_on(self) -> bool:
        """Return true if mower is inside this configured channel box."""
        loc = self.coordinator.get_device_location()
        if not loc:
            return False
        return self.channel.contains(loc.get("x"), loc.get("y"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return channel coordinates and current mower position."""
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
