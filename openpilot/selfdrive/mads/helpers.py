from openpilot.common.params import Params
from opendbc.car import structs
from opendbc.safety import ALTERNATIVE_EXPERIENCE

MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")


class MadsSteeringModeOnBrake:
  REMAIN_ACTIVE = 0
  PAUSE = 1
  DISENGAGE = 2


def read_steering_mode_param(CP: structs.CarParams, params: Params) -> int:
  if CP.brand in ("rivian", "tesla"):
    return MadsSteeringModeOnBrake.DISENGAGE
  return params.get("MadsSteeringMode", return_default=True)


def set_alternative_experience(CP: structs.CarParams, params: Params) -> None:
  enabled = params.get_bool("Mads") and CP.openpilotLongitudinalControl
  steering_mode = read_steering_mode_param(CP, params)

  if not enabled:
    return

  CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_MADS
  if steering_mode == MadsSteeringModeOnBrake.DISENGAGE:
    CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_DISENGAGE_LATERAL_ON_BRAKE
  elif steering_mode == MadsSteeringModeOnBrake.PAUSE:
    CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_PAUSE_LATERAL_ON_BRAKE
