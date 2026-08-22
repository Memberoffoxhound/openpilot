import math
import os
import time

import pyray as rl
from openpilot.cereal import messaging, log
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


LUDI_MS2 = 3.8
LUDI_COOLDOWN = 45.0
_warp_t0: float | None = None
_warp_last = 0.0


def trigger_ludicrous(*, preview: bool = False) -> None:
  """Start warp + sound. Preview ignores cooldown and on-road."""
  global _warp_t0, _warp_last
  now = time.monotonic()
  if not preview and (now - _warp_last) < LUDI_COOLDOWN:
    return
  _warp_t0 = now
  _warp_last = now
  request_ludicrous_play()


def maybe_trigger_ludicrous() -> None:
  if not ui_state.started or not ludicrous_on():
    return
  try:
    a = float(ui_state.sm["carState"].aEgo)
  except Exception:
    return
  if a >= LUDI_MS2:
    trigger_ludicrous(preview=False)


def draw_ludicrous_warp(rect: rl.Rectangle) -> None:
  global _warp_t0
  if _warp_t0 is None:
    return
  t = time.monotonic() - _warp_t0
  fade_in, hold, fade_out = 0.18, 0.95, 0.45
  total = fade_in + hold + fade_out
  if t > total:
    _warp_t0 = None
    return
  if t < fade_in:
    alpha = t / fade_in
  elif t < fade_in + hold:
    alpha = 1.0
  else:
    alpha = max(0.0, 1.0 - (t - fade_in - hold) / fade_out)
  cx = rect.x + rect.width * 0.5
  cy = rect.y + rect.height * 0.5
  prog = min(1.0, t / (fade_in + hold))
  span = max(rect.width, rect.height)
  n = 56
  for i in range(n):
    ang = (i / n) * math.tau + t * 0.35
    inner = 6.0 + prog * 28.0
    outer = 40.0 + prog * span
    c, s = math.cos(ang), math.sin(ang)
    rl.draw_line_ex(
      rl.Vector2(cx + inner * c, cy + inner * s),
      rl.Vector2(cx + outer * c, cy + outer * s),
      2.2 if i % 3 else 1.2,
      rl.Color(210, 230, 255, int(200 * alpha)),
    )
  rl.draw_rectangle_rec(rect, rl.Color(8, 12, 28, int(40 * alpha)))


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
