"""Services for Navimow integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import NavimowCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_BLADE_HEIGHT = "set_blade_height"
SERVICE_LEARN_DOCK_POSITION = "learn_dock_position"
SERVICE_CLEAR_DOCK_POSITION_LOCK = "clear_dock_position_lock"

SERVICE_SCHEMA_SET_BLADE_HEIGHT = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("height"): vol.Coerce(int),
    }
)

SERVICE_SCHEMA_DEVICE = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
    }
)

SERVICE_SCHEMA_LEARN_DOCK = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Optional("sample_seconds", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
    }
)


def _find_coordinator(hass: HomeAssistant, device_id: str) -> NavimowCoordinator:
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if not isinstance(entry_data, dict):
            continue
        coordinators: dict[str, Any] = entry_data.get("coordinators") or {}
        coordinator = coordinators.get(str(device_id))
        if coordinator is not None:
            return coordinator
    raise HomeAssistantError(f"Navimow device not found: {device_id}")


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Navimow services once."""

    async def _handle_set_blade_height(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        height = call.data["height"]
        _LOGGER.warning(
            "Blade height change not supported via REST API (device %s, height %s)",
            device_id,
            height,
        )
        raise HomeAssistantError("Blade height change is not supported by the current REST API")

    async def _handle_learn_dock_position(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        sample_seconds = int(call.data.get("sample_seconds") or 0)
        coordinator = _find_coordinator(hass, device_id)
        result = await coordinator.async_learn_dock_position(sample_seconds=sample_seconds)
        _LOGGER.info("Learned locked Navimow dock position for %s: %s", device_id, result)

    async def _handle_clear_dock_position_lock(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        coordinator = _find_coordinator(hass, device_id)
        await coordinator.async_clear_dock_position_lock()
        _LOGGER.info("Cleared locked Navimow dock position for %s", device_id)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_BLADE_HEIGHT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_BLADE_HEIGHT,
            _handle_set_blade_height,
            schema=SERVICE_SCHEMA_SET_BLADE_HEIGHT,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_LEARN_DOCK_POSITION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_LEARN_DOCK_POSITION,
            _handle_learn_dock_position,
            schema=SERVICE_SCHEMA_LEARN_DOCK,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_DOCK_POSITION_LOCK):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_DOCK_POSITION_LOCK,
            _handle_clear_dock_position_lock,
            schema=SERVICE_SCHEMA_DEVICE,
        )
