"""
Nudgeless / timed auto lane change, adapted from sunnypilot
(openpilot/sunnypilot/selfdrive/controls/lib/auto_lane_change.py).

Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.
Licensed under the MIT License.

TeslaPilot Highland defaults:
  - Nudgeless (blinker starts the change, no steering nudge)
  - Blind-spot delay: wait until DAS BSM is clear, then ~1s more
  - Speed floor is applied in desire_helper (25 mph)
  - Engaged gate is applied in desire_helper (lateral_active)

AutoLaneChangeTimer values (Toggles → Auto Lane Change):
  -1 Off (no lane change at all — not in the UI cycle)
   0 Nudge (stock openpilot — must apply steering torque)
   1 Nudgeless (~0.05 s)
   2–11 timed delay, 0.5 s steps from 0.5 s through 5.0 s
"""
from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL


class AutoLaneChangeMode:
  OFF = -1
  NUDGE = 0
  NUDGELESS = 1
  DELAY_MIN = 2   # 0.5 s
  DELAY_MAX = 11  # 5.0 s


AUTO_LANE_CHANGE_TIMER = {
  AutoLaneChangeMode.OFF: 0.0,
  AutoLaneChangeMode.NUDGE: 0.0,
  AutoLaneChangeMode.NUDGELESS: 0.05,
}

ALC_MODE_LABELS = {
  AutoLaneChangeMode.OFF: "Off",
  AutoLaneChangeMode.NUDGE: "Nudge",
  AutoLaneChangeMode.NUDGELESS: "Nudgeless",
}

for _mode in range(AutoLaneChangeMode.DELAY_MIN, AutoLaneChangeMode.DELAY_MAX + 1):
  _sec = 0.5 * (_mode - 1)
  AUTO_LANE_CHANGE_TIMER[_mode] = _sec
  ALC_MODE_LABELS[_mode] = f"{_sec:g} s"

# C4 / tici cycle order: one tap from the default lands on stock nudge.
ALC_UI_MODES = (
  [AutoLaneChangeMode.NUDGELESS, AutoLaneChangeMode.NUDGE] +
  list(range(AutoLaneChangeMode.DELAY_MIN, AutoLaneChangeMode.DELAY_MAX + 1))
)

# When BSM is occupied on a nudgeless/timed change, rewind the wait so the
# lane change cannot start until the spot has been clear ~1s.
ONE_SECOND_DELAY = -1


def normalize_alc_mode(value) -> int:
  try:
    mode = AutoLaneChangeMode.NUDGELESS if value is None else int(value)
  except (TypeError, ValueError):
    return AutoLaneChangeMode.NUDGELESS
  if mode == AutoLaneChangeMode.OFF:
    return AutoLaneChangeMode.OFF
  if mode not in AUTO_LANE_CHANGE_TIMER:
    return AutoLaneChangeMode.NUDGELESS
  return mode


def next_alc_mode(current: int) -> int:
  mode = normalize_alc_mode(current)
  if mode not in ALC_UI_MODES:
    return AutoLaneChangeMode.NUDGELESS
  idx = ALC_UI_MODES.index(mode)
  return ALC_UI_MODES[(idx + 1) % len(ALC_UI_MODES)]


def alc_label(value) -> str:
  return ALC_MODE_LABELS[normalize_alc_mode(value)]


class AutoLaneChangeController:
  def __init__(self, desire_helper):
    self.DH = desire_helper
    self.params = Params()
    self.lane_change_wait_timer = 0.0
    self.param_read_counter = 0
    self.lane_change_delay = 0.0
    self.lane_change_set_timer = AutoLaneChangeMode.NUDGELESS
    self.lane_change_bsm_delay = True
    self.prev_brake_pressed = False
    self.auto_lane_change_allowed = False
    self.prev_lane_change = False
    self.read_params()

  def reset(self) -> None:
    if self.DH.lane_change_state == log.LaneChangeState.off and \
       self.DH.lane_change_direction == log.LaneChangeDirection.none:
      self.lane_change_wait_timer = 0.0
      self.prev_brake_pressed = False
      self.prev_lane_change = False

  def read_params(self) -> None:
    self.lane_change_set_timer = normalize_alc_mode(
      self.params.get("AutoLaneChangeTimer", return_default=True)
    )
    bsm = self.params.get("AutoLaneChangeBsmDelay", return_default=True)
    self.lane_change_bsm_delay = True if bsm is None else bool(bsm)

  def update_params(self) -> None:
    if self.param_read_counter % 50 == 0:
      self.read_params()
    self.param_read_counter += 1

  def update_lane_change_timers(self, blindspot_detected: bool) -> None:
    self.lane_change_delay = AUTO_LANE_CHANGE_TIMER.get(
      self.lane_change_set_timer, AUTO_LANE_CHANGE_TIMER[AutoLaneChangeMode.NUDGELESS]
    )
    self.lane_change_wait_timer += DT_MDL
    if self.lane_change_bsm_delay and blindspot_detected and self.lane_change_delay > 0:
      if self.lane_change_delay == AUTO_LANE_CHANGE_TIMER[AutoLaneChangeMode.NUDGELESS]:
        self.lane_change_wait_timer = ONE_SECOND_DELAY
      else:
        self.lane_change_wait_timer = self.lane_change_delay + ONE_SECOND_DELAY

  def update_allowed(self) -> bool:
    if self.lane_change_set_timer in (AutoLaneChangeMode.OFF, AutoLaneChangeMode.NUDGE):
      return False
    if self.prev_brake_pressed:
      return False
    if self.prev_lane_change:
      return False
    return bool(self.lane_change_wait_timer > self.lane_change_delay)

  def update_lane_change(self, blindspot_detected: bool, brake_pressed: bool) -> None:
    if brake_pressed and not self.prev_brake_pressed:
      self.prev_brake_pressed = brake_pressed
    self.update_lane_change_timers(blindspot_detected)
    self.auto_lane_change_allowed = self.update_allowed()

  def update_state(self):
    if self.DH.lane_change_state == log.LaneChangeState.laneChangeStarting:
      self.prev_lane_change = True
    self.reset()
