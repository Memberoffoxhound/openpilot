from collections.abc import Callable

import pyray as rl
from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle, BigToggle, GreyBigButton, BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.selfdrive.ui.layouts.settings.common import (
  LANE_COLOR_LABELS, ONROAD_UI_LABELS, COMPASS_SIZE_LABELS,
  lane_color_label, next_lane_color,
  onroad_ui_label, next_onroad_ui, set_onroad_ui, restart_needed_callback,
  compass_size_label, next_compass_size,
  delorean_on, set_delorean, request_delorean_play,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.vslam.store import is_enabled, set_enabled

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


class AutoLaneChangeConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    warn = gui_app.texture("icons_mici/setup/warning.png", 64, 64)
    check = gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64)
    accept = BigConfirmationCircleButton("slide to\nenable", check,
                                         lambda: self.dismiss(on_confirm))
    self._scroller.add_widgets([
      GreyBigButton("enabling\nauto lane change", "scroll to continue", warn),
      GreyBigButton("", "Auto Lane Change uses Tesla's stock blind spot monitoring"),
      GreyBigButton("", "to check for a vehicle in the adjacent lane prior to merging."),
      GreyBigButton("", "You are still responsible for ensuring the lane of travel is clear"),
      GreyBigButton("", "and agree to intervene as necessary."),
      accept,
    ])


class OnroadUiCycle(BigButton):
  """Tap to switch stock onroad HUD vs custom."""

  def __init__(self):
    super().__init__("onroad UI", "")
    self._params = Params()
    self.refresh()

  def refresh(self):
    value = onroad_ui_label(self._params)
    if value != self.value:
      self.set_value(value)

  def show_event(self):
    super().show_event()
    self.refresh()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    nxt = next_onroad_ui(self._params)
    set_onroad_ui(nxt, self._params)
    self.set_value(ONROAD_UI_LABELS[nxt])


class CompassSizeCycle(BigButton):
  """Small left between DM and wheel, or large top-right. Custom UI only."""

  def __init__(self):
    super().__init__("compass size", "")
    self._params = Params()
    self.refresh()

  def refresh(self):
    value = compass_size_label(self._params)
    if value != self.value:
      self.set_value(value)

  def show_event(self):
    super().show_event()
    self.refresh()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    nxt = next_compass_size(self._params)
    self._params.put("CompassSize", nxt, block=True)
    self.set_value(COMPASS_SIZE_LABELS[nxt])


class LaneColorCycle(BigButton):
  """Tap to cycle tesla / openpilot paint. Tesla is Autopilot blue on lanes and HUD chrome."""

  def __init__(self):
    super().__init__("theme", "")
    self._params = Params()
    self.refresh()

  def refresh(self):
    value = lane_color_label(self._params)
    if value != self.value:
      self.set_value(value)

  def show_event(self):
    super().show_event()
    self.refresh()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    nxt = next_lane_color(self._params)
    self._params.put("LaneColor", nxt, block=True)
    self.set_value(LANE_COLOR_LABELS[nxt])


class DeloreanCycle(BigButton):
  """88mph clip on going onroad. Off by default."""

  def __init__(self):
    super().__init__("delorean", "")
    self.refresh()

  def refresh(self):
    value = "on" if delorean_on() else "off"
    if value != self.value:
      self.set_value(value)

  def show_event(self):
    super().show_event()
    self.refresh()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    on = not delorean_on()
    set_delorean(on)
    self.set_value("on" if on else "off")


class DeloreanPreview(BigButton):
  def __init__(self):
    super().__init__("delorean preview", "tap")

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    request_delorean_play()


class ThemeLayoutMici(NavScroller):
  """Settings → theme. Subsections live here."""

  def __init__(self):
    super().__init__()
    self._onroad_ui = OnroadUiCycle()
    self._compass_size = CompassSizeCycle()
    self._lane_color = LaneColorCycle()
    self._delorean = DeloreanCycle()
    self._delorean_preview = DeloreanPreview()
    self._scroller.add_widgets([
      self._onroad_ui, self._compass_size, self._lane_color,
      self._delorean, self._delorean_preview,
    ])


class ExperimentalModeConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()

    accept = BigConfirmationCircleButton("enable\nexperimental mode",
                                         gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                         lambda: self.dismiss(on_confirm))

    self._scroller.add_widgets([
      GreyBigButton("enabling\nexperimental mode", "scroll to continue",
                    gui_app.texture("icons_mici/setup/warning.png", 64, 64)),
      GreyBigButton("", "S3XYPilot defaults to driving in chill mode."),
      GreyBigButton("", "Experimental mode enables alpha-level features that aren't ready for chill mode."),
      GreyBigButton("End-to-End Longitudinal Control"),
      GreyBigButton("", "Let the driving model control the gas and brakes."),
      GreyBigButton("", "S3XYPilot will drive as it thinks a human would, including stopping for red lights and stop signs."),
      GreyBigButton("", "The set speed will only act as an upper bound."),
      GreyBigButton("", "This is an alpha quality feature; mistakes should be expected."),
      GreyBigButton("New Driving Visualization"),
      GreyBigButton("", "The path will change colors to communicate acceleration intent."),
      GreyBigButton("", "Red for braking, green for acceleration, and gray for coasting."),
      accept,
    ])


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"])
    self._experimental_btn = BigToggle("experimental mode", initial_state=ui_state.params.get_bool("ExperimentalMode"),
                                       toggle_callback=self._on_experimental_mode)
    # Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot).
    self._alc_btn = BigToggle("auto lane change", initial_state=ui_state.params.get_bool("AutoLaneChangeEnabled"),
                             toggle_callback=self._on_alc)
    self._vslam_btn = BigToggle("vSlam logger", initial_state=is_enabled(ui_state.params),
                               toggle_callback=self._on_vslam)
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM")
    record_front = BigParamControl("record & upload cabin camera", "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl("enable S3XYPilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)

    self._scroller.add_widgets([
      self._alc_btn,
      self._vslam_btn,
      self._personality_toggle,
      self._experimental_btn,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
      record_mic,
      enable_openpilot,
    ])

    # Toggle lists
    self._refresh_toggles = (
      ("ExperimentalMode", self._experimental_btn),
      ("AutoLaneChangeEnabled", self._alc_btn),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._experimental_btn.set_visible(True)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._experimental_btn.set_visible(False)
        self._experimental_btn.set_checked(False)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
    self._vslam_btn.set_checked(is_enabled(ui_state.params))

  def _on_vslam(self, state: bool):
    set_enabled(state, ui_state.params)

  def _on_alc(self, state: bool):
    if state:
      self._alc_btn.set_checked(False)

      def on_confirm():
        ui_state.params.put_bool("AutoLaneChangeEnabled", True, block=True)
        self._alc_btn.set_checked(True)

      gui_app.push_widget(AutoLaneChangeConfirmPage(on_confirm))
    else:
      ui_state.params.put_bool("AutoLaneChangeEnabled", False, block=True)

  def _on_experimental_mode(self, state: bool):
    if state and not ui_state.params.get_bool("ExperimentalModeConfirmed"):
      # Don't show enabled state until confirm
      self._experimental_btn.set_checked(False)

      def on_confirm():
        ui_state.params.put_bool("ExperimentalModeConfirmed", True)
        ui_state.params.put_bool("ExperimentalMode", True)
        self._experimental_btn.set_checked(True)

      gui_app.push_widget(ExperimentalModeConfirmPage(on_confirm))
    else:
      ui_state.params.put_bool("ExperimentalMode", state)
