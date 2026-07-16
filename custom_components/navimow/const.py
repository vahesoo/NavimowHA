"""Constants for Navimow integration."""
from __future__ import annotations
from typing import Final

DOMAIN: Final = "navimow"

# OAuth2 Configuration
OAUTH2_AUTHORIZE: Final = (
    "https://navimow-h5-fra.willand.com/smartHome/login?channel=homeassistant"
)
OAUTH2_TOKEN: Final = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"
OAUTH2_REFRESH: Final | None = None

CLIENT_ID: Final = "homeassistant"
CLIENT_SECRET: Final = "57056e15-722e-42be-bbaa-b0cbfb208a52"

API_BASE_URL: Final = "https://navimow-fra.ninebot.com"

MQTT_BROKER: Final = "mqtt.navimow.com"
MQTT_PORT: Final = 1883
MQTT_USERNAME: Final | None = None
MQTT_PASSWORD: Final | None = None

# General coordinator refresh interval. The realtime MQTT stream is push based,
# but a periodic update keeps OAuth tokens fresh and provides an HTTP fallback.
UPDATE_INTERVAL: Final = 30

# If no MQTT state/location/event has been received for this long, the
# coordinator may refresh through HTTP. Do not make entities unavailable just
# because MQTT reconnects for a second.
MQTT_STALE_SECONDS: Final = 90

# Minimum spacing between HTTP fallback/status refresh calls.
HTTP_FALLBACK_MIN_INTERVAL: Final = 60

# Normal live battery/state refresh. Battery is not included in every realtime
# location packet, so refresh through HTTP separately.
LIVE_STATUS_REFRESH_INTERVAL_SECONDS: Final = 120

# Keep last known good values for this long before allowing non-diagnostic
# entities to become unavailable because of missing data. The hourly MQTT
# reconnects observed in logs are normally 1-5 seconds, so this is intentionally
# conservative.
LAST_KNOWN_GOOD_TTL_SECONDS: Final = 10 * 60

# Dock learning guard rails.
DOCK_ZERO_EPSILON: Final = 0.001
DOCK_MAX_CANDIDATE_DISTANCE_M: Final = 1.0
DOCK_SAMPLE_WINDOW: Final = 30
DOCK_LEARN_MIN_SAMPLES: Final = 3

# Zone history storage/save behavior.
ZONE_HISTORY_SAVE_DELAY_SECONDS: Final = 30

MOWER_STATUS_TO_ACTIVITY = {
    "idle": "docked",
    "mowing": "mowing",
    "paused": "paused",
    "docked": "docked",
    "charging": "docked",
    "returning": "returning",
    "error": "error",
    "unknown": "error",
}
