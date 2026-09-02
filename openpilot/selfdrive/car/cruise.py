import math
import numpy as np

from opendbc.car.structs import car
from openpilot.common.constants import CV
from openpilot.common.params import Params


# WARNING: this value was determined based on the model's training distribution,
#          model predictions above this speed can be unpredictable
# V_CRUISE's are in kph
V_CRUISE_MIN = 8
V_CRUISE_MAX = 145
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 40
V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105
IMPERIAL_INCREMENT = round(CV.MPH_TO_KPH, 1)  # round here to avoid rounding errors incrementing set speed

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type
CRUISE_LONG_PRESS = 50
CRUISE_NEAREST_FUNC = {
  ButtonType.accelCruise: math.ceil,
  ButtonType.decelCruise: math.floor,
}
CRUISE_INTERVAL_SIGN = {
  ButtonType.accelCruise: +1,
  ButtonType.decelCruise: -1,
}

# Lift-off adopt: take current speed as the cruise target after a pedal overshoot.
ADOPT_DEADZONE_MS = 0.45  # ~1 mph


class VCruiseHelper:
  def __init__(self, CP):
    self.CP = CP
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.v_cruise_kph_last = 0
    self.button_timers = {ButtonType.decelCruise: 0, ButtonType.accelCruise: 0}
    self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}
    self.params = Params()
    self.gas_pressed_last = False
    self.adopted_v_cruise_kph = 0.0
    self.pcm_v_cruise_kph_last = 0.0

  @property
  def v_cruise_initialized(self):
    return self.v_cruise_kph != V_CRUISE_UNSET

  def update_v_cruise(self, CS, enabled, is_metric):
    self.v_cruise_kph_last = self.v_cruise_kph

    if CS.cruiseState.available:
      if not self.CP.pcmCruise:
        # if stock cruise is completely disabled, then we can use our own set speed logic
        self._update_v_cruise_non_pcm(CS, enabled, is_metric)
        self._maybe_adopt_lift_speed(CS, enabled, is_metric, pcm_kph=self.v_cruise_kph)
        self.v_cruise_cluster_kph = self.v_cruise_kph
        self.update_button_timers(CS, enabled)
      else:
        pcm_kph = CS.cruiseState.speed * CV.MS_TO_KPH
        self.v_cruise_kph = pcm_kph
        self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
        if CS.cruiseState.speed == 0:
          self.v_cruise_kph = V_CRUISE_UNSET
          self.v_cruise_cluster_kph = V_CRUISE_UNSET
        elif CS.cruiseState.speed == -1:
          self.v_cruise_kph = -1
          self.v_cruise_cluster_kph = -1
        else:
          self._maybe_adopt_lift_speed(CS, enabled, is_metric, pcm_kph=pcm_kph)
    else:
      self.v_cruise_kph = V_CRUISE_UNSET
      self.v_cruise_cluster_kph = V_CRUISE_UNSET
      self.adopted_v_cruise_kph = 0.0

    self.gas_pressed_last = bool(CS.gasPressed)

  def _maybe_adopt_lift_speed(self, CS, enabled, is_metric, pcm_kph):
    # OP long only. Tesla cluster DI_digitalSpeed stays on the PCM value; comma HUD + planner use this.
    if not self.CP.openpilotLongitudinalControl or not self.params.get_bool("SoftCruiseReturn"):
      self.adopted_v_cruise_kph = 0.0
      return
    if not enabled or self.v_cruise_kph in (V_CRUISE_UNSET, -1):
      self.adopted_v_cruise_kph = 0.0
      return

    inc = 1.0 if is_metric else IMPERIAL_INCREMENT
    v_ego_kph = CS.vEgo * CV.MS_TO_KPH

    # Any real Tesla/PCM set-speed change drops the shadow (user rolled the wheel).
    if self.pcm_v_cruise_kph_last and abs(pcm_kph - self.pcm_v_cruise_kph_last) >= (inc * 0.5):
      self.adopted_v_cruise_kph = 0.0
    self.pcm_v_cruise_kph_last = pcm_kph

    gas_falling = self.gas_pressed_last and not CS.gasPressed
    if gas_falling and (v_ego_kph - pcm_kph) > (ADOPT_DEADZONE_MS * CV.MS_TO_KPH):
      self.adopted_v_cruise_kph = float(np.clip(round(v_ego_kph / inc) * inc, V_CRUISE_MIN, V_CRUISE_MAX))

    if self.adopted_v_cruise_kph > 0:
      self.v_cruise_kph = max(pcm_kph, self.adopted_v_cruise_kph)
      self.v_cruise_cluster_kph = self.v_cruise_kph

  def _update_v_cruise_non_pcm(self, CS, enabled, is_metric):
    # handle button presses. TODO: this should be in state_control, but a decelCruise press
    # would have the effect of both enabling and changing speed is checked after the state transition
    if not enabled:
      return

    long_press = False
    button_type = None

    v_cruise_delta = 1. if is_metric else IMPERIAL_INCREMENT

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers and not b.pressed:
        if self.button_timers[b.type.raw] > CRUISE_LONG_PRESS:
          return  # end long press
        button_type = b.type.raw
        break
    else:
      for k, timer in self.button_timers.items():
        if timer and timer % CRUISE_LONG_PRESS == 0:
          button_type = k
          long_press = True
          break

    if button_type is None:
      return

    # Don't adjust speed when pressing resume to exit standstill
    cruise_standstill = self.button_change_states[button_type]["standstill"] or CS.cruiseState.standstill
    if button_type == ButtonType.accelCruise and cruise_standstill:
      return

    # Don't adjust speed if we've enabled since the button was depressed (some ports enable on rising edge)
    if not self.button_change_states[button_type]["enabled"]:
      return

    v_cruise_delta = v_cruise_delta * (5 if long_press else 1)
    if long_press and self.v_cruise_kph % v_cruise_delta != 0:  # partial interval
      self.v_cruise_kph = CRUISE_NEAREST_FUNC[button_type](self.v_cruise_kph / v_cruise_delta) * v_cruise_delta
    else:
      self.v_cruise_kph += v_cruise_delta * CRUISE_INTERVAL_SIGN[button_type]

    # If set is pressed while overriding, clip cruise speed to minimum of vEgo
    if CS.gasPressed and button_type in (ButtonType.decelCruise, ButtonType.setCruise):
      self.v_cruise_kph = max(self.v_cruise_kph, CS.vEgo * CV.MS_TO_KPH)

    self.v_cruise_kph = np.clip(round(self.v_cruise_kph, 1), V_CRUISE_MIN, V_CRUISE_MAX)

  def update_button_timers(self, CS, enabled):
    # increment timer for buttons still pressed
    for k in self.button_timers:
      if self.button_timers[k] > 0:
        self.button_timers[k] += 1

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers:
        # Start/end timer and store current state on change of button pressed
        self.button_timers[b.type.raw] = 1 if b.pressed else 0
        self.button_change_states[b.type.raw] = {"standstill": CS.cruiseState.standstill, "enabled": enabled}

  def initialize_v_cruise(self, CS, experimental_mode: bool) -> None:
    # initializing is handled by the PCM
    if self.CP.pcmCruise:
      return

    initial = V_CRUISE_INITIAL_EXPERIMENTAL_MODE if experimental_mode else V_CRUISE_INITIAL

    if any(b.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for b in CS.buttonEvents) and self.v_cruise_initialized:
      self.v_cruise_kph = self.v_cruise_kph_last
    else:
      self.v_cruise_kph = int(round(np.clip(CS.vEgo * CV.MS_TO_KPH, initial, V_CRUISE_MAX)))

    self.v_cruise_cluster_kph = self.v_cruise_kph
    self.adopted_v_cruise_kph = 0.0
