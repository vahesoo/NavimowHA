# NavimowHA Enhanced Fork

This repository is a personal-use fork of the Navimow Home Assistant integration, originally based on the `pgoutsos/NavimowHA` fork.

The goal of this fork is to add the features I personally needed for my own Navimow setup, especially better live map support, additional mower sensors, gate/channel automation support and a more useful Lovelace map card.

> **Important note**
>
> I am not a software developer and I am not very experienced with programming.  
> This fork was created mainly for my own Home Assistant installation and shared in case it is useful to others.
>
> I do not currently plan to actively maintain this as a professional or long-term software project. Contributions, fixes and pull requests are welcome.

---

## Current status

This fork has been tested on my own setup, but it has **not** been thoroughly tested across multiple Navimow models, regions or account types.

Some features are experimental and may need adjustment for other installations.

At the moment, after testing the currently available cloud API, MQTT topics and app/APK resources, it looks like **most available telemetry has already been exposed**. More detailed data such as map geometry, off-limit islands, VisionFence data, RTK diagnostics, collision/lift events or internal mower diagnostics does not currently appear to be available through the API/MQTT data streams used by this integration.

Further progress would probably require deeper reverse engineering of the mobile app traffic or native Flutter code.

---

## Installation 🛠️

This integration is not in the default HACS store. Add this fork as a custom repository:

1. HACS → top-right menu → **Custom repositories**
2. Repository: `https://github.com/vahesoo/NavimowHA`
3. Category: **Integration**
4. Search for `Navimow` in HACS and download it
5. Restart Home Assistant
6. Settings → Devices & Services → Add Integration → search `Navimow`

### Switching from another Navimow integration

If you are switching from the official integration or another fork:

1. In HACS, remove the existing Navimow download first.
2. This removes the files but normally keeps your configured device and login.
3. Add this fork as a custom repository and download it.
4. Restart Home Assistant.

Do **not** delete the Navimow integration from **Settings → Devices & Services** unless you want to re-authenticate.

---

## Main additions in this fork

### Additional mower sensors

This fork adds several sensors and attributes that are not available in the basic integration.

Depending on what the mower publishes, you may see sensors such as:

- Position X
- Position Y
- Heading
- Dock X
- Dock Y
- Zone
- Mowing zone
- Vehicle state
- Mow progress
- Mowing percentage
- Current job area
- Weekly mowing area
- Active task
- Error code
- Error message

The exact availability depends on what the mower and Segway cloud actually send.

### Zone and mowing zone handling

The integration separates two different concepts:

- **Zone**  
  The current physical/active mowing zone when available.

- **Mowing zone / planned zone**  
  The planned or target zone information from the mower task.

This is useful for automations, especially when the mower has to move between separate areas or through a gate.

### Vehicle state mapping

Some known vehicle states are mapped to readable values, including:

| Value | Meaning |
|---:|---|
| 1 | idle |
| 2 | docked |
| 3 | docked |
| 4 | mowing |
| 5 | docking / returning |
| 6 | mapping / manual control |

These values are based on observed MQTT data and may not be complete.

### Battery / state refresh

The integration refreshes general mower state periodically through the HTTP API so battery level and mower status stay more up to date, even when MQTT location data does not include battery updates often enough.

---

## Error sensors

This fork includes:

- `sensor.<mower>_error_code`
- `sensor.<mower>_error_message`

However, in testing, many short-lived mower errors such as collisions or temporary lift events did **not** appear to be exposed through the available MQTT or HTTP status data.

These sensors are only useful if the Segway cloud/API reports an active error state long enough for Home Assistant to read it.

---

## Gate / Channel support

This fork adds configurable **Channel** areas.

A Channel is a rectangular X/Y coordinate area based on the mower's local RTK position. When the mower enters that area, the integration creates a binary sensor that turns on.

Example:

```yaml
binary_sensor.tont_front_gate_channel
```

This can be used to trigger Home Assistant automations, for example to open a gate when the mower approaches a gate passage.

### Configure a channel

Open:

```text
Settings → Devices & Services → Navimow → Configure
```

Then select the mower and enter:

- Channel name
- X min
- X max
- Y min
- Y max

A binary sensor will be created for that channel.

### Important limitation

The channel logic works best when the channel box can be placed **outside the mowing area**, for example on a driveway, path, gate passage or corridor where the mower only enters when it is actually passing through.

If the channel box overlaps with a normal mowing area, the mower may trigger the channel sensor while simply mowing close to the gate. This can cause false gate openings.

For reliable gate automation, the channel should be placed in an area where the mower has no reason to be unless it is crossing the gate/channel.

---

## Example gate automation

An example gate automation is included under:

```text
examples/gate-automation/
```

The basic logic is:

1. Mower enters the configured channel.
2. Home Assistant pauses the mower.
3. Gate opens.
4. Automation waits until the gate is open.
5. Automation waits a short additional delay.
6. Mower resumes:
   - `start_mowing` if it was mowing
   - `dock` if it was returning to the dock

This avoids the mower stopping directly in front of the gate and waiting for VisionFence/LiDAR to clear the obstacle.

You will need to change the entity IDs in the example automation to match your own mower and gate entities.

---

## Lovelace map card

This fork also includes an enhanced Lovelace map card.

Example files are located under:

```text
examples/
```

Typical files include:

- `navimow-map-card.js`
- `Navimow_top_low.svg`
- example dashboard/card YAML
- gate automation YAML

The map card can be copied to Home Assistant, for example:

```text
/config/www/navimow/navimow-map-card.js
/config/www/navimow/Navimow_top_low.svg
```

Then add the JavaScript file as a Lovelace resource:

```text
/local/navimow/navimow-map-card.js
```

---

## Map card features

The custom map card includes:

- Live mower X/Y position
- Heading-based mower icon rotation
- Current session trail
- Previous session trails
- Recorder-backed trail history after dashboard reload
- Configurable number of displayed sessions
- Optional satellite/site-plan image overlay
- Interactive two-point calibration mode
- Pinch-to-zoom on mobile
- Mouse wheel zoom and pan on desktop
- Channel box visualization
- Configurable trail colors, widths, opacity and fade mode
- Customizable dock icon
- Configurable dock and robot marker scale
- Optional Mow / Pause / Dock buttons

---

## Map calibration

The map card supports both manual calibration and interactive calibration.

### Manual calibration

You can manually enter two known reference points:

```yaml
calibration:
  - m: [0.140, -2.250]
    px: [428, 536]
  - m: [-34.713, 0.568]
    px: [162, 505]
```

Where:

- `m` = mower RTK coordinates in meters `[x, y]`
- `px` = same point on the image in pixels `[x, y]`

### Interactive calibration mode

You can enable calibration mode:

```yaml
calibration_mode: true
```

Then:

1. Drive the mower to a known point.
2. Click the same point on the map image.
3. Drive the mower to a second known point.
4. Click the second point on the image.
5. Copy the displayed calibration values into your YAML.
6. Set `calibration_mode: false`.

Manual calibration remains fully supported.

---

## Example map card YAML

```yaml
type: custom:navimow-map-card
title: Tont Map

x_entity: sensor.tont_position_x
y_entity: sensor.tont_position_y
heading_entity: sensor.tont_heading
zone_entity: sensor.tont_zone
status_entity: lawn_mower.tont
battery_entity: sensor.tont_battery

history_hours: 48
session_count: 6
trail_length: 2000

overlay_image: /local/navimow/my_map.png
overlay_opacity: 0.9

calibration:
  - m: [0.140, -2.250]
    px: [428, 536]
  - m: [-34.713, 0.568]
    px: [162, 505]

channel_entities:
  - binary_sensor.tont_front_gate_channel

appearance:
  trails:
    active:
      color: "#00ff00"
      opacity: 0.8
      width: 5.2
    previous:
      color: "#808080"
      width: 5.2
      opacity:
        first: 0.46
        last: 0.12
    fade_mode: linear

  channel:
    fill: rgba(255, 0, 0, 0.35)
    stroke: rgba(255, 0, 0, 0.80)
    width: 2.5

  robot:
    scale: 1.0

  dock:
    scale: 1.0
    icon: mdi:lightning-bolt-circle
```

---

## Map card appearance options

The map card supports configurable appearance options directly from YAML.

### Trails

```yaml
appearance:
  trails:
    active:
      color: "#00ff00"
      opacity: 0.8
      width: 5.2
    previous:
      color: "#808080"
      width: 5.2
      opacity:
        first: 0.46
        last: 0.12
    fade_mode: linear
```

`fade_mode` can be:

- `linear`
- `exponential`

### Channel box

```yaml
appearance:
  channel:
    fill: rgba(255, 0, 0, 0.35)
    stroke: rgba(255, 0, 0, 0.80)
    width: 2.5
```

### Dock icon

```yaml
appearance:
  dock:
    scale: 1.0
    icon: mdi:lightning-bolt-circle
```

Any MDI icon can be used.

### Robot marker

```yaml
appearance:
  robot:
    scale: 1.0
```

The robot icon itself is intentionally not configurable from YAML because it rotates according to mower heading, and not every icon works well as a directional marker.

---

## About telemetry limitations

A lot of testing was done with:

- official cloud status API
- MQTT realtime location data
- wildcard MQTT topic subscriptions
- APK/resource inspection

At the moment, the available data appears to be limited mostly to:

- mower state
- battery
- position
- heading
- zone/task data
- mowing progress
- mowing area statistics
- task delay / active task state
- limited error information if reported by the API

The following data does **not currently appear to be available** through the used API/MQTT channels:

- full map geometry
- off-limit island geometry
- VisionFence diagnostics
- RTK satellite count / RTK quality
- collision event history
- lift event history
- detailed internal diagnostics
- edge mowing setting per zone
- robot map channels from the official app

This may change if someone reverse engineers more of the mobile app traffic.

---

## Development notes

This fork is experimental.

Some parts are based on observation and reverse engineering of MQTT/API behaviour, not official Segway documentation.

If you find a better way to access more data, map geometry or additional commands, contributions are very welcome.

---

## Credits

This fork builds on previous Navimow Home Assistant work by other developers and community members.

Thanks to the original integration and forks that made this possible.
