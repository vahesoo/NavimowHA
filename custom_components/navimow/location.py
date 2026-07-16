"""Real-time location / zone decoding for Navimow (fork addition)."""
from __future__ import annotations

import math
from typing import Any


def location_topic(device_id: str) -> str:
    """Cloud MQTT topic that carries real-time pose/zone for a device."""
    return f"/downlink/vehicle/{device_id}/realtimeDate/location"


DOCKED_STATES = frozenset({"docked", "charging"})
DOCK_MAX_SAMPLES = 200

# These names are intentionally conservative. Logs suggest that 2 and 3 are
# both dock-related, but not necessarily identical. Keep raw code sensors too.
VEHICLE_STATE_NAMES = {
    0: "unknown",
    1: "idle",
    2: "docked_state_2",
    3: "docked_state_3",
    4: "mowing",
    5: "docking",
    6: "mapping",
}


def vehicle_state_name(value: Any) -> str | None:
    """Return a best-effort friendly name for Navimow vehicleState."""
    try:
        key = int(value)
    except (TypeError, ValueError):
        return None
    return VEHICLE_STATE_NAMES.get(key, f"state_{key}")


def valid_xy(x: Any, y: Any) -> tuple[float, float] | None:
    """Return finite X/Y floats or None."""
    try:
        xf = float(x)
        yf = float(y)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf) or not math.isfinite(yf):
        return None
    return xf, yf


def distance_m(x1: float, y1: float, x2: float, y2: float) -> float:
    """Return Euclidean distance in meters."""
    return math.hypot(float(x1) - float(x2), float(y1) - float(y2))


def normalize_progress(value: Any) -> float | None:
    """Normalize Navimow progress values to percent.

    currentMowProgress is commonly 0..10000, while some values may already be
    0..100. Return a 0..100 float where possible.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number > 100:
        number = number / 100.0
    return max(0.0, min(100.0, number))


def update_dock_estimate(
    dock: dict | None, x: float, y: float, max_samples: int = DOCK_MAX_SAMPLES
) -> dict:
    """Fold one docked pose sample into the running dock-position average."""
    d = dock or {"x": 0.0, "y": 0.0, "n": 0}
    n = min(int(d.get("n", 0)), max_samples - 1)
    return {
        "x": (float(d["x"]) * n + float(x)) / (n + 1),
        "y": (float(d["y"]) * n + float(y)) / (n + 1),
        "n": n + 1,
    }


def parse_location_payload(
    cache: dict[str, dict], device_id: str, data: Any
) -> dict | None:
    """Merge one location message into the per-device cache."""
    if not isinstance(data, list):
        return None
    loc = dict(cache.get(device_id) or {})
    loc["device_id"] = device_id
    # Per-payload marker. It must be reset on every MQTT message so
    # progress/zone packets do not look like fresh pose updates.
    loc["_pose_updated"] = False
    changed = False

    for item in data:
        if not isinstance(item, dict):
            continue
        t = item.get("type")

        if t == 1:
            xy = valid_xy(item.get("postureX"), item.get("postureY"))
            if xy is not None:
                loc["x"], loc["y"] = xy
                loc["_pose_updated"] = True
                try:
                    loc["theta"] = float(item["postureTheta"])
                except (TypeError, ValueError, KeyError):
                    pass
            if "vehicleState" in item:
                loc["vehicle_state"] = item["vehicleState"]
            if "time" in item:
                loc["pose_time"] = item["time"]
            changed = True

        elif t == 2:
            if "currentMowBoundary" in item:
                loc["mow_boundary"] = item.get("currentMowBoundary")
                loc["mow_boundary_time"] = item.get("time")
            if "currentMowProgress" in item:
                loc["mow_progress"] = item.get("currentMowProgress")
                loc["mow_progress_percent"] = normalize_progress(
                    item.get("currentMowProgress")
                )
            if "mowingPercentage" in item:
                loc["mowing_percentage"] = normalize_progress(
                    item.get("mowingPercentage")
                )
            if "subtotalArea" in item:
                try:
                    loc["subtotal_area"] = float(item.get("subtotalArea"))
                except (TypeError, ValueError):
                    loc["subtotal_area"] = item.get("subtotalArea")
            if "mowingWeekArea" in item:
                try:
                    loc["mowing_week_area"] = float(item.get("mowingWeekArea"))
                except (TypeError, ValueError):
                    loc["mowing_week_area"] = item.get("mowingWeekArea")
            if "mowStartType" in item:
                loc["mow_start_type"] = item.get("mowStartType")
            if "action" in item:
                loc["action"] = item.get("action")
            if "subAction" in item:
                loc["sub_action"] = item.get("subAction")
            if "mapWorkPosition" in item:
                loc["map_work_position"] = item.get("mapWorkPosition")
            if "time" in item:
                loc["progress_time"] = item.get("time")
            changed = True

        elif t == 3:
            if "partitionIds" in item:
                pids = item.get("partitionIds")
                loc["partition_ids"] = pids
                loc["partition"] = pids[0] if isinstance(pids, list) and pids else None
                loc["partition_time"] = item.get("time")
                changed = True
            elif "time" in item:
                loc["partition_time"] = item.get("time")
                changed = True

        elif t == 4:
            if "taskDelay" in item:
                loc["active_task"] = item.get("taskDelay")
                loc["task_delay"] = item.get("taskDelay")
            if "vehicleState" in item:
                loc["vehicle_state"] = item.get("vehicleState")
            if "time" in item:
                loc["active_task_time"] = item.get("time")
                loc["delay_time"] = item.get("time")
            changed = True

    if not changed:
        return None
    cache[device_id] = loc
    return loc
