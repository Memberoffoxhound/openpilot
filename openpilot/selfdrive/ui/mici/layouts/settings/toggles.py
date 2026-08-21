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
  LANE_COLOR_LABELS, ONROAD_UI_LABELS, lane_color_label, next_lane_color,
  onroad_ui_label, next_onroad_ui, set_onroad_ui, restart_needed_callback,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.webrtc.helpers import on_air_block_reason

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
ON_AIR_SLASH = rl.Color(224, 36, 36, 255)
ON_AIR_SLASH_EDGE = rl.Color(255, 255, 255, 235)


def _network_is_none() -> bool:
  try:
    return ui_state.sm["deviceState"].networkType == log.DeviceState.NetworkType.none
  except Exception:
    return True


def on_air_ui_blocked() -> str | None:
  return on_air_block_reason(ui_state.params, network_none=_network_is_none())


def draw_on_air_slash(x: float, y: float, w: float, h: float) -> None:
  inset = max(4.0, min(w, h) * 0.14)
  p1 = rl.Vector2(x + inset, y + inset)
  p2 = rl.Vector2(x + w - inset, y + h - inset)
  rl.draw_line_ex(p1, p2, max(5.0, h * 0.14), ON_AIR_SLASH_EDGE)
  rl.draw_line_ex(p1, p2, max(3.5, h * 0.09), ON_AIR_SLASH)


def try_toggle_on_air() -> None:
  params = ui_state.params
  want_on = not params.get_bool("LivestreamEnabled")
  if want_on:
    reason = on_air_ui_blocked()
    if reason:
      gui_app.push_widget(OnAirBlockedPage(reason))
      return
  params.put_bool("LivestreamEnabled", want_on, block=True)


class OnAirBlockedPage(NavScroller):
  def __init__(self, reason: str):
    super().__init__()
    warn = gui_app.texture("icons_mici/setup/warning.png", 64, 64)
    if reason == "prime":
      cards = [
        GreyBigButton("On-Air", "comma Prime LTE", warn),
        GreyBigButton("", "You think Hotz wants to pay for your influence?"),
        GreyBigButton("", "Get yer own connection!"),
      ]
    else:
      cards = [
        GreyBigButton("On-Air", "no internet connection", warn),
      ]
    self._scroller.add_widgets(cards)


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


class LaneColorCycle(BigButton):
  """Tap to cycle tesla blue / comma green. Applied in custom onroad UI."""

  def __init__(self):
    super().__init__("lane color", "")
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


class OnAirToggle(Widget):
  """Red On-Air = livestream on. Gray = stock Connect only."""

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._on = gui_app.texture("icons_mici/on_air_on.png", 280, 112)
    self._off = gui_app.texture("icons_mici/on_air_off.png", 280, 112)
    self.set_rect(rl.Rectangle(0, 0, 220, 180))
    self.set_click_callback(self._toggle)

  def _toggle(self):
    try_toggle_on_air()

  def _render(self, _):
    txt = self._on if self._params.get_bool("LivestreamEnabled") else self._off
    max_w = max(40.0, self.rect.width - 24)
    scale = min(1.0, max_w / max(1, txt.width))
    w, h = txt.width * scale, txt.height * scale
    x = self.rect.x + (self.rect.width - w) / 2
    y = self.rect.y + (self.rect.height - h) / 2
    src = rl.Rectangle(0, 0, txt.width, txt.height)
    dest = rl.Rectangle(x, y, w, h)
    rl.draw_texture_pro(txt, src, dest, rl.Vector2(0, 0), 0.0, rl.WHITE)
    if on_air_ui_blocked():
      draw_on_air_slash(x, y, w, h)


class LivestreamLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._scroller.add_widgets([
      OnAirToggle(),
      GreyBigButton("", "Local Wi-Fi viewer · 720p WebRTC.\nPhone: port 5001. Not comma's servers."),
    ])


class ThemeLayoutMici(NavScroller):
  """Settings → theme. Subsections live here."""

  def __init__(self):
    super().__init__()
    self._onroad_ui = OnroadUiCycle()
    self._lane_color = LaneColorCycle()
    self._scroller.add_widgets([self._onroad_ui, self._lane_color])


class ExperimentalModeConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()

    accept = BigConfirmationCircleButton("enable\nexperimental mode",
                                         gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                         lambda: self.dismiss(on_confirm))

    self._scroller.add_widgets([
      GreyBigButton("enabling\nexperimental mode", "scroll to continue",
                    gui_app.texture("icons_mici/setup/warning.png", 64, 64)),
      GreyBigButton("", "openpilot defaults to driving in chill mode."),
      GreyBigButton("", "Experimental mode enables alpha-level features that aren't ready for chill mode."),
      GreyBigButton("End-to-End Longitudinal Control"),
      GreyBigButton("", "Let the driving model control the gas and brakes."),
      GreyBigButton("", "openpilot will drive as it thinks a human would, including stopping for red lights and stop signs."),
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
    self._alc_btn = BigToggle("auto lane change", initial_state=ui_state.params.get_bool("AutoLaneChangeEnabled"),
                             toggle_callback=self._on_alc)
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM")
    record_front = BigParamControl("record & upload cabin camera", "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl("enable openpilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)

    self._scroller.add_widgets([
      self._alc_btn,
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
