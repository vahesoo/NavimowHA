"""DataUpdateCoordinator for Navimow integration."""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from mower_sdk.api import MowerAPI
from mower_sdk.models import (
    Device,
    DeviceAttributesMessage,
    DeviceStateMessage,
    DeviceStatus,
)
from mower_sdk.sdk import NavimowSDK

from .const import (
    DOCK_LEARN_MIN_SAMPLES,
    DOCK_MAX_CANDIDATE_DISTANCE_M,
    DOCK_SAMPLE_WINDOW,
    DOCK_ZERO_EPSILON,
    DOMAIN,
    HTTP_FALLBACK_MIN_INTERVAL,
    LAST_KNOWN_GOOD_TTL_SECONDS,
    LIVE_STATUS_REFRESH_INTERVAL_SECONDS,
    MQTT_STALE_SECONDS,
    ZONE_HISTORY_SAVE_DELAY_SECONDS,
)
from .location import (
    DOCKED_STATES,
    distance_m,
    normalize_progress,
    update_dock_estimate,
    valid_xy,
    vehicle_state_name,
)

_LOGGER = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NavimowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Navimow data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        sdk: NavimowSDK,
        api: MowerAPI,
        device: Device,
        oauth_session: config_entry_oauth2_flow.OAuth2Session | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device.id}",
            update_interval=None,
        )
        self.sdk = sdk
        self.api = api
        self.device = device
        self.oauth_session = oauth_session
        self.data: dict[str, Any] = {}

        self._last_state: DeviceStateMessage | None = None
        self._last_attributes: DeviceAttributesMessage | None = None
        self._last_location: dict[str, Any] | None = None
        # Pure live pose cache. Updated only from MQTT type 1 posture packets.
        # Position sensors use this instead of general location/progress data so
        # HTTP/status refreshes and cached fallback data cannot create fake X/Y points.
        self._last_pose_location: dict[str, Any] | None = None
        self._last_event: dict[str, Any] | None = None

        self._last_good_update: float | None = None
        self._last_mqtt_update: float | None = None
        self._last_mqtt_state_update: float | None = None
        self._last_http_fetch: float | None = None
        self._last_data_source: str | None = None

        self._mqtt_connected = False
        self._mqtt_last_connected: str | None = None
        self._mqtt_last_disconnected: str | None = None
        self._mqtt_disconnect_count = 0
        self._mqtt_reconnect_count = 0

        self._battery_history: list[tuple[float, int | float]] = []

        self._dock_store = Store(hass, 1, f"{DOMAIN}_dock_{device.id}")
        self._dock_save_unsub: Callable[[], None] | None = None
        self._dock: dict[str, Any] | None = None
        self._dock_locked: dict[str, Any] | None = None
        self._dock_samples: list[tuple[float, float, float]] = []
        self._dock_last_candidate: dict[str, Any] | None = None
        self._dock_last_rejected_reason: str | None = None
        self._dock_last_rejected_candidate: dict[str, Any] | None = None

        self._zone_store = Store(hass, 1, f"{DOMAIN}_zone_history_{device.id}")
        self._zone_save_unsub: Callable[[], None] | None = None
        self._zone_data: dict[str, Any] = {"zones": {}}
        self._zone_discovery_callbacks: list[Callable[[str], None]] = []

    async def async_setup(self) -> None:
        """Register callbacks from SDK and load persisted data."""
        stored_dock = await self._dock_store.async_load()
        if isinstance(stored_dock, dict):
            locked = stored_dock.get("locked")
            if isinstance(locked, dict):
                self._dock_locked = locked
                self._dock = dict(locked)
            else:
                # Older patch versions stored an automatically learned dock under
                # "auto". Do not load it as the displayed dock anymore because
                # it may have been learned from a stale/shifted/0,0 coordinate.
                self._dock = None

        stored_zones = await self._zone_store.async_load()
        if isinstance(stored_zones, dict) and isinstance(stored_zones.get("zones"), dict):
            self._zone_data = stored_zones

        self.sdk.on_state(self._handle_state)
        self.sdk.on_attributes(self._handle_attributes)

    def _touch_good_data(self) -> None:
        self._last_good_update = time.monotonic()

    def _schedule_coro_threadsafe(self, coro_func: Callable[[], Any]) -> None:
        """Schedule an async helper safely from HA's loop or an MQTT worker thread.

        Do not call hass.async_create_task directly here. Some MQTT callbacks can
        reach coordinator code from a worker thread, and newer Home Assistant
        versions treat hass.async_create_task from outside the event loop as a
        thread-safety error. The coroutine is therefore created inside the HA
        event loop callback.
        """
        def _schedule_on_loop() -> None:
            self.hass.async_create_task(coro_func())

        try:
            self.hass.loop.call_soon_threadsafe(_schedule_on_loop)
        except RuntimeError as err:
            _LOGGER.warning("Failed to schedule Navimow async helper: %s", err)

    def _build_data(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "state": self._last_state,
            "attributes": self._last_attributes,
            "location": self._last_location,
            "pose": self._last_pose_location,
            "event": self._last_event,
            "meta": {
                "last_data_source": self._last_data_source,
                "last_good_update_monotonic": self._last_good_update,
                "last_mqtt_update_monotonic": self._last_mqtt_update,
                "last_mqtt_state_update_monotonic": self._last_mqtt_state_update,
                "last_http_fetch_monotonic": self._last_http_fetch,
                "mqtt_connected": self._mqtt_connected,
                "mqtt_last_connected": self._mqtt_last_connected,
                "mqtt_last_disconnected": self._mqtt_last_disconnected,
                "mqtt_disconnect_count": self._mqtt_disconnect_count,
                "mqtt_reconnect_count": self._mqtt_reconnect_count,
            },
        }

    def _device_status_to_state(self, status: DeviceStatus) -> DeviceStateMessage:
        error: dict[str, Any] | None = None
        if status.error_code and status.error_code.value != "none":
            error = {
                "code": status.error_code.value,
                "message": status.error_message,
            }
        return DeviceStateMessage(
            device_id=status.device_id,
            timestamp=status.timestamp,
            state=status.status.value,
            battery=status.battery,
            signal_strength=status.signal_strength,
            position=status.position,
            error=error,
            metrics=None,
        )

    def _battery_value(self, state: Any) -> float | None:
        try:
            value = float(getattr(state, "battery", None))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def _should_reject_non_mqtt_state(self, state: DeviceStateMessage, source: str) -> bool:
        """Return True when a non-MQTT state looks like stale cached data.

        Logs showed periodic 100 -> 52 -> 100 battery spikes. Those spikes are
        almost certainly stale SDK/HTTP data written over fresher MQTT state.
        Do not overwrite a recent known-good MQTT state with a large battery
        jump from cache/HTTP.
        """
        if source == "mqtt_push" or self._last_state is None:
            return False
        current = self._battery_value(self._last_state)
        incoming = self._battery_value(state)
        if current is None or incoming is None:
            return False
        now = time.monotonic()
        mqtt_state_age = (
            now - self._last_mqtt_state_update
            if self._last_mqtt_state_update is not None
            else None
        )
        # Large sudden battery changes from non-MQTT sources shortly after a
        # MQTT state update are treated as stale. Normal battery changes are
        # still allowed.
        if mqtt_state_age is not None and mqtt_state_age <= 10 * 60 and abs(incoming - current) >= 15:
            _LOGGER.debug(
                "Ignoring stale-looking %s state for %s: battery %.1f -> %.1f, mqtt_state_age=%.1fs",
                source,
                self.device.id,
                current,
                incoming,
                mqtt_state_age,
            )
            return True
        return False

    def _apply_state(self, state: DeviceStateMessage, source: str) -> bool:
        """Apply a mower state if it is not stale-looking fallback data."""
        if self._should_reject_non_mqtt_state(state, source):
            return False
        self._last_state = state
        self._record_battery(getattr(state, "battery", None))
        if source == "mqtt_push":
            self._last_mqtt_state_update = time.monotonic()
        self._last_data_source = source
        self._touch_good_data()
        return True

    async def _async_ensure_valid_token(self) -> str | None:
        if not self.oauth_session:
            return None
        try:
            token: dict[str, Any] | None
            if hasattr(self.oauth_session, "async_ensure_token_valid"):
                await self.oauth_session.async_ensure_token_valid()
                token = self.oauth_session.token
            elif hasattr(self.oauth_session, "async_get_valid_token"):
                token = await self.oauth_session.async_get_valid_token()
            else:
                token = self.oauth_session.token
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning(
                "Token refresh failed, falling back to cached token: %s", err
            )
            cached = getattr(self.oauth_session, "token", None)
            if cached and cached.get("access_token"):
                token = cached
            else:
                raise ConfigEntryAuthFailed(
                    f"Token refresh failed and no cached token available: {err}"
                ) from err
        if not token or not token.get("access_token"):
            raise ConfigEntryAuthFailed("No access token after refresh")
        access_token = token["access_token"]
        self.api.set_token(access_token)
        return access_token

    async def async_force_http_status_refresh(self) -> None:
        """Force-refresh battery/state from HTTP API without touching live MQTT data."""
        now = time.monotonic()
        try:
            await self._async_ensure_valid_token()
            status = await self.api.async_get_device_status(self.device.id)
            state = self._device_status_to_state(status)
            self._last_http_fetch = now
            if self._apply_state(state, "http_status_timer"):
                self.async_set_updated_data(self._build_data())
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.debug(
                "Forced HTTP status refresh failed for device %s; keeping previous state: %s",
                self.device.id,
                err,
            )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._async_ensure_valid_token()
        except ConfigEntryAuthFailed:
            raise

        cached_state = self.sdk.get_cached_state(self.device.id)
        now = time.monotonic()
        state_cache_allowed = (
            cached_state is not None
            and (
                self._last_state is None
                or self._last_mqtt_state_update is None
                or now - self._last_mqtt_state_update > MQTT_STALE_SECONDS
            )
        )
        if state_cache_allowed:
            self._apply_state(cached_state, "mqtt_cache")

        cached_attrs = self.sdk.get_cached_attributes(self.device.id)
        if cached_attrs is not None:
            self._last_attributes = cached_attrs
            self._touch_good_data()

        is_mqtt_stale = (
            self._last_mqtt_update is None
            or now - self._last_mqtt_update > MQTT_STALE_SECONDS
        )
        due_live_status_refresh = (
            self._last_http_fetch is None
            or now - self._last_http_fetch > LIVE_STATUS_REFRESH_INTERVAL_SECONDS
        )
        can_http_fallback = (
            self._last_http_fetch is None
            or now - self._last_http_fetch > HTTP_FALLBACK_MIN_INTERVAL
        )

        if due_live_status_refresh or (is_mqtt_stale and can_http_fallback):
            try:
                status = await self.api.async_get_device_status(self.device.id)
                state = self._device_status_to_state(status)
                self._last_http_fetch = now
                self._apply_state(
                    state,
                    "http_status_refresh" if not is_mqtt_stale else "http_fallback",
                )
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "HTTP status refresh failed for device %s; keeping previous state: %s",
                    self.device.id,
                    err,
                )

        self.data = self._build_data()
        return self.data

    def _handle_state(self, state: DeviceStateMessage) -> None:
        if state.device_id != self.device.id:
            return
        self._last_mqtt_update = time.monotonic()
        self._last_data_source = "mqtt_push"
        self.hass.loop.call_soon_threadsafe(self._update_from_state, state)

    def _handle_attributes(self, attrs: DeviceAttributesMessage) -> None:
        if attrs.device_id != self.device.id:
            return
        self._last_mqtt_update = time.monotonic()
        self.hass.loop.call_soon_threadsafe(self._update_from_attributes, attrs)

    def _update_from_state(self, state: DeviceStateMessage) -> None:
        self._apply_state(state, "mqtt_push")
        self.async_set_updated_data(self._build_data())

    def _update_from_attributes(self, attrs: DeviceAttributesMessage) -> None:
        self._last_attributes = attrs
        self._touch_good_data()
        self.async_set_updated_data(self._build_data())

    def ingest_location(self, location: dict) -> None:
        if not isinstance(location, dict):
            return
        if location.get("device_id") not in (None, self.device.id):
            return
        self._last_mqtt_update = time.monotonic()
        self._last_location = location
        if location.get("_pose_updated"):
            self._last_pose_location = {
                "device_id": self.device.id,
                "x": location.get("x"),
                "y": location.get("y"),
                "theta": location.get("theta"),
                "pose_time": location.get("pose_time"),
                "vehicle_state": location.get("vehicle_state"),
            }
        _LOGGER.debug(
            "NAVIMOW_INGEST_LOCATION device=%s pose_updated=%s x=%s y=%s theta=%s pose_time=%s boundary=%s partition=%s vehicle_state=%s",
            self.device.id,
            location.get("_pose_updated"),
            location.get("x"),
            location.get("y"),
            location.get("theta"),
            location.get("pose_time"),
            location.get("mow_boundary"),
            location.get("partition"),
            location.get("vehicle_state"),
        )
        self._last_data_source = "mqtt_location"
        self._touch_good_data()
        self._discover_zones(location)
        self._track_zone(location)
        self._maybe_learn_dock(location)
        self.async_set_updated_data(self._build_data())

    def ingest_event(self, topic: str, payload: Any) -> None:
        """Store the latest MQTT event and forward it to HA's event bus."""
        now = _utc_iso()
        event: dict[str, Any]
        if isinstance(payload, dict):
            event = dict(payload)
        else:
            event = {"payload": payload}
        event.setdefault("device_id", self.device.id)
        event["topic"] = topic
        event["received_at"] = now
        self._last_event = event
        self._last_mqtt_update = time.monotonic()
        self._last_data_source = "mqtt_event"
        self._touch_good_data()
        self.hass.bus.async_fire(f"{DOMAIN}_event", event)
        self.async_set_updated_data(self._build_data())

    def set_mqtt_connected(self, connected: bool) -> None:
        """Update diagnostic MQTT connection state without clearing mower data."""
        if self._mqtt_connected == connected:
            return
        self._mqtt_connected = connected
        if connected:
            self._mqtt_last_connected = _utc_iso()
            self._mqtt_reconnect_count += 1
        else:
            self._mqtt_last_disconnected = _utc_iso()
            self._mqtt_disconnect_count += 1
        self.async_set_updated_data(self._build_data())

    def _record_battery(self, battery: Any) -> None:
        try:
            value = float(battery)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        now = time.monotonic()
        self._battery_history.append((now, value))
        cutoff = now - 15 * 60
        self._battery_history = [item for item in self._battery_history if item[0] >= cutoff]

    def _state_status(self) -> str:
        state = self.get_device_state()
        return (getattr(state, "state", None) or "").lower() if state else ""

    def _is_docked_status(self) -> bool:
        status = self._state_status()
        loc = self.get_device_location() or {}
        vehicle_state = loc.get("vehicle_state")
        try:
            vehicle_state_int = int(vehicle_state)
        except (TypeError, ValueError):
            vehicle_state_int = None
        # State codes 2 and 3 look dock-related in observed logs, but they are
        # still exposed separately as raw sensors. Use them only as a fallback
        # for explicit/manual dock learning and charging inference; never use an
        # "idle" state alone as proof that the mower is physically docked.
        return status in DOCKED_STATES or vehicle_state_int in (2, 3)

    def get_charging_state(self) -> str | None:
        """Infer charging state from docked state and battery trend."""
        state = self.get_device_state()
        if state is None:
            return None
        status = (getattr(state, "state", None) or "").lower()
        battery = getattr(state, "battery", None)
        if not self._is_docked_status():
            return "not_docked"
        try:
            battery_value = float(battery)
        except (TypeError, ValueError):
            battery_value = None
        if status == "charging":
            return "charging"
        if battery_value is not None and battery_value >= 99.5:
            return "full"
        history = self._battery_history
        if len(history) >= 2:
            newest_t, newest = history[-1]
            older = next(((t, v) for t, v in history if newest_t - t >= 60), history[0])
            dt, old = older
            if newest_t - dt >= 60:
                diff = newest - old
                if diff > 0.3:
                    return "charging"
                if diff < -0.3:
                    return "discharging"
                return "docked_not_charging"
        return "docked_unknown"

    def is_battery_charging(self) -> bool | None:
        state = self.get_charging_state()
        if state is None:
            return None
        return state == "charging"

    def _valid_dock_candidate(
        self, x: Any, y: Any, *, allow_far_from_locked: bool = False
    ) -> tuple[float, float] | None:
        xy = valid_xy(x, y)
        if xy is None:
            self._dock_last_rejected_reason = "invalid_xy"
            return None
        xf, yf = xy
        if abs(xf) <= DOCK_ZERO_EPSILON and abs(yf) <= DOCK_ZERO_EPSILON:
            self._dock_last_rejected_reason = "zero_zero"
            self._dock_last_rejected_candidate = {"x": xf, "y": yf, "at": _utc_iso()}
            return None
        reference = self._dock_locked
        if (
            reference
            and not allow_far_from_locked
            and int(reference.get("n", 0) or 0) >= DOCK_LEARN_MIN_SAMPLES
        ):
            dist = distance_m(xf, yf, float(reference["x"]), float(reference["y"]))
            if dist > DOCK_MAX_CANDIDATE_DISTANCE_M:
                self._dock_last_rejected_reason = "too_far_from_locked_dock"
                self._dock_last_rejected_candidate = {
                    "x": xf,
                    "y": yf,
                    "distance_m": round(dist, 3),
                    "at": _utc_iso(),
                }
                return None
        self._dock_last_rejected_reason = None
        return xf, yf

    def _maybe_learn_dock(self, location: dict) -> None:
        """Collect recent dock samples, but never auto-overwrite the dock.

        The charging station is a static user-controlled reference point. Logs
        showed that automatic learning can occasionally store stale or shifted
        coordinates. From this version onward, dock position is changed only by
        the explicit learn_dock_position service.
        """
        if not self._is_docked_status():
            return
        xy = self._valid_dock_candidate(location.get("x"), location.get("y"))
        if xy is None:
            return
        x, y = xy
        now = time.monotonic()
        self._dock_samples.append((now, x, y))
        self._dock_samples = self._dock_samples[-DOCK_SAMPLE_WINDOW:]
        self._dock_last_candidate = {"x": x, "y": y, "at": _utc_iso()}

    async def async_learn_dock_position(self, sample_seconds: int = 0) -> dict[str, Any]:
        """Learn and lock dock position from recent valid docked samples."""
        sample_seconds = max(0, min(int(sample_seconds or 0), 60))
        if sample_seconds > 0:
            await asyncio.sleep(sample_seconds)
        if not self._is_docked_status():
            raise HomeAssistantError("Mower must be docked before learning dock position")

        loc = self.get_device_location() or {}
        # Explicit learn is allowed to replace a previously locked dock even if
        # the new station position is more than the normal outlier threshold away.
        xy = self._valid_dock_candidate(
            loc.get("x"), loc.get("y"), allow_far_from_locked=True
        )
        now_mono = time.monotonic()
        if xy is not None:
            self._dock_samples.append((now_mono, xy[0], xy[1]))
            self._dock_samples = self._dock_samples[-DOCK_SAMPLE_WINDOW:]

        # Avoid using very old samples if the dock was physically moved.
        cutoff = now_mono - max(120, sample_seconds + 30)
        samples = [(x, y) for t, x, y in self._dock_samples if t >= cutoff]
        if len(samples) < DOCK_LEARN_MIN_SAMPLES and xy is None:
            raise HomeAssistantError("No valid dock position samples available")
        if len(samples) >= DOCK_LEARN_MIN_SAMPLES:
            x = median([p[0] for p in samples])
            y = median([p[1] for p in samples])
            n = len(samples)
        elif xy is not None:
            x, y = xy
            n = 1
        else:
            raise HomeAssistantError("No valid dock position samples available")

        self._dock_locked = {
            "x": float(x),
            "y": float(y),
            "n": n,
            "locked_at": _utc_iso(),
            "source": "manual_learn",
        }
        self._dock = dict(self._dock_locked)
        await self._async_save_dock()
        self.async_set_updated_data(self._build_data())
        return self._dock_locked

    async def async_clear_dock_position_lock(self) -> None:
        """Clear manually locked dock position. Automatic relearning stays disabled."""
        self._dock_locked = None
        self._dock = None
        await self._async_save_dock()
        self.async_set_updated_data(self._build_data())

    def _schedule_dock_save(self) -> None:
        if self._dock_save_unsub is not None:
            return

        def _save(_now: Any) -> None:
            self._dock_save_unsub = None
            self._schedule_coro_threadsafe(self._async_save_dock)

        self._dock_save_unsub = async_call_later(self.hass, 10, _save)

    async def _async_save_dock(self) -> None:
        await self._dock_store.async_save({"locked": self._dock_locked, "auto": None})

    def get_dock_position(self) -> dict | None:
        return self._dock_locked

    def get_dock_debug(self) -> dict[str, Any]:
        reference = self.get_dock_position()
        candidate = self._dock_last_candidate
        deviation = None
        if reference and candidate:
            deviation = distance_m(
                float(reference["x"]),
                float(reference["y"]),
                float(candidate["x"]),
                float(candidate["y"]),
            )
        return {
            "locked": self._dock_locked is not None,
            "source": "locked" if self._dock_locked else "none",
            "auto_learning_enabled": False,
            "samples": int((reference or {}).get("n", 0) or 0),
            "last_candidate": candidate,
            "last_rejected_reason": self._dock_last_rejected_reason,
            "last_rejected_candidate": self._dock_last_rejected_candidate,
            "candidate_deviation_m": round(deviation, 3) if deviation is not None else None,
        }

    def _zone_id_from_location(self, location: dict) -> str | None:
        zone = location.get("mow_boundary")
        if zone is None:
            zone = location.get("partition")
        if zone is None:
            return None
        return str(zone)

    def _discover_zones(self, location: dict) -> None:
        ids: set[str] = set()
        zone = self._zone_id_from_location(location)
        if zone:
            ids.add(zone)
        pids = location.get("partition_ids")
        if isinstance(pids, list):
            ids.update(str(pid) for pid in pids if pid is not None)
        zones = self._zone_data.setdefault("zones", {})
        for zone_id in sorted(ids):
            if zone_id not in zones:
                zones[zone_id] = {"zone_id": zone_id, "created_at": _utc_iso()}
                for callback in list(self._zone_discovery_callbacks):
                    callback(zone_id)
                self._schedule_zone_save()

    def _track_zone(self, location: dict) -> None:
        zone_id = self._zone_id_from_location(location)
        if not zone_id:
            return
        zones = self._zone_data.setdefault("zones", {})
        stats = zones.setdefault(zone_id, {"zone_id": zone_id, "created_at": _utc_iso()})
        status = self._state_status()
        vehicle_state = location.get("vehicle_state")
        try:
            vehicle_state_int = int(vehicle_state)
        except (TypeError, ValueError):
            vehicle_state_int = None
        mowing = status == "mowing" or vehicle_state_int == 4
        progress = location.get("mow_progress_percent")
        if progress is None:
            progress = normalize_progress(location.get("mow_progress"))
        now = _utc_iso()
        stats["last_seen"] = now
        if progress is not None:
            stats["last_progress"] = progress
            stats["last_good_progress"] = progress
            stats["max_progress"] = max(float(stats.get("max_progress") or 0), float(progress))
        if location.get("subtotal_area") is not None:
            stats["last_area"] = location.get("subtotal_area")
            stats["last_good_area"] = location.get("subtotal_area")
        if mowing:
            if not stats.get("active"):
                stats["session_count"] = int(stats.get("session_count") or 0) + 1
                stats["last_started"] = now
                stats["current_session_id"] = uuid.uuid4().hex
            stats["active"] = True
            stats["last_mowed"] = now
            if progress is not None and float(progress) >= 99.0:
                stats["last_completed"] = now
                stats["last_completed_progress"] = progress
        else:
            stats["active"] = False
        self._schedule_zone_save()

    def _schedule_zone_save(self) -> None:
        if self._zone_save_unsub is not None:
            return

        def _save(_now: Any) -> None:
            self._zone_save_unsub = None
            self._schedule_coro_threadsafe(self._async_save_zone_history)

        self._zone_save_unsub = async_call_later(
            self.hass, ZONE_HISTORY_SAVE_DELAY_SECONDS, _save
        )

    async def _async_save_zone_history(self) -> None:
        await self._zone_store.async_save(self._zone_data)

    def known_zone_ids(self) -> list[str]:
        zones = self._zone_data.get("zones") or {}
        return sorted(str(zone_id) for zone_id in zones.keys())

    def get_zone_stats(self, zone_id: str) -> dict[str, Any] | None:
        zones = self._zone_data.get("zones") or {}
        stats = zones.get(str(zone_id))
        return dict(stats) if isinstance(stats, dict) else None

    def get_zone_history_summary(self) -> dict[str, Any]:
        zones = self._zone_data.get("zones") or {}
        return {"zone_count": len(zones), "zones": zones}

    def register_zone_discovery_callback(self, callback: Callable[[str], None]) -> None:
        self._zone_discovery_callbacks.append(callback)

    def get_device_pose_location(self) -> dict | None:
        """Return the latest pure MQTT posture packet for position sensors.

        Position X/Y/heading must follow MQTT type 1 posture packets only.
        Do not read restored/HTTP/SDK fallback coordinates here, and do not
        actively re-emit coordinates from coordinator.data on non-pose updates.
        """
        return self._last_pose_location

    def get_device_location(self) -> dict | None:
        return self.data.get("location") or self._last_location

    def get_device_state(self) -> DeviceStateMessage | None:
        return self.data.get("state") or self._last_state

    def get_device_attributes(self) -> DeviceAttributesMessage | None:
        return self.data.get("attributes") or self._last_attributes

    def get_last_event(self) -> dict[str, Any] | None:
        return self.data.get("event") or self._last_event

    def get_device_info(self) -> Any | None:
        return self.data.get("device") or self.device

    def has_recent_good_data(self) -> bool:
        if self._last_good_update is None:
            return False
        return time.monotonic() - self._last_good_update <= LAST_KNOWN_GOOD_TTL_SECONDS

    def is_mqtt_connected(self) -> bool:
        return self._mqtt_connected

    def get_mqtt_connection_info(self) -> dict[str, Any]:
        return {
            "connected": self._mqtt_connected,
            "last_connected": self._mqtt_last_connected,
            "last_disconnected": self._mqtt_last_disconnected,
            "disconnect_count": self._mqtt_disconnect_count,
            "reconnect_count": self._mqtt_reconnect_count,
            "last_mqtt_update_monotonic": self._last_mqtt_update,
            "last_mqtt_state_update_monotonic": self._last_mqtt_state_update,
            "last_data_source": self._last_data_source,
        }
