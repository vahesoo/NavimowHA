# NavimowHA Enhanced Fork

An experimental Home Assistant custom integration for Segway Navimow robotic mowers.

This repository is an enhanced personal-use fork of the Navimow Home Assistant work by Segway Navimow and community forks. The additional functionality in this fork was developed and tested for the Home Assistant installations of **Toomas Vähesoo** and is shared in case it is useful to other users.

> This is not an official Segway product and it has not been tested with every mower model, region or account type. The cloud API and MQTT payloads may change without notice. Contributions and pull requests are welcome.

## Main features

- Standard mower entity with start, pause and dock controls.
- Battery and general state refresh through the cloud REST API.
- High-frequency local X/Y position and heading from the MQTT `location` stream.
- Current physical mowing zone and planned/target zone information.
- Mowing progress, mowing percentage and area statistics when published by the mower.
- Vehicle-state, charging-state and limited error/event diagnostic sensors.
- Learned dock X/Y position.
- Per-zone history sensors created dynamically when zones are observed.
- Restore support for useful non-position values after a Home Assistant restart.
- Configurable channel binary sensors for gate or corridor automations.
- MQTT credential refresh after broker disconnects.
- Pose-stream watchdog that restarts MQTT when an active mower stops publishing type-1 pose packets.
- Optional detailed debug logging that users can enable themselves.

## Installation with HACS

This fork is not in the default HACS store.

1. Open **HACS**.
2. Open the top-right menu and select **Custom repositories**.
3. Add:

   ```text
   https://github.com/vahesoo/NavimowHA
   ```

4. Select category **Integration**.
5. Search for **Navimow** and install it.
6. Restart Home Assistant.
7. Open **Settings → Devices & services → Add integration** and search for **Navimow**.

### Switching from another Navimow fork

1. Remove the currently downloaded Navimow repository from HACS.
2. Add this repository as a custom integration repository.
3. Install it and restart Home Assistant.

Normally the existing config entry and login are retained. Do not delete the integration from **Settings → Devices & services** unless re-authentication is intended.

## Updating the repository files manually

The integration files belong under:

```text
/config/custom_components/navimow/
```

When replacing Python files manually:

1. Copy the updated files into `custom_components/navimow`.
2. Replace all nine Python/service files included in this archive. Keep the other repository files such as `manifest.json`, `auth.py`, `config_flow.py`, `channel.py`, translations and icons.
3. Restart Home Assistant.
4. Check **Settings → System → Logs** for startup errors.

## Live MQTT location data

The normal `navimow-sdk` processes the MQTT `state`, `event` and `attributes` channels. The mower publishes its detailed local position on a separate topic:

```text
/downlink/vehicle/<device_id>/realtimeDate/location
```

The payload is a JSON list. Observed item types include:

| Type | Purpose | Typical fields |
|---:|---|---|
| 1 | Live pose | `postureX`, `postureY`, `postureTheta`, `vehicleState`, `time` |
| 2 | Mowing progress | `currentMowBoundary`, `currentMowProgress`, `mowingPercentage`, area values |
| 3 | Planned partitions | `partitionIds` |
| 4 | Task state | `taskDelay`, `vehicleState`, `time` |

The coordinates are a mower-local Cartesian coordinate system in metres. They are not GPS latitude and longitude.

### Position-source rules

Position X, Position Y and Heading are deliberately sourced only from valid MQTT **type-1** packets.

They are not:

- restored after a Home Assistant restart;
- generated from the REST API;
- generated from type-2, type-3 or type-4 packets;
- replaced with guessed coordinates.

This avoids false trail segments after restarts or MQTT interruptions. Other task and zone values can retain or restore their last known values because they do not create map trails.

## Pose-stream watchdog

A connected MQTT session may occasionally continue receiving general packets while the high-frequency pose stream stops. During active movement, the integration checks the age of the last valid type-1 pose packet.

Default behaviour:

- check interval: 60 seconds;
- stale threshold: 180 seconds;
- restart cooldown: 300 seconds;
- active states checked: mowing, docking/returning and mapping/manual movement.

When the mower is active and no fresh pose packet has arrived for more than three minutes, the integration restarts its MQTT session. Docked and idle mowers do not trigger the watchdog.

## Sensors

Exact entity IDs depend on the mower name assigned by Home Assistant. Typical entities include:

| Sensor | Description |
|---|---|
| Battery | Battery percentage from mower state/API data |
| Charging state | Best-effort charging/docked status |
| Position X / Position Y | Latest valid MQTT type-1 coordinates in metres |
| Heading | Type-1 heading converted from radians to degrees |
| Zone | Current physical mowing boundary, with planned-zone fallback |
| Mowing zone | Planned/target partition, with active-boundary fallback |
| Dock X / Dock Y | Average position learned while the mower is docked |
| Mow progress | Route progress converted from the observed 0–10000 value to percent |
| Mowing percentage | Percentage published directly by the mower |
| Current job area | Current task area when published |
| Weekly mowing area | Weekly area when published |
| Task delay raw | Raw observed `taskDelay` value |
| Vehicle state | Friendly value derived from `vehicleState` |
| Vehicle state code | Raw numeric code for diagnostics |
| Last event | Latest event exposed by the standard MQTT event channel |
| Zone history | Summary of zones observed during the running HA session |
| Error code / message | Active cloud/API error data when available |

### Observed vehicle-state values

The current mapping is based on observed MQTT data and may not be complete:

| Code | Displayed value |
|---:|---|
| 0 | unknown |
| 1 | idle |
| 2 | docked |
| 3 | docked |
| 4 | mowing |
| 5 | docking |
| 6 | mapping |

Unknown numeric codes are shown as `unknown_<code>` instead of being discarded.

## Restored values

The following values can restore their last Home Assistant state until fresh data arrives:

- charging state;
- zone and mowing zone;
- mowing progress and mowing percentage;
- current and weekly area values;
- task-delay value;
- vehicle state and raw vehicle-state code;
- learned dock coordinates;
- per-zone history sensor values.

Position X, Position Y, Heading and active error diagnostics are intentionally not restored.

## Zone handling

The integration keeps two related concepts separate:

- `currentMowBoundary` — the physical boundary currently being mowed;
- `partitionIds` — planned or requested partitions for the task.

This distinction is useful for gate automations because a planned zone may be known before the mower physically reaches it.

### Per-zone history

When a new zone ID is observed, Home Assistant creates per-zone sensors such as:

- last mowed time;
- last progress;
- last completed time;
- last area;
- session count.

These values are based on the MQTT packets available to this integration. They are diagnostic estimates, not an official replacement for the Navimow app's complete task history.

## Dock position

Dock X and Dock Y are learned by averaging valid pose samples received while the mower reports a docked or charging state. The capped running average smooths normal coordinate jitter while still allowing the estimate to move gradually if the dock is relocated.

The dock sensor attributes include the current sample count and data source. Home Assistant restores the last sensor values after a restart until new live dock samples are collected.

## Channel binary sensors

The fork supports rectangular channel areas based on local mower coordinates. A channel binary sensor is on while the mower position is within the configured X/Y limits.

Configure channels under:

```text
Settings → Devices & services → Navimow → Configure
```

Channel sensors are useful for gate, driveway and corridor automations. For reliable gate control, define the rectangle in a passage the mower enters only when crossing the gate. A rectangle overlapping a normal mowing area may cause false triggers.

## Battery and state refresh

The MQTT location stream does not always contain battery data. General status is therefore refreshed through the REST API every 120 seconds.

A recent live MQTT mower state takes priority over a conflicting HTTP poll so an older cloud response does not incorrectly change a mower from mowing to idle. Battery and signal values from the HTTP response can still be refreshed.

## MQTT authentication and reconnects

MQTT username/password information and WebSocket authorization are linked to the Navimow account session. On a normal broker disconnect, the integration:

1. refreshes the OAuth token when necessary;
2. requests current MQTT credentials from the cloud API;
3. updates the SDK credentials;
4. allows the SDK to reconnect and resubscribe.

The location topic is subscribed for every discovered mower after each MQTT connection.

## Debug logging

Detailed diagnostic calls remain in the integration but are silent at the normal Home Assistant log level.

To enable them temporarily, add or merge the following into `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.navimow: debug
    custom_components.navimow.coordinator: debug
```

Restart Home Assistant after changing YAML.

Useful debug markers include:

```text
NAVIMOW_MQTT_RAW
NAVIMOW_LOCATION_RAW
NAVIMOW_LOCATION_PARSED
NAVIMOW_INGEST_LOCATION
NAVIMOW_EVENT_RAW
```

To disable detailed logging again, remove only the two `custom_components.navimow...: debug` entries and restart Home Assistant. Keep the `_LOGGER.debug(...)` lines in the integration source; they produce no debug output unless the logger level is enabled.

> Raw logs may contain mower device IDs, coordinates and task details. Review them before publishing.

## Services

The integration registers these services:

```text
navimow.set_blade_height
navimow.learn_dock_position
navimow.clear_dock_position_lock
```

`set_blade_height` is currently only a diagnostic placeholder. The cloud REST API used by this integration does not provide a confirmed blade-height command, so the service intentionally returns an error instead of pretending the setting changed.

`learn_dock_position` stores and locks the charging-station coordinates from recent valid pose samples while the mower is docked. `clear_dock_position_lock` removes that saved reference. Automatic dock overwriting remains disabled.

## Map card

The enhanced Lovelace card is maintained as a separate repository:

```text
https://github.com/vahesoo/Navimow-map-card
```

Keeping it separate allows HACS to install and update the integration and dashboard card independently.

The map card can use the position, heading, dock, mower, battery, zone and channel entities exposed by this integration. It supports live trails, Recorder history, multi-day filtering, an optional aerial image overlay, calibration and channel visualization.

## Known limitations

Testing of the current API, MQTT topics and mobile-app resources has not revealed reliable access to all data available inside the official app. The following are not currently confirmed through the interfaces used here:

- complete map and off-limit-island geometry;
- official channel geometry;
- detailed VisionFence diagnostics;
- RTK satellite count and fix-quality details;
- reliable short collision/lift event history;
- every mower setting and per-zone setting;
- confirmed cloud commands for blade height or similar configuration changes.

The error and event sensors can only show information that the cloud/SDK actually publishes. Short-lived local mower warnings may never reach Home Assistant.

## Troubleshooting

### Position does not update

1. Enable the Navimow debug logger.
2. Start or move the mower.
3. Look for `NAVIMOW_MQTT_RAW` packets with `"type":1`.
4. Confirm that `NAVIMOW_LOCATION_PARSED` shows `pose_updated=True`.
5. Confirm that `NAVIMOW_INGEST_LOCATION` follows it.

Type-2 or type-4 packets with `pose_updated=False` are normal and do not represent a new coordinate.

### Values remain unknown after restart

Position values wait for a new valid type-1 packet by design. Other restored values may remain unknown until that entity has had at least one valid value in an earlier Home Assistant session.

### Old values remain visible

Restored non-position values are expected to remain until fresh MQTT/API data replaces them. Position values are not restored. Error sensors are also not restored.

### Card shows no earlier trails

Historical trails depend on Home Assistant Recorder retaining the mower and X/Y sensor history. See the separate map-card repository for card-specific setup.

## Development notes

The enhanced location/task decoder is based on observed payloads rather than official protocol documentation. Payload fields and meanings can vary between mower series, firmware versions and regions.

The files were designed to preserve the existing integration structure and SDK while adding the minimum additional MQTT handling required for the location stream.

## Credits

- Segway Navimow's official Home Assistant integration and `navimow-sdk`.
- Earlier community forks, including the work this fork was originally based on.
- Home Assistant and Navimow community members who shared logs and test results.
- Enhanced fork and testing: **Toomas Vähesoo**.

## License

MIT. See the repository's `LICENSE` file.
