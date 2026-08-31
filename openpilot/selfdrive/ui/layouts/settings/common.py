from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.common.params import Params
import os
import math
import pyray as rl


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


# Stored trip values are always meters (vEgo m/s * dt). Pair the label
# with the divisor so "mi" can never be a kilometer reading.
M_PER_MILE = 1609.344
M_PER_KM = 1000.0


def metric_units() -> bool:
  try:
    return bool(ui_state.params.get_bool("IsMetric"))
  except Exception:
    return bool(getattr(ui_state, "is_metric", False))


def distance_unit_m() -> float:
  return M_PER_KM if metric_units() else M_PER_MILE


def distance_unit_label() -> str:
  return "km" if metric_units() else "mi"


def meters_to_display(meters: float) -> float:
  return max(0.0, float(meters or 0.0)) / distance_unit_m()


def fmt_distance_m(meters: float, tenths: bool | None = None, spaced: bool = False) -> str:
  """Format stored meters. Unit always matches the conversion."""
  v = meters_to_display(meters)
  unit = distance_unit_label()
  if tenths is True or (tenths is None and v < 10.0):
    txt = f"{v:.1f}"
  elif v >= 1000:
    txt = f"{v:,.0f}"
  else:
    txt = f"{v:.0f}"
  return f"{txt} {unit}" if spaced else f"{txt}{unit}"


def tick_trip() -> None:
  from openpilot.selfdrive.ui.layouts.settings.trip_seed import tick_trip as _tick
  _tick()


def trip_snapshot() -> dict:
  try:
    from openpilot.selfdrive.ui.layouts.settings.trip_seed import trip_snapshot as _snap
    return _snap()
  except Exception:
    import json
    try:
      return json.loads(open("/data/trip_meter.json", encoding="utf-8").read())
    except Exception:
      return {}


def spawn_trip_job(kind: str) -> None:
  return


LANE_COLOR_GREEN = 0
LANE_COLOR_TESLA = 1
LANE_COLOR_LABELS = ("openpilot", "tesla")
THEME_TESLA_RGB = (62, 140, 235)
THEME_OPENPILOT_RGB = (0, 255, 64)
THEME_LANE_ALPHA = 0.7
ONROAD_UI_STOCK = 0
ONROAD_UI_CUSTOM = 1
ONROAD_UI_LABELS = ("stock UI", "custom UI")
_CUSTOM_ONROAD_PATH = "/data/params/d/CustomOnroadUi"
COMPASS_SMALL = 0
COMPASS_LARGE = 1
COMPASS_SIZE_LABELS = ("small", "large")


def _theme_params(params: Params | None = None) -> Params:
  if params is not None:
    return params
  try:
    return ui_state.params
  except Exception:
    return Params()


def lane_color_mode(params: Params | None = None) -> int:
  params = _theme_params(params)
  try:
    mode = params.get("LaneColor", return_default=True)
  except Exception:
    mode = LANE_COLOR_TESLA
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


def onroad_ui_mode(params: Params | None = None) -> int:
  params = params or Params()
  try:
    mode = params.get("CustomOnroadUi", return_default=True)
    return ONROAD_UI_CUSTOM if mode == ONROAD_UI_CUSTOM else ONROAD_UI_STOCK
  except Exception:
    try:
      raw = open(_CUSTOM_ONROAD_PATH, encoding="utf-8").read().strip()
      return ONROAD_UI_CUSTOM if raw in ("1", "true") else ONROAD_UI_STOCK
    except Exception:
      return ONROAD_UI_STOCK


def onroad_ui_label(params: Params | None = None) -> str:
  return ONROAD_UI_LABELS[onroad_ui_mode(params)]


def next_onroad_ui(params: Params | None = None) -> int:
  return ONROAD_UI_STOCK if onroad_ui_mode(params) == ONROAD_UI_CUSTOM else ONROAD_UI_CUSTOM


def custom_onroad_ui(params: Params | None = None) -> bool:
  return onroad_ui_mode(params) == ONROAD_UI_CUSTOM


def set_onroad_ui(mode: int, params: Params | None = None) -> None:
  mode = ONROAD_UI_CUSTOM if int(mode) == ONROAD_UI_CUSTOM else ONROAD_UI_STOCK
  params = params or Params()
  try:
    params.put("CustomOnroadUi", mode, block=True)
  except Exception:
    os.makedirs(os.path.dirname(_CUSTOM_ONROAD_PATH), exist_ok=True)
    with open(_CUSTOM_ONROAD_PATH, "w", encoding="utf-8") as f:
      f.write(str(mode))


def compass_size(params: Params | None = None) -> int:
  params = params or Params()
  try:
    mode = params.get("CompassSize", return_default=True)
  except Exception:
    mode = COMPASS_SMALL
  return COMPASS_LARGE if mode == COMPASS_LARGE else COMPASS_SMALL


def compass_size_label(params: Params | None = None) -> str:
  return COMPASS_SIZE_LABELS[compass_size(params)]


def next_compass_size(params: Params | None = None) -> int:
  return COMPASS_SMALL if compass_size(params) == COMPASS_LARGE else COMPASS_LARGE


CARDINALS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


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
