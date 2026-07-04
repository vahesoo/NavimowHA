"""Configurable Navimow channel helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NavimowChannelBox:
    """One rectangular channel box in mower-local X/Y coordinates."""

    device_id: str
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float | None, y: float | None) -> bool:
        """Return true when the supplied X/Y point is inside this channel box."""
        if x is None or y is None:
            return False
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    @property
    def slug(self) -> str:
        """Return a simple slug for entity unique IDs."""
        return self.name.lower().replace(" ", "_").replace("-", "_")


def _normalize_box(device_id: str, name: str, raw: dict[str, Any]) -> NavimowChannelBox:
    """Normalize a stored channel dict."""
    x1 = float(raw["x_min"])
    x2 = float(raw["x_max"])
    y1 = float(raw["y_min"])
    y2 = float(raw["y_max"])
    return NavimowChannelBox(
        device_id=str(device_id),
        name=str(name or "gate"),
        x_min=min(x1, x2),
        x_max=max(x1, x2),
        y_min=min(y1, y2),
        y_max=max(y1, y2),
    )


def channels_from_options(options: dict[str, Any]) -> dict[str, list[NavimowChannelBox]]:
    """Return configured channel boxes grouped by mower device_id.

    Stored format in config entry options:
      {
        "channels": {
          "<device_id>": {
            "gate": {"x_min": ..., "x_max": ..., "y_min": ..., "y_max": ...}
          }
        }
      }
    """
    raw_channels = options.get("channels") or {}
    result: dict[str, list[NavimowChannelBox]] = {}

    if not isinstance(raw_channels, dict):
        return result

    for device_id, device_channels in raw_channels.items():
        if not isinstance(device_channels, dict):
            continue
        boxes: list[NavimowChannelBox] = []
        for name, raw in device_channels.items():
            if not isinstance(raw, dict):
                continue
            try:
                boxes.append(_normalize_box(str(device_id), str(name), raw))
            except (KeyError, TypeError, ValueError):
                continue
        if boxes:
            result[str(device_id)] = boxes

    return result
