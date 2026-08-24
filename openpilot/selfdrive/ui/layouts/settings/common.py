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


_LUDI_MODE = "/data/ludicrous_mode"
_LUDI_PLAY = "/data/ludicrous_play"
_BUCKLE_MODE = "/data/buckle_sound"
_BUCKLE_PLAY = "/data/buckle_play"
_DELOREAN_MODE = "/data/delorean_sound"
_DELOREAN_PLAY = "/data/delorean_play"
TRIP_PATH = "/data/trip_meter.json"
LUDI_WAVS = (
  "/data/ludicrous.wav",
  BASEDIR + "/openpilot/selfdrive/assets/sounds/ludicrous.wav",
)


def ludicrous_on() -> bool:
  try:
    return open(_LUDI_MODE, encoding="utf-8").read().strip() in ("1", "true")
  except Exception:
    return False


def set_ludicrous(on: bool) -> None:
  with open(_LUDI_MODE, "w", encoding="utf-8") as f:
    f.write("1" if on else "0")


def request_ludicrous_play() -> None:
  with open(_LUDI_PLAY, "w", encoding="utf-8") as f:
    f.write("1")


def consume_ludicrous_play() -> bool:
  try:
    if open(_LUDI_PLAY, encoding="utf-8").read().strip() in ("1", "true"):
      os.unlink(_LUDI_PLAY)
      return True
  except Exception:
    return False
  return False


def buckle_on() -> bool:
  try:
    return open(_BUCKLE_MODE, encoding="utf-8").read().strip() in ("1", "true")
  except Exception:
    return False


def set_buckle(on: bool) -> None:
  with open(_BUCKLE_MODE, "w", encoding="utf-8") as f:
    f.write("1" if on else "0")


def request_buckle_play() -> None:
  with open(_BUCKLE_PLAY, "w", encoding="utf-8") as f:
    f.write("1")


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


def _first_file(paths) -> str | None:
  for p in paths:
    if os.path.isfile(p):
      return p
  return None


def ludicrous_files_ok() -> bool:
  return _first_file(LUDI_WAVS) is not None


LUDI_MS2 = 3.8
LUDI_COOLDOWN = 45.0
LUDI_FADE_IN = 0.12
LUDI_HOLD = 1.55
LUDI_FADE_OUT = 0.50
_warp_t0: float | None = None
_warp_last = 0.0
_STARS = tuple(
  (i * 2.399963, (i * 0.618034) % 1.0, 0.55 + (i % 7) * 0.22, 1.1 + (i % 5) * 0.35)
  for i in range(120)
)
_seen_offroad = False
_mid_drive_boot = False
_ludi_drive = False


def tick_egg_drive() -> None:
  """Arm easter eggs only after this process has seen offroad. Reboot mid-drive stays silent."""
  global _seen_offroad, _mid_drive_boot, _ludi_drive
  if not ui_state.started:
    _seen_offroad = True
    _mid_drive_boot = False
    _ludi_drive = False
    return
  if not _seen_offroad:
    _mid_drive_boot = True


def eggs_live() -> bool:
  return bool(ui_state.started and _seen_offroad and not _mid_drive_boot)


def trigger_ludicrous(*, preview: bool = False) -> bool:
  global _warp_t0, _warp_last, _ludi_drive
  if not ludicrous_files_ok():
    return False
  if not preview:
    tick_egg_drive()
    if not eggs_live() or _ludi_drive:
      return True
    _ludi_drive = True
  now = time.monotonic()
  if not preview and (now - _warp_last) < LUDI_COOLDOWN:
    return True
  _warp_t0 = now
  _warp_last = now
  request_ludicrous_play()
  return True


def maybe_trigger_ludicrous() -> None:
  if not ludicrous_on():
    return
  tick_egg_drive()
  if not eggs_live():
    return
  try:
    a = float(ui_state.sm["carState"].aEgo)
  except Exception:
    return
  if a >= LUDI_MS2:
    trigger_ludicrous(preview=False)


def draw_ludicrous_warp(rect: rl.Rectangle) -> None:
  """ANH hyperspace: radial star streaks, full screen, then fade back."""
  global _warp_t0
  if _warp_t0 is None:
    return
  t = time.monotonic() - _warp_t0
  total = LUDI_FADE_IN + LUDI_HOLD + LUDI_FADE_OUT
  if t > total:
    _warp_t0 = None
    return
  if t < LUDI_FADE_IN:
    a = t / LUDI_FADE_IN
  elif t < LUDI_FADE_IN + LUDI_HOLD:
    a = 1.0
  else:
    a = max(0.0, 1.0 - (t - LUDI_FADE_IN - LUDI_HOLD) / LUDI_FADE_OUT)
  p = min(1.0, t / (LUDI_FADE_IN + LUDI_HOLD))
  p2 = p * p
  cx = rect.x + rect.width * 0.5
  cy = rect.y + rect.height * 0.5
  span = math.hypot(rect.width, rect.height) * 0.62
  stretch = 6.0 + p2 * 140.0
  rl.draw_rectangle_rec(rect, rl.Color(2, 6, 22, int(170 * a)))
  for ang, r0, spd, w in _STARS:
    r = (r0 + p * spd) % 1.0
    r = 0.04 + r * 0.96
    inner = r * span * (0.08 + 0.92 * p)
    outer = inner + stretch * (0.25 + r)
    ca, sa = math.cos(ang), math.sin(ang)
    thick = w * (0.8 + 1.8 * p)
    rl.draw_line_ex(
      rl.Vector2(cx + inner * ca, cy + inner * sa),
      rl.Vector2(cx + outer * ca, cy + outer * sa),
      thick,
      rl.Color(210, 230, 255, int((90 + 140 * r) * a)),
    )
  if p > 0.45:
    flash = 1.0 - abs(((p - 0.45) / 0.55) * 2.0 - 1.0)
    rl.draw_circle(int(cx), int(cy), int(18 + flash * 70), rl.Color(190, 220, 255, int(55 * flash * a)))


def _day_id() -> str:
  try:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/Chicago"))
    return f"{now.year:04d}-{now.month:02d}-{now.day:02d}"
  except Exception:
    st = time.localtime()
    return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d}"


def _sunday_id() -> str:
  """Local Sunday date. Device TZ is UTC; week boundary is America/Chicago."""
  try:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/Chicago"))
    sun = now - timedelta(days=(now.weekday() + 1) % 7)
    return f"{sun.year:04d}-{sun.month:02d}-{sun.day:02d}"
  except Exception:
    now = time.localtime()
    sun = time.mktime(now) - ((now.tm_wday + 1) % 7) * 86400
    st = time.localtime(sun)
    return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d}"


_trip: dict | None = None
_trip_t = 0.0
_trip_flush = 0.0
_seed_started = False


def _run_seed() -> None:
  global _trip
  try:
    from openpilot.selfdrive.ui.layouts.settings.trip_seed import seed_week_today
    s = seed_week_today()
  except Exception:
    cloudlog.exception("trip seed")
    return
  if not s or _trip is None:
    return
  _trip["week_m"] = float(s["week_m"])
  _trip["week_eng_m"] = float(s["week_eng_m"])
  _trip["today_m"] = float(s["today_m"])
  _trip["today_eng_m"] = float(s["today_eng_m"])
  _trip["week_id"] = s["week_id"]
  _trip["day_id"] = s["day_id"]
  _trip["seed"] = "qlog"
  try:
    _save_trip(_trip)
  except Exception:
    pass


def _load_trip() -> dict:
  t = {"trip_m": 0.0, "eng_m": 0.0, "eng_s": 0.0, "tot_s": 0.0,
       "last_m": 0.0, "last_eng_m": 0.0, "last_eng_s": 0.0, "last_tot_s": 0.0, "route": "",
       "week_m": 0.0, "week_eng_m": 0.0, "week_eng_s": 0.0, "week_tot_s": 0.0, "week_id": "",
       "today_m": 0.0, "today_eng_m": 0.0, "day_id": ""}
  try:
    t.update(json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  for m_key, e_key, es_key, ts_key in (
    ("trip_m", "eng_m", "eng_s", "tot_s"),
    ("last_m", "last_eng_m", "last_eng_s", "last_tot_s"),
    ("week_m", "week_eng_m", "week_eng_s", "week_tot_s"),
  ):
    if not t.get(e_key) and t.get(m_key) and (t.get(ts_key) or 0) > 1:
      t[e_key] = float(t[m_key]) * float(t.get(es_key, 0) or 0) / float(t[ts_key])
  return t


def _save_trip(t: dict) -> None:
  tmp = TRIP_PATH + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(t, f)
  os.replace(tmp, TRIP_PATH)


def tick_trip() -> None:
  """Today/Week from stock carState.vEgo + selfdriveState.enabled. UI-thread."""
  global _trip, _trip_t, _trip_flush, _seed_started
  now = time.monotonic()
  if _trip is None:
    _trip = _load_trip()
    _trip_t = now
    if not _seed_started:
      _seed_started = True
      threading.Thread(target=_run_seed, daemon=True).start()

  # Rollover checks execute every tick across midnight & Sundays
  wid = _sunday_id()
  if not _trip.get("week_id"):
    _trip["week_id"] = wid
  elif _trip.get("week_id") != wid:
    _trip["week_m"] = _trip["week_eng_m"] = _trip["week_eng_s"] = _trip["week_tot_s"] = 0.0
    _trip["week_id"] = wid

  did = _day_id()
  if not _trip.get("day_id"):
    _trip["day_id"] = did
  elif _trip.get("day_id") != did:
    _trip["today_m"] = _trip["today_eng_m"] = 0.0
    _trip["day_id"] = did

  dt = min(1.0, max(0.0, now - _trip_t))
  _trip_t = now
  params = ui_state.params
  route = params.get("CurrentRoute") or ""
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
