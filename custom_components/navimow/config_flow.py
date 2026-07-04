"""Config flow for Navimow integration."""
from __future__ import annotations
import logging
import voluptuous as vol
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .auth import NavimowOAuth2Implementation
from .channel import channels_from_options
from .const import (
    DOMAIN,
    CLIENT_ID,
    CLIENT_SECRET,
    API_BASE_URL,
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.debug("Navimow config_flow module imported")


class NavimowOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle a Navimow OAuth2 config flow."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def oauth2_implementation(self) -> NavimowOAuth2Implementation:
        """Return the OAuth2 implementation."""
        _LOGGER.debug(
            "Creating OAuth2 implementation for domain=%s, client_id_set=%s, client_secret_set=%s",
            DOMAIN,
            bool(CLIENT_ID),
            bool(CLIENT_SECRET),
        )
        implementation = NavimowOAuth2Implementation(
            self.hass, DOMAIN, CLIENT_ID, CLIENT_SECRET
        )
        # Ensure HA has the implementation registered before redirect/callback.
        config_entry_oauth2_flow.async_register_implementation(
            self.hass, DOMAIN, implementation
        )
        _LOGGER.debug("OAuth2 implementation registered for domain=%s", DOMAIN)
        return implementation

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        _LOGGER.debug("Starting OAuth2 flow: source=%s", self.source)
        # 检查是否已经配置
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # 检查必要的配置
        if not CLIENT_ID or not CLIENT_SECRET:
            _LOGGER.error(
                "Missing OAuth2 client configuration: client_id_set=%s, client_secret_set=%s",
                bool(CLIENT_ID),
                bool(CLIENT_SECRET),
            )
            return self.async_abort(
                reason="missing_config",
                description_placeholders={
                    "error": "CLIENT_ID 或 CLIENT_SECRET 未配置，请在 const.py 中配置"
                },
            )

        # Ensure implementation is registered before authorize step.
        _LOGGER.debug("Registering OAuth2 implementation before authorize step")
        _ = self.oauth2_implementation
        # 仅一个 OAuth2 实现，直接进入授权步骤
        _LOGGER.debug("Proceeding to OAuth2 authorize step")
        return await super().async_step_user()

    async def async_step_oauth2_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ensure implementation exists before redirect."""
        _LOGGER.debug("Entering oauth2_authorize step")
        # Force register implementation in case HA missed it.
        _ = self.oauth2_implementation
        return await super().async_step_oauth2_authorize(user_input)

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=None,
            )

        # 仅一个 OAuth2 实现，直接进入授权步骤
        return await super().async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create an entry for the flow, or update existing entry for reauth."""
        # HA 已经自动处理了 token 交换，data["token"] 已包含 token 信息
        # 如果是 reauth，HA 会自动更新 entry
        if self.source == config_entries.SOURCE_REAUTH:
            existing_entry = self.entry
            self.hass.config_entries.async_update_entry(
                existing_entry,
                data={
                    **existing_entry.data,
                    **data,  # 包含新的 token
                },
            )
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        # 保存配置和 token（HA 已自动处理 token 交换）
        return self.async_create_entry(
            title="Navimow",
            data={
                "auth_implementation": DOMAIN,
                **data,  # 包含 token（由 HA 自动处理）
                "api_base_url": API_BASE_URL,
                "mqtt_broker": MQTT_BROKER,
                "mqtt_port": MQTT_PORT,
                "mqtt_username": MQTT_USERNAME,
                "mqtt_password": MQTT_PASSWORD,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return NavimowOptionsFlowHandler(config_entry)


class NavimowOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Navimow options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    def _device_choices(self) -> dict[str, str]:
        """Return available mower choices from the loaded integration data."""
        data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        devices = data.get("devices", [])
        choices: dict[str, str] = {}
        for device in devices:
            device_id = getattr(device, "id", None)
            if not device_id:
                continue
            name = getattr(device, "name", None) or device_id
            choices[str(device_id)] = f"{name} ({device_id})"
        return choices

    def _schema_for_device(self, device_id_default: str | None = None) -> vol.Schema:
        """Build the options form schema."""
        channels = channels_from_options(self._config_entry.options)
        device_choices = self._device_choices()

        if device_id_default is None:
            device_id_default = next(iter(device_choices), "")

        existing = None
        if device_id_default and channels.get(device_id_default):
            existing = channels[device_id_default][0]

        name_default = existing.name if existing else "gate"

        x_min_default = existing.x_min if existing else 0.0
        x_max_default = existing.x_max if existing else 0.0
        y_min_default = existing.y_min if existing else 0.0
        y_max_default = existing.y_max if existing else 0.0

        if device_choices:
            device_field = vol.In(device_choices)
        else:
            device_field = str

        return vol.Schema(
            {
                vol.Required("device_id", default=device_id_default): device_field,
                vol.Required("channel_name", default=name_default): str,
                vol.Required("enabled", default=True): bool,
                vol.Required("x_min", default=x_min_default): vol.Coerce(float),
                vol.Required("x_max", default=x_max_default): vol.Coerce(float),
                vol.Required("y_min", default=y_min_default): vol.Coerce(float),
                vol.Required("y_max", default=y_max_default): vol.Coerce(float),
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage channel options.

        Run Configure once for each mower/channel. The selected channel is
        added or updated without touching channels configured for other mowers.
        Set enabled=false to remove the selected channel.
        """
        if user_input is not None:
            options = dict(self._config_entry.options)
            raw_channels = dict(options.get("channels") or {})

            device_id = str(user_input["device_id"])
            channel_name = str(user_input.get("channel_name") or "gate")
            device_channels = dict(raw_channels.get(device_id) or {})

            if user_input.get("enabled", True):
                x1 = float(user_input["x_min"])
                x2 = float(user_input["x_max"])
                y1 = float(user_input["y_min"])
                y2 = float(user_input["y_max"])
                device_channels[channel_name] = {
                    "x_min": min(x1, x2),
                    "x_max": max(x1, x2),
                    "y_min": min(y1, y2),
                    "y_max": max(y1, y2),
                }
                raw_channels[device_id] = device_channels
            else:
                device_channels.pop(channel_name, None)
                if device_channels:
                    raw_channels[device_id] = device_channels
                else:
                    raw_channels.pop(device_id, None)

            options["channels"] = raw_channels
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._schema_for_device(),
        )
