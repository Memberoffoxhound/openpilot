from collections.abc import Callable

from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle, BigToggle, GreyBigButton, BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.selfdrive.ui.layouts.settings.common import (
  lane_color_label, next_lane_color,
  onroad_ui_label, next_onroad_ui, set_onroad_ui, restart_needed_callback,
  compass_size_label, next_compass_size,
  delorean_on, set_delorean, request_delorean_play,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.car import tesla_step_aside, park_offroad
from openpilot.selfdrive.ui.lib import drive_summary
from openpilot.selfdrive.ui.mici.layouts.settings.initial_cruise_speed import InitialCruiseSpeedButton

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


def _wire_confirm(page: NavScroller, title: str, bodies: list[str], on_confirm: Callable[[], None]) -> None:
  warn = gui_app.texture("icons_mici/setup/warning.png", 64, 64)
  check = gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64)
  accept = BigConfirmationCircleButton("slide to\nenable", check,
                                       lambda: page.dismiss(on_confirm))
  page._scroller.add_widgets([
    GreyBigButton(title, "scroll to continue", warn),
    *[GreyBigButton("", body) for body in bodies],
    accept,
  ])


class AutoLaneChangeConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    _wire_confirm(self, "enabling\nauto lane change", [
      "Auto Lane Change uses Tesla's stock blind spot monitoring",
      "to check for a vehicle in the adjacent lane prior to merging.",
      "You are still responsible for ensuring the lane of travel is clear",
      "and agree to intervene as necessary.",
    ], on_confirm)


class ParkOffroadConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    _wire_confirm(self, "enabling\ngo offroad in park", [
      "Tesla: TeslaPilot goes offroad after Park is held 3 s.",
      "Only D or R brings it back onroad, as a new route. The car staying on does not.",
      "Ignition starts TeslaPilot as before. Turning the car off and on resets it.",
      "Every Park splits the route. After D/R, TeslaPilot needs several seconds to be ready.",
      "Parked offroad with the car on, uploads and updates run as offroad.",
      "The shutdown timer starts only once the car powers off.",
      "Summon and Autopark keep it offroad, relay open. FSD from Park goes through step aside.",
      "Also turns on the drive summary card.",
    ], on_confirm)


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


class DeloreanPreview(BigButton):
  def __init__(self):
    super().__init__("delorean preview", "tap")

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    request_delorean_play()


class ThemeLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._scroller.add_widgets([
      _ParamCycle("onroad UI", onroad_ui_label, next_onroad_ui, set_onroad_ui),
      _ParamCycle("compass size", compass_size_label, next_compass_size, lambda nxt, p: p.put("CompassSize", nxt, block=True)),
      _ParamCycle("theme", lane_color_label, next_lane_color, lambda nxt, p: p.put("LaneColor", nxt, block=True)),
      _ParamCycle("delorean", lambda p: "on" if delorean_on() else "off", lambda p: not delorean_on(), lambda on, p: set_delorean(on)),
      DeloreanPreview(),
    ])


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle("following distance", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"],
                                                   description="Standard is recommended.\n" +
                                                               "Aggressive follows closer, with firmer gas and braking.\n" +
                                                               "Relaxed leaves more space.\n" +
                                                               "Use the steering wheel distance button on supported cars.")
    # Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot).
    self._alc_btn = BigToggle("auto lane change", initial_state=ui_state.params.get_bool("AutoLaneChangeEnabled"),
                             toggle_callback=self._on_alc)
    self._initial_cruise_speed = InitialCruiseSpeedButton()
    self._initial_cruise_speed.set_visible(lambda: ui_state.CP is not None and ui_state.has_longitudinal_control and not ui_state.CP.pcmCruise)
    is_metric_toggle = BigToggle("use metric units", initial_state=ui_state.params.get_bool("IsMetric"), toggle_callback=self._on_metric_toggle)
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled",
                                 description="Warn when you drift across a detected lane line.\n" +
                                             "Only above 31 mph (50 km/h), with no turn signal.")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM", description="Monitor the driver even when openpilot is not engaged.")
    record_front = BigParamControl("record & upload cabin camera", "RecordFront",
                                   description_icon=gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64),
                                   toggle_callback=restart_needed_callback, description="Upload cabin camera data to help improve driver monitoring.")
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", description_icon=gui_app.texture("icons_mici/microphone.png", 64, 64),
                                 toggle_callback=restart_needed_callback,
                                 description="Record microphone audio while driving.\n" +
                                             "Audio is included in dashcam videos in comma connect.")
    enable_openpilot = BigParamControl("enable TeslaPilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback,
                                       description="Enable to use TeslaPilot driver assistance.\n" +
                                                   "Disable to use your car's stock driver assistance.")

    # Tesla step-aside: default on. Tolerant params helpers, so a stale params library can't crash the UI.
    self._step_aside_btn = BigToggle("step aside for tesla fsd", initial_state=tesla_step_aside.enabled(ui_state.params),
                                     toggle_callback=self._on_step_aside,
                                     description="When Tesla Autosteer or FSD is selected or driving (or Summon),\n" +
                                                 "TeslaPilot steps aside: relay open, nothing sent,\n" +
                                                 "screen off after a 5 s alert. Back when Tesla is on TACC.")
    self._step_aside_btn.set_enabled(lambda: not ui_state.engaged)

    # Park-offroad + drive summary: one toggle, confirmation first
    self._park_offroad_btn = BigToggle("go offroad in park", initial_state=park_offroad.enabled(ui_state.params),
                                       toggle_callback=self._on_park_offroad,
                                       description="Offroad after Park is held 3 s, back onroad on D/R.\n" +
                                                   "Adds the drive summary card.")

    self._scroller.add_widgets([
      self._alc_btn,
      self._personality_toggle,
      self._initial_cruise_speed,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
      record_mic,
      self._step_aside_btn,
      self._park_offroad_btn,
      enable_openpilot,
    ])

    # Toggle lists
    self._refresh_toggles = (
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

  def _on_metric_toggle(self, state: bool):
    ui_state.params.put_bool("IsMetric", state, block=True)
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()
    self._initial_cruise_speed.refresh()

    if ui_state.CP is not None:
      self._personality_toggle.set_visible(ui_state.has_longitudinal_control)

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
    self._step_aside_btn.set_checked(tesla_step_aside.enabled(ui_state.params))
    self._park_offroad_btn.set_checked(park_offroad.enabled(ui_state.params))

  def _on_step_aside(self, state: bool):
    tesla_step_aside.put_bool(ui_state.params, tesla_step_aside.PARAM_ENABLED, state, block=True)
    restart_needed_callback()

  def _on_park_offroad(self, state: bool):
    def apply(on: bool):
      park_offroad.put_bool(ui_state.params, park_offroad.PARAM_ENABLED, on, block=True)
      drive_summary.put_bool(ui_state.params, drive_summary.PARAM_ENABLED, on)  # the summary rides on the same toggle
      self._park_offroad_btn.set_checked(on)

    if state:
      self._park_offroad_btn.set_checked(False)
      gui_app.push_widget(ParkOffroadConfirmPage(lambda: apply(True)))
    else:
      apply(False)

  def _on_alc(self, state: bool):
    if state:
      self._alc_btn.set_checked(False)

      def on_confirm():
        ui_state.params.put_bool("AutoLaneChangeEnabled", True, block=True)
        self._alc_btn.set_checked(True)

      gui_app.push_widget(AutoLaneChangeConfirmPage(on_confirm))
    else:
      ui_state.params.put_bool("AutoLaneChangeEnabled", False, block=True)
