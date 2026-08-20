import math

from openpilot.cereal import messaging, log
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


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
