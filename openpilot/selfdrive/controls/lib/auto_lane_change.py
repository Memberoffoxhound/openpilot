from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL

# Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot #653).
# Nudgeless only. Stock nudge is AutoLaneChangeEnabled=False in desire_helper.
START_DELAY = 0.05
BSM_CLEAR_S = 1.0


class AutoLaneChangeController:
  def __init__(self, desire_helper):
    self.DH = desire_helper
    self.params = Params()
    self.enabled = False
    self.lane_change_wait_timer = 0.0
    self.param_read_counter = 0
    self.prev_brake_pressed = False
    self.auto_lane_change_allowed = False
    self.prev_lane_change = False
    self.read_params()

  def read_params(self):
    self.enabled = self.params.get_bool("AutoLaneChangeEnabled")

  def update_params(self):
    if self.param_read_counter % 50 == 0:
      self.read_params()
    self.param_read_counter += 1

  def reset(self):
    if self.DH.lane_change_state == log.LaneChangeState.off and \
       self.DH.lane_change_direction == log.LaneChangeDirection.none:
      self.lane_change_wait_timer = 0.0
      self.prev_brake_pressed = False
      self.prev_lane_change = False

  def update_lane_change(self, blindspot_detected: bool, brake_pressed: bool):
    if brake_pressed and not self.prev_brake_pressed:
      self.prev_brake_pressed = True
    self.lane_change_wait_timer += DT_MDL
    if blindspot_detected:
      self.lane_change_wait_timer = -BSM_CLEAR_S
    self.auto_lane_change_allowed = (
      self.enabled
      and not self.prev_brake_pressed
      and not self.prev_lane_change
      and self.lane_change_wait_timer > START_DELAY
    )

  def update_state(self):
    if self.DH.lane_change_state == log.LaneChangeState.laneChangeStarting:
      self.prev_lane_change = True
    self.reset()
