"""Lawn mower platform for Navimow integration."""
import logging
from typing import Any

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from mower_sdk.api import MowerAPI
from mower_sdk.models import DeviceStateMessage, MowerCommand

from .const import DOMAIN, MOWER_STATUS_TO_ACTIVITY
from .coordinator import NavimowCoordinator
from .location import vehicle_state_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up lawn mower entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api: MowerAPI = data["api"]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]

    entities = []
    for device in devices:
        entities.append(
            NavimowLawnMower(
                coordinator=coordinators[device.id],
                api=api,
                device_id=device.id,
                device_name=device.name,
                device_info=device,
            )
        )

    async_add_entities(entities)


class NavimowLawnMower(CoordinatorEntity[NavimowCoordinator], LawnMowerEntity):
    """Representation of a Navimow lawn mower."""

    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(
        self,
        coordinator: NavimowCoordinator,
        api: MowerAPI,
        device_id: str,
        device_name: str,
        device_info: Any,
    ) -> None:
        """Initialize the lawn mower entity."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._device_name = device_name
        self._device_info = device_info

        # 设置实体属性
        self._attr_name = device_name
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="Navimow",
            model=device_info.model or "Unknown",
            sw_version=device_info.firmware_version or None,
            serial_number=device_info.serial_number or self._device_id,
        )

    @property
    def available(self) -> bool:
        """Keep entity available as long as cached state exists.

        Broker-initiated MQTT disconnects (with paho auto-reconnect) are
        transient; the entity should not flip to unavailable during the
        brief reconnection window.
        """
        if self.coordinator.get_device_state() is not None or self.coordinator.has_recent_good_data():
            return True
        return super().available

    @property
    def activity(self) -> LawnMowerActivity:
        """Return the current activity of the lawn mower."""
        state = self.coordinator.get_device_state()
        if not state:
            return None
        activity = MOWER_STATUS_TO_ACTIVITY.get(state.state)
        if activity is None:
            return None
        return LawnMowerActivity(activity)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        state: DeviceStateMessage | None = self.coordinator.get_device_state()
        attrs = self.coordinator.get_device_attributes()
        if not state:
            return {}
        attributes: dict[str, Any] = {
            "battery": state.battery,
            "status": state.state,
            "charging_state": self.coordinator.get_charging_state(),
            "mqtt_connected": self.coordinator.is_mqtt_connected(),
        }
        if state.signal_strength is not None:
            attributes["signal_strength"] = state.signal_strength
        if state.position:
            attributes["position"] = state.position
        if state.error:
            attributes["error"] = state.error
        if state.metrics:
            attributes["metrics"] = state.metrics
        loc = self.coordinator.get_device_location()
        if loc:
            attributes["active_task"] = loc.get("active_task")
            attributes["task_delay_raw"] = loc.get("task_delay")
            attributes["vehicle_state"] = loc.get("vehicle_state")
            attributes["vehicle_state_name"] = vehicle_state_name(loc.get("vehicle_state"))
            attributes["current_zone"] = loc.get("mow_boundary")
            attributes["planned_zones"] = loc.get("partition_ids")
            attributes["zone_source"] = "partitionIds" if loc.get("partition") is not None else "currentMowBoundary"
            attributes["target_mowing_zone"] = loc.get("partition")
            attributes["mow_progress_raw"] = loc.get("mow_progress")
            attributes["mow_progress"] = (
                (loc.get("mow_progress") or 0) / 100
                if loc.get("mow_progress") is not None else None
            )
            attributes["mowing_percentage"] = loc.get("mowing_percentage")
            attributes["current_job_area"] = loc.get("subtotal_area")
            attributes["weekly_mowing_area"] = loc.get("mowing_week_area")
            attributes["mow_start_type"] = loc.get("mow_start_type")
            attributes["action"] = loc.get("action")
            attributes["sub_action"] = loc.get("sub_action")
            attributes["pose_time"] = loc.get("pose_time")
            attributes["active_task_time"] = loc.get("active_task_time")
            attributes["delay_time"] = loc.get("delay_time")
            attributes["partition_time"] = loc.get("partition_time")
            attributes["progress_time"] = loc.get("progress_time")
            attributes["mow_boundary_time"] = loc.get("mow_boundary_time")
        if attrs:
            attributes["attributes"] = attrs.attributes
        return attributes

    async def _async_send_command(self, command: MowerCommand, label: str) -> None:
        """发送指令前先刷新 token，避免 token 过期导致 CODE_OAUTH_INFO_ILLEGAL。"""
        await self.coordinator._async_ensure_valid_token()
        await self._api.async_send_command(self._device_id, command)
        _LOGGER.info("%s for device %s", label, self._device_id)
        await self.coordinator.async_request_refresh()

    async def async_start_mowing(self) -> None:
        """Start mowing."""
        try:
            await self._async_send_command(MowerCommand.START, "Started mowing")
        except Exception as err:
            _LOGGER.error(
                "Failed to start mowing for device %s: %s", self._device_id, err
            )
            raise

    async def async_pause(self) -> None:
        """Pause mowing."""
        try:
            await self._async_send_command(MowerCommand.PAUSE, "Paused mowing")
        except Exception as err:
            _LOGGER.error(
                "Failed to pause mowing for device %s: %s", self._device_id, err
            )
            raise

    async def async_dock(self) -> None:
        """Dock the mower."""
        try:
            await self._async_send_command(MowerCommand.DOCK, "Docked")
        except Exception as err:
            _LOGGER.error("Failed to dock device %s: %s", self._device_id, err)
            raise

    async def async_resume(self) -> None:
        """Resume mowing."""
        try:
            await self._async_send_command(MowerCommand.RESUME, "Resumed mowing")
        except Exception as err:
            _LOGGER.error(
                "Failed to resume mowing for device %s: %s", self._device_id, err
            )
            raise
