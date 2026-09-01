import math

import pyray as rl
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


LANE_COLOR_GREEN = 0
LANE_COLOR_TESLA = 1
LANE_COLOR_LABELS = ("openpilot", "tesla")

# Tesla Autopilot viz blue / stock openpilot green.
THEME_TESLA_RGB = (62, 140, 235)
THEME_OPENPILOT_RGB = (0, 255, 64)
# Lane lines clip alpha at 0.7 so the HUD does not burn an OLED. Tesla wheel uses the same cap.
THEME_LANE_ALPHA = 0.7

COMPASS_SMALL = 0
COMPASS_LARGE = 1
COMPASS_SIZE_LABELS = ("small", "large")

CARDINALS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _theme_params(params: Params | None = None) -> Params:
  if params is not None:
    return params
  try:
    return ui_state.params
  except Exception:
    return Params()


def lane_color_mode(params: Params | None = None) -> int:
  params = _theme_params(params)
  mode = params.get("LaneColor", return_default=True)
  return LANE_COLOR_TESLA if mode == LANE_COLOR_TESLA else LANE_COLOR_GREEN


def lane_color_label(params: Params | None = None) -> str:
  return LANE_COLOR_LABELS[lane_color_mode(params)]


def next_lane_color(params: Params | None = None) -> int:
  return LANE_COLOR_GREEN if lane_color_mode(params) == LANE_COLOR_TESLA else LANE_COLOR_TESLA


def tesla_theme(params: Params | None = None) -> bool:
  return lane_color_mode(params) == LANE_COLOR_TESLA


def theme_rgb(params: Params | None = None) -> tuple[int, int, int]:
  return THEME_TESLA_RGB if tesla_theme(params) else THEME_OPENPILOT_RGB


def theme_color(alpha: float = 1.0, params: Params | None = None) -> rl.Color:
  r, g, b = theme_rgb(params)
  a = int(max(0.0, min(1.0, float(alpha))) * 255)
  return rl.Color(r, g, b, a)


def compass_size(params: Params | None = None) -> int:
  params = params or Params()
  mode = params.get("CompassSize", return_default=True)
  return COMPASS_LARGE if mode == COMPASS_LARGE else COMPASS_SMALL


def compass_size_label(params: Params | None = None) -> str:
  return COMPASS_SIZE_LABELS[compass_size(params)]


def next_compass_size(params: Params | None = None) -> int:
  return COMPASS_SMALL if compass_size(params) == COMPASS_LARGE else COMPASS_LARGE


def heading_deg() -> float | None:
  sm = ui_state.sm
  try:
    if sm.recv_frame["gpsLocationExternal"] > 0:
      gps = sm["gpsLocationExternal"]
      if not (hasattr(gps, "hasFix") and not gps.hasFix):
        return float(gps.bearingDeg) % 360.0
  except Exception:
    pass
  try:
    if sm.recv_frame["deviceMotion"] > 0:
      ori = sm["deviceMotion"].orientationNED
      if ori.valid:
        return math.degrees(float(ori.z)) % 360.0
  except Exception:
    pass
  return None


def heading_letter() -> str | None:
  deg = heading_deg()
  if deg is None:
    return None
  return CARDINALS[int((deg + 22.5) % 360.0) // 45]
