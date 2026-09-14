from collections.abc import Callable

from cereal import log
from openpilot.common.params import Params
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle, BigButton, BigToggle
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.selfdrive.ui.layouts.settings.common import (
  lane_color_label, next_lane_color, set_lane_color,
  onroad_ui_label, next_onroad_ui, set_onroad_ui, restart_needed_callback,
  compass_size_label, next_compass_size, set_compass_size,
  delorean_on, set_delorean, request_delorean_play,
  s3xy_get_bool, s3xy_put_bool,
)
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


class _ParamCycle(BigButton):
  def __init__(self, title: str, label_fn, next_fn, apply_fn):
    super().__init__(title, "")
    self._params = Params()
    self._label_fn = label_fn
    self._next_fn = next_fn
    self._apply_fn = apply_fn
    self.refresh()

  def refresh(self):
    value = self._label_fn(self._params)
    if value != self.value:
      self.set_value(value)

  def show_event(self):
    super().show_event()
    self.refresh()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    nxt = self._next_fn(self._params)
    self._apply_fn(nxt, self._params)
    self.refresh()


class OnroadUiCycle(_ParamCycle):
  def __init__(self):
    super().__init__(
      "onroad UI", onroad_ui_label, next_onroad_ui,
      lambda nxt, p: set_onroad_ui(nxt, p),
    )

class CompassSizeCycle(_ParamCycle):
  def __init__(self):
    super().__init__(
      "compass size", compass_size_label, next_compass_size,
      lambda nxt, p: set_compass_size(nxt, p),
    )


class LaneColorCycle(_ParamCycle):
  def __init__(self):
    super().__init__(
      "theme", lane_color_label, next_lane_color,
      lambda nxt, p: set_lane_color(nxt, p),
    )


class S3xyBoolControl(BigToggle):
  """Bool toggle for Highland keys missing from stock params_pyx.so."""

  def __init__(self, text: str, key: str, default: bool = False, toggle_callback=None):
    self._s3xy_key = key
    self._s3xy_default = default
    super().__init__(text, "", initial_state=s3xy_get_bool(key, default), toggle_callback=toggle_callback)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    s3xy_put_bool(self._s3xy_key, self._checked)

  def refresh(self):
    self.set_checked(s3xy_get_bool(self._s3xy_key, self._s3xy_default))


class DeloreanCycle(BigButton):
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


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"])
    self._experimental_btn = BigParamControl("experimental mode", "ExperimentalMode")
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM")
    record_front = BigParamControl("record & upload driver camera", "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl("enable openpilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)
    alc = S3xyBoolControl("auto lane change", "AutoLaneChangeEnabled", False)

    self._scroller.add_widgets([
      self._personality_toggle,
      self._experimental_btn,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
      record_mic,
      enable_openpilot,
      alc,
    ])

    # Toggle lists
    self._refresh_toggles = (
      ("ExperimentalMode", self._experimental_btn),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
      ("AutoLaneChangeEnabled", alc),
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
      if hasattr(item, "refresh") and key == "AutoLaneChangeEnabled":
        item.refresh()
      else:
        item.set_checked(ui_state.params.get_bool(key))
