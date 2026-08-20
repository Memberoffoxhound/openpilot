import math

from openpilot.cereal import messaging, log
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


def calib_button_value(params: Params | None = None, compact: bool = False) -> str:
  """Pitch/yaw for the Reset Calibration control. compact=True is two lines for C4."""
  params = params or Params()
  calib_bytes = params.get("CalibrationParams")
  if not calib_bytes:
    return "uncalibrated"

  try:
    calib = messaging.log_from_bytes(calib_bytes, log.Event).extrinsicsCalibration
    if calib.calStatus == log.ExtrinsicsCalibration.Status.uncalibrated:
      return "uncalibrated"
    pitch = math.degrees(calib.rpyCalib[1])
    yaw = math.degrees(calib.rpyCalib[2])
  except Exception:
    cloudlog.exception("invalid CalibrationParams")
    return "uncalibrated"

  pitch_s = f"{abs(pitch):.1f}° {'down' if pitch > 0 else 'up'}"
  yaw_s = f"{abs(yaw):.1f}° {'left' if yaw > 0 else 'right'}"
  if compact:
    return f"{pitch_s}\n{yaw_s}"
  return f"{pitch_s} · {yaw_s}"
