import json
import math
import os
import threading
import time

import pyray as rl
from openpilot.cereal import messaging, log
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.settings.trip_seed import day_id, sunday_id, seed_week_today


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


LANE_COLOR_GREEN = 0
LANE_COLOR_TESLA = 1
LANE_COLOR_LABELS = ("comma green", "tesla blue")

ONROAD_UI_STOCK = 0
ONROAD_UI_CUSTOM = 1
ONROAD_UI_LABELS = ("stock UI", "custom UI")
_CUSTOM_ONROAD_PATH = "/data/params/d/CustomOnroadUi"

COMPASS_SMALL = 0
COMPASS_LARGE = 1
COMPASS_SIZE_LABELS = ("small", "large")


def lane_color_mode(params: Params | None = None) -> int:
  params = params or Params()
  mode = params.get("LaneColor", return_default=True)
  return LANE_COLOR_TESLA if mode == LANE_COLOR_TESLA else LANE_COLOR_GREEN


def lane_color_label(params: Params | None = None) -> str:
  return LANE_COLOR_LABELS[lane_color_mode(params)]


def next_lane_color(params: Params | None = None) -> int:
  return LANE_COLOR_GREEN if lane_color_mode(params) == LANE_COLOR_TESLA else LANE_COLOR_TESLA


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
TRIP_PATH = "/data/trip_meter.json"


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


_trip: dict | None = None
_trip_t = 0.0
_trip_flush = 0.0
_seed_started = False
_seed_done = False


def _run_seed() -> None:
  global _trip, _seed_done
  s = None
  try:
    s = seed_week_today()
  except Exception:
    cloudlog.exception("trip seed")
  if _trip is None:
    _seed_done = True
    return
  did, wid = day_id(), sunday_id()
  if s:
    _trip["week_m"] = float(s["week_m"])
    _trip["week_eng_m"] = float(s["week_eng_m"])
    _trip["today_m"] = float(s["today_m"])
    _trip["today_eng_m"] = float(s["today_eng_m"])
    _trip["week_id"] = s["week_id"]
    _trip["day_id"] = s["day_id"]
    _trip["seed"] = "qlog"
  else:
    if _trip.get("week_id") != wid:
      _trip["week_m"] = _trip["week_eng_m"] = _trip["week_eng_s"] = _trip["week_tot_s"] = 0.0
      _trip["week_id"] = wid
    if _trip.get("day_id") != did:
      _trip["today_m"] = _trip["today_eng_m"] = 0.0
      _trip["day_id"] = did
  try:
    _save_trip(_trip)
  except Exception:
    pass
  _seed_done = True


def _load_trip() -> dict:
  t = {"trip_m": 0.0, "eng_m": 0.0, "eng_s": 0.0, "tot_s": 0.0,
       "last_m": 0.0, "last_eng_m": 0.0, "last_eng_s": 0.0, "last_tot_s": 0.0, "route": "",
       "week_m": 0.0, "week_eng_m": 0.0, "week_eng_s": 0.0, "week_tot_s": 0.0, "week_id": "",
       "today_m": 0.0, "today_eng_m": 0.0, "day_id": ""}
  try:
    t.update(json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  return t


def _save_trip(t: dict) -> None:
  tmp = TRIP_PATH + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(t, f)
  os.replace(tmp, TRIP_PATH)


def tick_trip() -> None:
  """Today = Chicago calendar day. Week = Sunday 00:00 Chicago. Live add after qlog seed."""
  global _trip, _trip_t, _trip_flush, _seed_started
  now = time.monotonic()
  if _trip is None:
    _trip = _load_trip()
    _trip_t = now
    if not _seed_started:
      _seed_started = True
      threading.Thread(target=_run_seed, daemon=True).start()
    return
  if not _seed_done:
    _trip_t = now
    return

  wid, did = sunday_id(), day_id()
  if _trip.get("week_id") != wid:
    _trip["week_m"] = _trip["week_eng_m"] = _trip["week_eng_s"] = _trip["week_tot_s"] = 0.0
    _trip["week_id"] = wid
  if _trip.get("day_id") != did:
    _trip["today_m"] = _trip["today_eng_m"] = 0.0
    _trip["day_id"] = did

  dt = min(1.0, max(0.0, now - _trip_t))
  _trip_t = now
  params = ui_state.params
  route = params.get("CurrentRoute") or ""
  if isinstance(route, bytes):
    route = route.decode(errors="replace")
  if route and route != _trip.get("route"):
    _trip["trip_m"] = _trip["eng_m"] = _trip["eng_s"] = _trip["tot_s"] = 0.0
    _trip["route"] = route
    _save_trip(_trip)
  try:
    offroad = params.get_bool("IsOffroad")
    cs_ok = ui_state.sm.recv_frame["carState"] > 0
  except Exception:
    offroad, cs_ok = True, False
  if (not offroad) and cs_ok:
    v = max(0.0, float(ui_state.sm["carState"].vEgo))
    _trip["tot_s"] += dt
    if v > 0.15:
      _trip["trip_m"] += v * dt
      _trip["week_m"] += v * dt
      _trip["today_m"] = _trip.get("today_m", 0.0) + v * dt
    try:
      if ui_state.sm.recv_frame["selfdriveState"] > 0 and ui_state.sm["selfdriveState"].enabled:
        _trip["eng_m"] = _trip.get("eng_m", 0.0) + v * dt
        _trip["week_eng_m"] = _trip.get("week_eng_m", 0.0) + v * dt
        _trip["today_eng_m"] = _trip.get("today_eng_m", 0.0) + v * dt
        _trip["eng_s"] += dt
        _trip["week_eng_s"] += dt
    except Exception:
      pass
  if now - _trip_flush > 1.0:
    _save_trip(_trip)
    _trip_flush = now


def trip_pct() -> int:
  t = _trip
  if t is None:
    return 0
  m = float(t.get("trip_m") or 0)
  e = float(t.get("eng_m") or 0)
  return int(round(100.0 * e / m)) if m > 1 else 0


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
