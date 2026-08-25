from openpilot.cereal import log
from openpilot.common.params import Params, UnknownKeyName
from openpilot.selfdrive.ui.layouts.settings.common import (
  lane_color_label, next_lane_color, onroad_ui_label, next_onroad_ui, set_onroad_ui,
  compass_size_label, next_compass_size,
)
from openpilot.selfdrive.weather_news import config as grok_cfg
from openpilot.selfdrive.weather_news import grok as grok_api
from openpilot.selfdrive.weather_news import mode as wx
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import multiple_button_item, toggle_item, button_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants

# Description constants
DESCRIPTIONS = {
  "OpenpilotEnabledToggle": tr_noop(
    "Use the openpilot system for adaptive cruise control and lane keep driver assistance. " +
    "Your attention is required at all times to use this feature."
  ),
  "DisengageOnAccelerator": tr_noop("When enabled, pressing the accelerator pedal will disengage openpilot."),
  "LongitudinalPersonality": tr_noop(
    "Standard is recommended. In aggressive mode, openpilot will follow lead cars closer and be more aggressive with the gas and brake. " +
    "In relaxed mode openpilot will stay further away from lead cars. On supported cars, you can cycle through these personalities with " +
    "your steering wheel distance button."
  ),
  "AutoLaneChangeEnabled": tr_noop(
    "Auto Lane Change uses Tesla's built-in blind spot monitoring to check for a vehicle in the adjacent lane prior to merging. " +
    "You are still responsible for ensuring the lane of travel is clear and agree to intervene as necessary. " +
    "When off, a steering-wheel nudge is required (stock openpilot). Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot)."
  ),
  "LaneColor": tr_noop(
    "Theme. Color of the engaged lane lines. Tesla blue matches Autopilot visualization. Comma green is default openpilot. Applied in custom onroad UI."
  ),
  "CustomOnroadUi": tr_noop(
    "Stock UI is comma's onroad HUD. Custom UI is this fork's onroad overlays, starting with a compass heading."
  ),
  "CompassSize": tr_noop(
    "Theme. Custom onroad compass: small (left, hides with MAX) or large (top-right, stays engaged)."
  ),
  "WeatherNewsMode": tr_noop(
    "Local forecast plus news, spoken by Grok Ara. Off, Nice, or Unhinged. Unhinged is NSFW — not for kids."
  ),
  "WeatherNewsSchedule": tr_noop(
    "3x a day plays once in the morning, once in the afternoon, and once after 7pm. Missed windows stay missed — never stacked. Every drive plays at the start of each onroad session."
  ),
  "WeatherNewsPlayback": tr_noop(
    "Voice-only. Standard is clean. Boosted is louder for road noise, with less speaker crackle."
  ),
  "GrokVoice": tr_noop(
    "Grok Ara for weather and news. Nice and Unhinged share Ara. Scan the QR to paste your xAI API key on the LAN console."
  ),
  "IsLdwEnabled": tr_noop(
    "Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line " +
    "without a turn signal activated while driving over 31 mph (50 km/h)."
  ),
  "AlwaysOnDM": tr_noop("Enable driver monitoring even when openpilot is not engaged."),
  'RecordFront': tr_noop("Upload data from the cabin camera and help improve the driver monitoring algorithm."),
  "IsMetric": tr_noop("Display speed in km/h instead of mph."),
  "RecordAudio": tr_noop("Record and store microphone audio while driving. The audio will be included in the dashcam video in comma connect."),
}


class TogglesLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = self._params.get_bool("IsReleaseBranch")

    # param, title, desc, icon, needs_restart
    self._toggle_defs = {
      "OpenpilotEnabledToggle": (
        lambda: tr("Enable openpilot"),
        DESCRIPTIONS["OpenpilotEnabledToggle"],
        "chffr_wheel.png",
        True,
      ),
      "ExperimentalMode": (
        lambda: tr("Experimental Mode"),
        "",
        "experimental_white.png",
        False,
      ),
      "DisengageOnAccelerator": (
        lambda: tr("Disengage on Accelerator Pedal"),
        DESCRIPTIONS["DisengageOnAccelerator"],
        "disengage_on_accelerator.png",
        False,
      ),
      "AutoLaneChangeEnabled": (
        lambda: tr("Auto Lane Change"),
        DESCRIPTIONS["AutoLaneChangeEnabled"],
        "warning.png",
        False,
      ),
      "IsLdwEnabled": (
        lambda: tr("Enable Lane Departure Warnings"),
        DESCRIPTIONS["IsLdwEnabled"],
        "warning.png",
        False,
      ),
      "AlwaysOnDM": (
        lambda: tr("Always-On Driver Monitoring"),
        DESCRIPTIONS["AlwaysOnDM"],
        "monitoring.png",
        False,
      ),
      "RecordFront": (
        lambda: tr("Record and Upload Cabin Camera"),
        DESCRIPTIONS["RecordFront"],
        "monitoring.png",
        True,
      ),
      "RecordAudio": (
        lambda: tr("Record and Upload Microphone Audio"),
        DESCRIPTIONS["RecordAudio"],
        "microphone.png",
        True,
      ),
      "IsMetric": (
        lambda: tr("Use Metric System"),
        DESCRIPTIONS["IsMetric"],
        "metric.png",
        False,
      ),
    }

    self._long_personality_setting = multiple_button_item(
      lambda: tr("Driving Personality"),
      lambda: tr(DESCRIPTIONS["LongitudinalPersonality"]),
      buttons=[lambda: tr("Aggressive"), lambda: tr("Standard"), lambda: tr("Relaxed")],
      button_width=255,
      callback=self._set_longitudinal_personality,
      selected_index=self._params.get("LongitudinalPersonality", return_default=True),
      icon="speed_limit.png"
    )

    self._onroad_ui_setting = button_item(
      lambda: tr("Theme: Onroad UI"),
      lambda: tr(onroad_ui_label(self._params)),
      description=lambda: tr(DESCRIPTIONS["CustomOnroadUi"]),
      callback=self._cycle_onroad_ui,
    )

    self._lane_color_setting = button_item(
      lambda: tr("Theme: Lane Color"),
      lambda: tr(lane_color_label(self._params)),
      description=lambda: tr(DESCRIPTIONS["LaneColor"]),
      callback=self._cycle_lane_color,
    )

    self._compass_size_setting = button_item(
      lambda: tr("Theme: Compass Size"),
      lambda: tr(compass_size_label(self._params)),
      description=lambda: tr(DESCRIPTIONS["CompassSize"]),
      callback=self._cycle_compass_size,
    )

    self._weather_mode_setting = multiple_button_item(
      lambda: tr("Theme: Weather & News"),
      lambda: tr(DESCRIPTIONS["WeatherNewsMode"]),
      buttons=[lambda: tr("Off"), lambda: tr("Nice"), lambda: tr("Unhinged")],
      button_width=220,
      callback=self._set_weather_news_mode,
      selected_index=wx.get(self._params),
      icon="speed_limit.png",
    )

    self._grok_voice_setting = button_item(
      lambda: tr("Theme: Grok Voice"),
      lambda: tr("On" if grok_cfg.voice_enabled() else "Off"),
      description=lambda: tr(DESCRIPTIONS["GrokVoice"]),
      callback=self._toggle_grok_voice,
    )

    self._grok_qr_setting = button_item(
      lambda: tr("Theme: Grok Setup"),
      lambda: tr("Show QR"),
      description=lambda: tr("Scan to open the LAN console and paste your xAI API key."),
      callback=self._show_grok_qr,
      enabled=lambda: grok_cfg.voice_enabled(),
    )

    self._weather_preview_setting = button_item(
      lambda: tr("Theme: Weather Preview"),
      lambda: tr("Preview"),
      description=lambda: tr("Plays Nice or Unhinged through Ara. Enable Grok voice first."),
      callback=self._preview_weather_news,
      enabled=lambda: wx.get(self._params) != wx.OFF and grok_cfg.voice_enabled(),
    )

    self._weather_schedule_setting = button_item(
      lambda: tr("Theme: Briefing Schedule"),
      lambda: tr("Every drive" if grok_cfg.every_drive() else "3x a day"),
      description=lambda: tr(DESCRIPTIONS["WeatherNewsSchedule"]),
      callback=self._toggle_weather_schedule,
    )

    self._weather_playback_setting = multiple_button_item(
      lambda: tr("Theme: Briefing Playback"),
      lambda: tr(DESCRIPTIONS["WeatherNewsPlayback"]),
      buttons=[lambda: tr("Standard"), lambda: tr("Boosted")],
      button_width=255,
      callback=self._set_weather_playback,
      selected_index=1 if grok_cfg.playback_boosted() else 0,
      icon="speed_limit.png",
    )

    self._toggles = {}
    self._locked_toggles = set()
    for param, (title, desc, icon, needs_restart) in self._toggle_defs.items():
      toggle = toggle_item(
        title,
        desc,
        self._params.get_bool(param),
        callback=lambda state, p=param: self._toggle_callback(state, p),
        icon=icon,
      )

      try:
        locked = self._params.get_bool(param + "Lock")
      except UnknownKeyName:
        locked = False
      toggle.action_item.set_enabled(not locked)

      # Make description callable for live translation
      additional_desc = ""
      if needs_restart and not locked:
        additional_desc = tr("Changing this setting will restart openpilot if the car is powered on.")
      toggle.set_description(lambda og_desc=toggle.description, add_desc=additional_desc: tr(og_desc) + (" " + tr(add_desc) if add_desc else ""))

      # track for engaged state updates
      if locked:
        self._locked_toggles.add(param)

      self._toggles[param] = toggle

      # insert longitudinal personality + ALC cycle after NDOG toggle
      if param == "DisengageOnAccelerator":
        self._toggles["LongitudinalPersonality"] = self._long_personality_setting
        self._toggles["CustomOnroadUi"] = self._onroad_ui_setting
        self._toggles["LaneColor"] = self._lane_color_setting
        self._toggles["CompassSize"] = self._compass_size_setting
        self._toggles["WeatherNewsMode"] = self._weather_mode_setting
        self._toggles["GrokVoice"] = self._grok_voice_setting
        self._toggles["GrokQr"] = self._grok_qr_setting
        self._toggles["WeatherNewsPreview"] = self._weather_preview_setting
        self._toggles["WeatherNewsPlayback"] = self._weather_playback_setting
        self._toggles["WeatherNewsSchedule"] = self._weather_schedule_setting

    self._update_experimental_mode_icon()
    self._scroller = Scroller(list(self._toggles.values()), line_separator=True, spacing=0)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._long_personality_setting.action_item.set_selected_button(personality)
      ui_state.personality = personality
    st = wx.status_text(self._params)
    grok_on = grok_cfg.voice_enabled()
    if getattr(self, "_wx_st", None) != (st, grok_on):
      self._wx_st = (st, grok_on)
      self._weather_preview_setting.action_item.set_text(lambda s=st: tr(s) if s else tr("Preview"))
      self._weather_preview_setting.action_item.set_enabled(
        lambda: wx.get(self._params) != wx.OFF and grok_cfg.voice_enabled() and not wx.status_text(self._params)
      )
      self._grok_voice_setting.action_item.set_text(lambda: tr("On" if grok_cfg.voice_enabled() else "Off"))
      self._grok_qr_setting.action_item.set_enabled(lambda: grok_cfg.voice_enabled())

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    e2e_description = tr(
      "openpilot defaults to driving in chill mode. Experimental mode enables alpha-level features that aren't ready for chill mode. " +
      "Experimental features are listed below:<br>" +
      "<h4>End-to-End Longitudinal Control</h4><br>" +
      "Let the driving model control the gas and brakes. openpilot will drive as it thinks a human would, including stopping for red lights and stop signs. " +
      "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; " +
      "mistakes should be expected.<br>" +
      "<h4>New Driving Visualization</h4><br>" +
      "The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. " +
      "The Experimental mode logo will also be shown in the top right corner."
    )

    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._toggles["ExperimentalMode"].action_item.set_enabled(True)
        self._toggles["ExperimentalMode"].set_description(e2e_description)
        self._long_personality_setting.action_item.set_enabled(True)
      else:
        # no long for now
        self._toggles["ExperimentalMode"].action_item.set_enabled(False)
        self._toggles["ExperimentalMode"].action_item.set_state(False)
        self._long_personality_setting.action_item.set_enabled(False)
        self._params.remove("ExperimentalMode")

        unavailable = tr("Experimental mode is currently unavailable on this car since the car's stock ACC is used for longitudinal control.")

        long_desc = unavailable + " " + tr("openpilot longitudinal control may come in a future update.")
        if ui_state.CP.alphaLongitudinalAvailable:
          if self._is_release:
            long_desc = unavailable + " " + tr("An alpha version of openpilot longitudinal control can be tested, along with " +
                                               "Experimental mode, on non-release branches.")
          else:
            long_desc = tr("Enable the openpilot longitudinal control (alpha) toggle to allow Experimental mode.")

        self._toggles["ExperimentalMode"].set_description("<b>" + long_desc + "</b><br><br>" + e2e_description)
    else:
      self._toggles["ExperimentalMode"].set_description(e2e_description)

    self._update_experimental_mode_icon()

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for param in self._toggle_defs:
      self._toggles[param].action_item.set_state(self._params.get_bool(param))

    # these toggles need restart, block while engaged
    for toggle_def in self._toggle_defs:
      if self._toggle_defs[toggle_def][3] and toggle_def not in self._locked_toggles:
        self._toggles[toggle_def].action_item.set_enabled(not ui_state.engaged)

    self._onroad_ui_setting.action_item.set_text(lambda: tr(onroad_ui_label(self._params)))
    self._lane_color_setting.action_item.set_text(lambda: tr(lane_color_label(self._params)))
    self._compass_size_setting.action_item.set_text(lambda: tr(compass_size_label(self._params)))
    self._weather_mode_setting.action_item.set_selected_button(wx.get(self._params))
    self._weather_schedule_setting.action_item.set_text(
      lambda: tr("Every drive" if grok_cfg.every_drive() else "3x a day")
    )
    self._weather_playback_setting.action_item.set_selected_button(1 if grok_cfg.playback_boosted() else 0)
    st = wx.status_text(self._params)
    self._weather_preview_setting.action_item.set_text(lambda s=st: tr(s) if s else tr("Preview"))
    self._weather_preview_setting.action_item.set_enabled(
      lambda: wx.get(self._params) != wx.OFF and grok_cfg.voice_enabled() and not wx.status_text(self._params)
    )

  def _render(self, rect):
    self._scroller.render(rect)

  def _update_experimental_mode_icon(self):
    icon = "experimental.png" if self._toggles["ExperimentalMode"].action_item.get_state() else "experimental_white.png"
    self._toggles["ExperimentalMode"].set_icon(icon)

  def _handle_experimental_mode_toggle(self, state: bool):
    confirmed = self._params.get_bool("ExperimentalModeConfirmed")
    if state and not confirmed:
      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("ExperimentalMode", True, block=True)
          self._params.put_bool("ExperimentalModeConfirmed", True, block=True)
        else:
          self._toggles["ExperimentalMode"].action_item.set_state(False)
        self._update_experimental_mode_icon()

      # show confirmation dialog
      content = (f"<h1>{self._toggles['ExperimentalMode'].title}</h1><br>" +
                 f"<p>{self._toggles['ExperimentalMode'].description}</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)
    else:
      self._update_experimental_mode_icon()
      self._params.put_bool("ExperimentalMode", state, block=True)

  def _toggle_callback(self, state: bool, param: str):
    if param == "ExperimentalMode":
      self._handle_experimental_mode_toggle(state)
      return
    if param == "AutoLaneChangeEnabled":
      self._handle_alc_toggle(state)
      return

    self._params.put_bool(param, state, block=True)
    if self._toggle_defs[param][3]:
      self._params.put_bool("OnroadCycleRequested", True, block=True)

  def _handle_alc_toggle(self, state: bool):
    if state:
      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("AutoLaneChangeEnabled", True, block=True)
        else:
          self._toggles["AutoLaneChangeEnabled"].action_item.set_state(False)

      content = (f"<h1>{tr('Auto Lane Change')}</h1><br>" +
                 f"<p>{tr(DESCRIPTIONS['AutoLaneChangeEnabled'])}</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)
    else:
      self._params.put_bool("AutoLaneChangeEnabled", False, block=True)

  def _set_longitudinal_personality(self, button_index: int):
    self._params.put("LongitudinalPersonality", button_index, block=True)

  def _cycle_onroad_ui(self):
    nxt = next_onroad_ui(self._params)
    set_onroad_ui(nxt, self._params)
    self._onroad_ui_setting.action_item.set_text(lambda: tr(onroad_ui_label(self._params)))

  def _cycle_lane_color(self):
    nxt = next_lane_color(self._params)
    self._params.put("LaneColor", nxt, block=True)
    self._lane_color_setting.action_item.set_text(lambda: tr(lane_color_label(self._params)))

  def _cycle_compass_size(self):
    nxt = next_compass_size(self._params)
    self._params.put("CompassSize", nxt, block=True)
    self._compass_size_setting.action_item.set_text(lambda: tr(compass_size_label(self._params)))

  def _toggle_grok_voice(self):
    grok_cfg.set_voice_enabled(not grok_cfg.voice_enabled())
    self._grok_voice_setting.action_item.set_text(lambda: tr("On" if grok_cfg.voice_enabled() else "Off"))
    self._grok_qr_setting.action_item.set_enabled(lambda: grok_cfg.voice_enabled())
    self._weather_preview_setting.action_item.set_enabled(
      lambda: wx.get(self._params) != wx.OFF and grok_cfg.voice_enabled()
    )

  def _show_grok_qr(self):
    dlg = ConfirmDialog(
      f"<h1>Grok setup</h1><p>On this network open:</p><p><b>{grok_api.console_url('/grok')}</b></p>",
      tr("OK"), rich=True,
    )
    gui_app.push_widget(dlg)

  def _set_weather_news_mode(self, button_index: int):
    if button_index == wx.AGGRESSIVE and wx.get(self._params) != wx.AGGRESSIVE:
      self._weather_mode_setting.action_item.set_selected_button(wx.get(self._params))

      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          wx.set(wx.AGGRESSIVE, self._params)
          self._weather_mode_setting.action_item.set_selected_button(wx.AGGRESSIVE)
          self._weather_preview_setting.action_item.set_enabled(lambda: True)
        else:
          self._weather_mode_setting.action_item.set_selected_button(wx.get(self._params))

      content = ("<h1>NSFW — Unhinged</h1>"
                 "<p>Explicit language through the speaker. Not for kids. "
                 "Not for passengers who didn't ask.</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)
      return
    wx.set(button_index, self._params)
    self._weather_preview_setting.action_item.set_enabled(lambda: wx.get(self._params) != wx.OFF)

  def _preview_weather_news(self):
    wx.request_preview(self._params)

  def _toggle_weather_schedule(self):
    grok_cfg.set_every_drive(not grok_cfg.every_drive())
    self._weather_schedule_setting.action_item.set_text(
      lambda: tr("Every drive" if grok_cfg.every_drive() else "3x a day")
    )

  def _set_weather_playback(self, button_index: int):
    grok_cfg.set_playback(grok_cfg.PLAYBACK_BOOSTED if button_index == 1 else grok_cfg.PLAYBACK_STANDARD)
