import json
import math
import os
import subprocess
import sys
import threading
import time

import pyray as rl
from openpilot.cereal import messaging, log
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.settings.trip_seed import (
  empty_trip, merge_snapshots, apply_seed, roll_ids, week_cache_valid,
  sunday_id, day_id,
)


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


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
_trip_param = 0.0
_seed_started = False
_awaiting_seed = False
_was_offroad = True
_live_streak = 0.0
_trip_lock = threading.Lock()
_PERSIST_KEYS = (
  "trip_m", "eng_m", "eng_s", "tot_s",
  "last_m", "last_eng_m", "last_eng_s", "last_tot_s", "route",
  "week_m", "week_eng_m", "week_eng_s", "week_tot_s", "week_id",
  "today_m", "today_eng_m", "day_id", "seed",
  "life_m", "life_e", "max_streak_m", "max_day_streak", "v",
)
TRIP_VER = 5
RESET_KEYS = (
  "today_m", "today_eng_m", "week_m", "week_eng_m", "week_eng_s", "week_tot_s",
  "life_m", "life_e",
)


def _params_trip() -> dict:
  try:
    v = Params().get("TripMeter")
    if isinstance(v, dict):
      return v
    if isinstance(v, (bytes, bytearray)):
      v = v.decode()
    if isinstance(v, str) and v.strip():
      d = json.loads(v)
      return d if isinstance(d, dict) else {}
  except Exception:
    pass
  return {}


def _persist_blob(t: dict) -> dict:
  out: dict = {}
  for k in _PERSIST_KEYS:
    v = t.get(k)
    if isinstance(v, bool) or v is None:
      out[k] = "" if k.endswith("_id") or k in ("route", "seed") else 0.0
    elif k == "v":
      out[k] = TRIP_VER
    elif isinstance(v, (int, float)) and k not in ("route", "seed", "week_id", "day_id"):
      out[k] = float(v)
    else:
      out[k] = "" if v is None else str(v)
  out["v"] = TRIP_VER
  return out


SEED_OUT = "/data/trip_seed_out.json"


def _write_trip_file(blob: dict) -> None:
  tmp = TRIP_PATH + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(blob, f)
  os.replace(tmp, TRIP_PATH)


def _write_trip_param(blob: dict, block: bool = False) -> None:
  try:
    Params().put("TripMeter", blob, block=block)
  except Exception:
    pass


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


def _read_seed_out() -> dict | None:
  try:
    if not os.path.isfile(SEED_OUT):
      return None
    s = json.loads(open(SEED_OUT, encoding="utf-8").read())
    os.remove(SEED_OUT)
    return s if isinstance(s, dict) else None
  except Exception:
    return None


def _load_trip() -> tuple[dict, bool]:
  t = empty_trip()
  try:
    t = merge_snapshots(t, json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  t = merge_snapshots(t, _params_trip())
  try:
    ver = int(t.get("v") or 0)
  except (TypeError, ValueError):
    ver = 0
  if ver != TRIP_VER:
    for k in RESET_KEYS:
      t[k] = 0.0
    t["v"] = TRIP_VER
    t["seed"] = "live"
  if not str(t.get("week_id") or ""):
    t["week_id"] = sunday_id()
  if not str(t.get("day_id") or ""):
    t["day_id"] = day_id()
  roll_ids(t)
  t["v"] = TRIP_VER
  return t, False


def trip_snapshot() -> dict:
  with _trip_lock:
    if _trip is not None:
      return dict(_trip)
  t = empty_trip()
  try:
    t = merge_snapshots(t, json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  return merge_snapshots(t, _params_trip())


def tick_trip() -> None:
  global _trip, _trip_t, _trip_flush, _trip_param, _seed_started, _awaiting_seed, _was_offroad, _live_streak
  now = time.monotonic()
  _read_seed_out()
  park_cache = False
  file_blob = None
  param_blob = None
  param_block = False
  with _trip_lock:
    if _trip is None:
      _trip, need_seed = _load_trip()
      _trip_t = now
      _awaiting_seed = False
      _seed_started = True
      _trip["seed"] = "live"
      file_blob = _persist_blob(_trip)
      param_blob = file_blob
      param_block = True
    else:
      roll_ids(_trip)
      dt = min(1.0, max(0.0, now - _trip_t))
      _trip_t = now
      params = ui_state.params
      route = params.get("CurrentRoute") or ""
      if isinstance(route, bytes):
        route = route.decode(errors="replace")
      if route and route != _trip.get("route"):
        _trip["trip_m"] = _trip["eng_m"] = _trip["eng_s"] = _trip["tot_s"] = 0.0
        _trip["route"] = route
        _live_streak = 0.0
        file_blob = _persist_blob(_trip)
        param_blob = file_blob
      try:
        offroad = params.get_bool("IsOffroad")
        cs_ok = ui_state.sm.recv_frame["carState"] > 0
      except Exception:
        offroad, cs_ok = True, False
      if offroad and not _was_offroad:
        park_cache = True
      _was_offroad = offroad
      if (not offroad) and cs_ok:
        v = max(0.0, float(ui_state.sm["carState"].vEgo))
        _trip["tot_s"] += dt
        engaged = False
        try:
          engaged = ui_state.sm.recv_frame["selfdriveState"] > 0 and bool(ui_state.sm["selfdriveState"].enabled)
        except Exception:
          engaged = False
        if v > 0.15:
          d = v * dt
          _trip["trip_m"] += d
          _trip["week_m"] += d
          _trip["today_m"] = _trip.get("today_m", 0.0) + d
          _trip["life_m"] = _trip.get("life_m", 0.0) + d
          if engaged:
            _trip["eng_m"] = _trip.get("eng_m", 0.0) + d
            _trip["week_eng_m"] = _trip.get("week_eng_m", 0.0) + d
            _trip["today_eng_m"] = _trip.get("today_eng_m", 0.0) + d
            _trip["life_e"] = _trip.get("life_e", 0.0) + d
            _trip["eng_s"] += dt
            _trip["week_eng_s"] += dt
            _live_streak += d
            _trip["max_streak_m"] = max(float(_trip.get("max_streak_m") or 0), _live_streak)
          else:
            _live_streak = 0.0
        elif not engaged:
          _live_streak = 0.0
      if now - _trip_flush > 1.0:
        file_blob = _persist_blob(_trip)
        _trip_flush = now
      if now - _trip_param > 5.0:
        param_blob = file_blob or _persist_blob(_trip)
        _trip_param = now

  if file_blob is not None:
    try:
      _write_trip_file(file_blob)
    except Exception:
      cloudlog.exception("trip save")
  if param_blob is not None:
    _write_trip_param(param_blob, block=param_block or park_cache)
  if park_cache:
    _spawn_trip_job("cache")


def trip_pct() -> int:
  t = _trip
  if t is None:
    return 0
  m = float(t.get("trip_m") or 0)
  e = float(t.get("eng_m") or 0)
  return int(round(100.0 * e / m)) if m > 1 else 0


def _rpy_lines(roll: float, pitch: float, yaw: float) -> tuple[str, str, str]:
  pitch_s = f"P {abs(pitch):.1f}° {'down' if pitch > 0 else 'up'}"
  yaw_s = f"Y {abs(yaw):.1f}° {'left' if yaw > 0 else 'right'}"
  roll_s = f"R {abs(roll):.1f}° {'cw' if roll > 0 else 'ccw'}"
  return pitch_s, yaw_s, roll_s


def calib_button_value(params: Params | None = None, compact: bool = False) -> str:
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
