import json
import math
import os
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
TRIP_PATH = "/data/trip_meter.json"
LUDI_WAVS = (
  "/data/ludicrous.wav",
  BASEDIR + "/openpilot/selfdrive/assets/sounds/ludicrous.wav",
)
LUDI_GIFS = (
  "/data/ludicrous.gif",
  BASEDIR + "/openpilot/selfdrive/assets/images/ludicrous.gif",
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


def _first_file(paths) -> str | None:
  for p in paths:
    if os.path.isfile(p):
      return p
  return None


def ludicrous_files_ok() -> bool:
  return _first_file(LUDI_WAVS) is not None and _first_file(LUDI_GIFS) is not None


LUDI_MS2 = 3.8
LUDI_COOLDOWN = 45.0
LUDI_FADE_IN = 0.20
LUDI_FADE_OUT = 0.35
_warp_t0: float | None = None
_warp_last = 0.0
_clip = None  # lazy {frames, w, h, dt, tex, idx}


def trigger_ludicrous(*, preview: bool = False) -> bool:
  """Start clip + sound. Returns False if drop-in files are missing."""
  global _warp_t0, _warp_last
  if not ludicrous_files_ok():
    return False
  now = time.monotonic()
  if not preview and (now - _warp_last) < LUDI_COOLDOWN:
    return True
  _warp_t0 = now
  _warp_last = now
  request_ludicrous_play()
  return True


def maybe_trigger_ludicrous() -> None:
  if not ui_state.started or not ludicrous_on():
    return
  try:
    a = float(ui_state.sm["carState"].aEgo)
  except Exception:
    return
  if a >= LUDI_MS2:
    trigger_ludicrous(preview=False)


def _load_clip():
  global _clip
  if _clip is not None:
    return _clip
  path = _first_file(LUDI_GIFS)
  if path is None:
    _clip = False
    return None
  try:
    from PIL import Image
    im = Image.open(path)
    frames = []
    n = getattr(im, "n_frames", 1)
    for i in range(n):
      im.seek(i)
      frames.append(im.convert("RGBA").tobytes())
    w, h = im.size
    # Texture must be RGBA — gen_image_color is R8G8B8A8. RGB tobytes painted black.
    img = rl.gen_image_color(w, h, rl.BLACK)
    tex = rl.load_texture_from_image(img)
    rl.unload_image(img)
    rl.update_texture(tex, frames[0])
    _clip = {"frames": frames, "w": w, "h": h, "dt": 1.0 / 12.0, "tex": tex, "n": n}
    return _clip
  except Exception:
    _clip = False
    return None


def _clip_alpha(t: float, dur: float) -> float:
  if t < LUDI_FADE_IN:
    return t / LUDI_FADE_IN
  if t > dur - LUDI_FADE_OUT:
    return max(0.0, (dur - t) / LUDI_FADE_OUT)
  return 1.0


def draw_ludicrous_warp(rect: rl.Rectangle) -> None:
  """Center-crop GIF into the camera rect. Does not draw into the side panel."""
  global _warp_t0
  if _warp_t0 is None:
    return
  clip = _load_clip()
  if not clip:
    _warp_t0 = None
    return
  dur = clip["n"] * clip["dt"]
  t = time.monotonic() - _warp_t0
  if t > dur:
    _warp_t0 = None
    return
  alpha = _clip_alpha(t, dur)
  idx = min(clip["n"] - 1, int(t / clip["dt"]))
  w, h = clip["w"], clip["h"]
  try:
    rl.update_texture(clip["tex"], clip["frames"][idx])
  except Exception:
    pass
  # cover crop, pin slightly high so the subtitle stays
  scale = max(rect.width / w, rect.height / h)
  dw, dh = w * scale, h * scale
  ox = rect.x - (dw - rect.width) * 0.5
  oy = rect.y - (dh - rect.height) * 0.72
  src = rl.Rectangle(0, 0, w, h)
  dst = rl.Rectangle(ox, oy, dw, dh)
  rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
  rl.draw_texture_pro(clip["tex"], src, dst, rl.Vector2(0, 0), 0.0, rl.Color(255, 255, 255, int(255 * alpha)))
  rl.end_scissor_mode()


def _sunday_id() -> str:
  now = time.localtime()
  sun = time.mktime(now) - ((now.tm_wday + 1) % 7) * 86400
  st = time.localtime(sun)
  return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d}"


_trip: dict | None = None
_trip_t = 0.0
_trip_flush = 0.0


def _load_trip() -> dict:
  t = {"trip_m": 0.0, "eng_m": 0.0, "eng_s": 0.0, "tot_s": 0.0,
       "last_m": 0.0, "last_eng_m": 0.0, "last_eng_s": 0.0, "last_tot_s": 0.0, "route": "",
       "week_m": 0.0, "week_eng_m": 0.0, "week_eng_s": 0.0, "week_tot_s": 0.0, "week_id": ""}
  try:
    t.update(json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  # One-time seed: old files only had time-based engaged seconds.
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
  """Last/Week from stock carState.vEgo + selfdriveState.enabled. UI-thread."""
  global _trip, _trip_t, _trip_flush
  now = time.monotonic()
  if _trip is None:
    _trip = _load_trip()
    _trip_t = now
  dt = min(1.0, max(0.0, now - _trip_t))
  _trip_t = now
  params = ui_state.params
  route = params.get("CurrentRoute") or ""
  wid = _sunday_id()
  if _trip.get("week_id") != wid:
    _trip["week_m"] = _trip["week_eng_m"] = _trip["week_eng_s"] = _trip["week_tot_s"] = 0.0
    _trip["week_id"] = wid
  if route and route != _trip.get("route"):
    if _trip.get("trip_m", 0) > 50 or _trip.get("tot_s", 0) > 5:
      _trip["last_m"] = _trip["trip_m"]
      _trip["last_eng_m"] = _trip.get("eng_m", 0.0)
      _trip["last_eng_s"] = _trip["eng_s"]
      _trip["last_tot_s"] = _trip["tot_s"]
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
      try:
        if ui_state.sm.recv_frame["selfdriveState"] > 0 and ui_state.sm["selfdriveState"].enabled:
          _trip["eng_m"] = _trip.get("eng_m", 0.0) + v * dt
          _trip["week_eng_m"] = _trip.get("week_eng_m", 0.0) + v * dt
          _trip["eng_s"] += dt
          _trip["week_eng_s"] += dt
      except Exception:
        pass
  if now - _trip_flush > 1.0:
    _save_trip(_trip)
    _trip_flush = now


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
