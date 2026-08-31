import math
import os
import subprocess
import sys
import time

import pyray as rl
from openpilot.cereal import messaging, log
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
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


def _read_onroad_ui_file() -> int:
  try:
    raw = open(_CUSTOM_ONROAD_PATH, "r", encoding="utf-8").read().strip()
    return ONROAD_UI_CUSTOM if raw in ("1", "true") else ONROAD_UI_STOCK
  except Exception:
    return ONROAD_UI_STOCK


def onroad_ui_mode(params: Params | None = None) -> int:
  params = params or Params()
  try:
    mode = params.get("CustomOnroadUi", return_default=True)
    return ONROAD_UI_CUSTOM if mode == ONROAD_UI_CUSTOM else ONROAD_UI_STOCK
  except Exception:
    return _read_onroad_ui_file()


def onroad_ui_label(params: Params | None = None) -> str:
  return ONROAD_UI_LABELS[onroad_ui_mode(params)]


def next_onroad_ui(params: Params | None = None) -> int:
  return ONROAD_UI_STOCK if onroad_ui_mode(params) == ONROAD_UI_CUSTOM else ONROAD_UI_CUSTOM


def custom_onroad_ui(params: Params | None = None) -> bool:
  return onroad_ui_mode(params) == ONROAD_UI_CUSTOM


def compass_size(params: Params | None = None) -> int:
  params = params or Params()
  mode = params.get("CompassSize", return_default=True)
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


def set_onroad_ui(mode: int, params: Params | None = None) -> None:
  mode = ONROAD_UI_CUSTOM if int(mode) == ONROAD_UI_CUSTOM else ONROAD_UI_STOCK
  params = params or Params()
  try:
    params.put("CustomOnroadUi", mode, block=True)
  except Exception:
    os.makedirs(os.path.dirname(_CUSTOM_ONROAD_PATH), exist_ok=True)
    with open(_CUSTOM_ONROAD_PATH, "w", encoding="utf-8") as f:
      f.write(str(mode))


_DELOREAN_MODE = "/data/delorean_sound"
_DELOREAN_PLAY = "/data/delorean_play"


def delorean_on() -> bool:
  try:
    return open(_DELOREAN_MODE, encoding="utf-8").read().strip() in ("1", "true")
  except Exception:
    return False


def set_delorean(on: bool) -> None:
  with open(_DELOREAN_MODE, "w", encoding="utf-8") as f:
    f.write("1" if on else "0")


def request_delorean_play() -> None:
  with open(_DELOREAN_PLAY, "w", encoding="utf-8") as f:
    f.write("1")


_trip_t = 0.0
_trip_flush = 0.0
_seed_started = False
_was_offroad = True


def _spawn_trip_job(kind: str) -> None:
  try:
    subprocess.Popen(
      [sys.executable, "-m", "openpilot.selfdrive.ui.layouts.settings.trip_seed", kind],
      cwd=BASEDIR,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      start_new_session=True,
    )
  except Exception:
    cloudlog.exception("trip job")


def spawn_trip_job(kind: str) -> None:
  _spawn_trip_job(kind)


def trip_snapshot() -> dict:
  """Home/stats compatibility. Same object as stats_view()."""
  from openpilot.selfdrive.ui.layouts.settings.trip_stats import stats_view
  return stats_view()


def tick_trip() -> None:
  """Live overlay = this drive only. Qlog cache owns completed miles."""
  global _trip_t, _trip_flush, _seed_started, _was_offroad
  now = time.monotonic()
  if not _seed_started:
    _seed_started = True
    _spawn_trip_job("seed")
  try:
    params = ui_state.params
    offroad = params.get_bool("IsOffroad")
    cs_ok = ui_state.sm.recv_frame["carState"] > 0
  except Exception:
    offroad, cs_ok = True, False
  park_cache = bool(offroad and not _was_offroad)
  _was_offroad = offroad

  if (not offroad) and cs_ok:
    dt = min(1.0, max(0.0, now - _trip_t)) if _trip_t else 0.0
    _trip_t = now
    v = max(0.0, float(ui_state.sm["carState"].vEgo))
    engaged = False
    try:
      engaged = ui_state.sm.recv_frame["selfdriveState"] > 0 and bool(ui_state.sm["selfdriveState"].enabled)
    except Exception:
      engaged = False
    route = params.get("CurrentRoute") or ""
    if isinstance(route, bytes):
      route = route.decode(errors="replace")
    d = v * dt if v > 0.15 else 0.0
    if d > 0:
      from openpilot.selfdrive.ui.layouts.settings.trip_stats import add_live
      add_live(d, d if engaged else 0.0, str(route), d if engaged else 0.0)
  else:
    _trip_t = now

  if now - _trip_flush > 1.0:
    _trip_flush = now
    try:
      from openpilot.selfdrive.ui.layouts.settings.trip_stats import flush_live
      flush_live()
    except Exception:
      pass
  if park_cache:
    _spawn_trip_job("cache")


def _rpy_lines(roll: float, pitch: float, yaw: float) -> tuple[str, str, str]:
  # rpyCalib is device-frame Euler: roll, pitch, yaw.
  # Pitch/yaw words match stock. +roll is clockwise looking forward (right side down).
  pitch_s = f"P {abs(pitch):.1f}° {'down' if pitch > 0 else 'up'}"
  yaw_s = f"Y {abs(yaw):.1f}° {'left' if yaw > 0 else 'right'}"
  roll_s = f"R {abs(roll):.1f}° {'cw' if roll > 0 else 'ccw'}"
  return pitch_s, yaw_s, roll_s


def calib_button_value(params: Params | None = None, compact: bool = False) -> str:
  """Live roll/pitch/yaw for Reset Calibration. compact=True is three lines for C4."""
  params = params or Params()
  calib_bytes = params.get("CalibrationParams")
  if not calib_bytes:
    return "uncalibrated"

  try:
    calib = messaging.log_from_bytes(calib_bytes, log.Event).extrinsicsCalibration
    if calib.calStatus == log.ExtrinsicsCalibration.Status.uncalibrated:
      return "uncalibrated"
    roll = math.degrees(calib.rpyCalib[0])
    pitch = math.degrees(calib.rpyCalib[1])
    yaw = math.degrees(calib.rpyCalib[2])
  except Exception:
    cloudlog.exception("invalid CalibrationParams")
    return "uncalibrated"

  pitch_s, yaw_s, roll_s = _rpy_lines(roll, pitch, yaw)
  if compact:
    return f"{pitch_s}\n{yaw_s}\n{roll_s}"
  return f"{pitch_s}  {yaw_s}  {roll_s}"
