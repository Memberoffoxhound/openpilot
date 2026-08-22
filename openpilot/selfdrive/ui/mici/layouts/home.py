import datetime
import json
import time

from openpilot.cereal import log
import pyray as rl
from collections.abc import Callable
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.layouts import HBoxLayout
from openpilot.system.ui.widgets.icon_widget import IconWidget
from openpilot.system.ui.widgets.label import UnifiedLabel, gui_label
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_SCALE
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.mici.layouts.settings.toggles import (
  draw_on_air_slash, on_air_ui_blocked, try_toggle_on_air,
)
from openpilot.common.version import RELEASE_BRANCHES

HEAD_BUTTON_FONT_SIZE = 40
HOME_PADDING = 8
ALERTS_ZONE_WIDTH = 180
TRIP_PATH = "/data/trip_meter.json"
WORDMARK_SIZE = 80
LABEL_WHITE = rl.Color(255, 255, 255, int(255 * 0.9))


def _glyph_ink(font: rl.Font, ch: str, font_size: int) -> tuple[float, float, float, float, float]:
  """offsetX, offsetY, width, height, advance — pixels at the drawn size."""
  scale = (font_size * FONT_SCALE) / float(font.baseSize)
  idx = rl.get_glyph_index(font, ord(ch))
  g = font.glyphs[idx]
  rec = font.recs[idx]
  return g.offsetX * scale, g.offsetY * scale, rec.width * scale, rec.height * scale, g.advanceX * scale


def draw_tesla_three(x: float, y: float, w: float, h: float, color: rl.Color) -> float:
  """Tesla E: three equal stadiums. Slight inverted-trapezoid via pill ends."""
  bar_h = max(3.0, h * 0.26)
  gap = max(2.0, (h - 3 * bar_h) / 2.0)
  for i in range(3):
    rl.draw_rectangle_rounded(rl.Rectangle(x, y + i * (bar_h + gap), w, bar_h), 0.85, 8, color)
  return w

NetworkType = log.DeviceState.NetworkType

NETWORK_TYPES = {
  NetworkType.none: "Offline",
  NetworkType.wifi: "WiFi",
  NetworkType.cell2G: "2G",
  NetworkType.cell3G: "3G",
  NetworkType.cell4G: "LTE",
  NetworkType.cell5G: "5G",
  NetworkType.ethernet: "Ethernet",
}


class AlertsPill(Widget):
  ICON_OFFSET = 12
  COUNT_OFFSET = 40

  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 104, 52))

    self._pill_bg_txt = gui_app.texture("icons_mici/alerts_pill.png", 104, 52)
    self._icon_red = gui_app.texture("icons_mici/offroad_alerts/red_warning.png", 36, 36)
    self._icon_orange = gui_app.texture("icons_mici/offroad_alerts/orange_warning.png", 36, 36)
    self._icon_green = gui_app.texture("icons_mici/offroad_alerts/green_wheel.png", 36, 36)
    self._alert_count_callback: Callable[[], int] | None = None
    self._max_severity_callback: Callable[[], int | None] | None = None

  def set_alert_count_callback(self, callback: Callable[[], int] | None,
                               severity_callback: Callable[[], int | None] | None = None):
    self._alert_count_callback = callback
    self._max_severity_callback = severity_callback

  def _render(self, _):
    alert_count = self._alert_count_callback() if self._alert_count_callback else 0
    if alert_count > 0:
      pill_w, pill_h = self._pill_bg_txt.width, self._pill_bg_txt.height
      rl.draw_texture_ex(self._pill_bg_txt, rl.Vector2(self.rect.x, self.rect.y), 0.0, 1.0, rl.WHITE)

      severity = self._max_severity_callback() if self._max_severity_callback else None
      if severity == -1:
        warning_txt = self._icon_green
      elif severity is not None and severity > 0:
        warning_txt = self._icon_red
      else:
        warning_txt = self._icon_orange

      warn_x = self.rect.x + self.ICON_OFFSET
      warn_y = self.rect.y + (pill_h - warning_txt.height) / 2
      rl.draw_texture_ex(warning_txt, rl.Vector2(warn_x, warn_y), 0.0, 1.0, rl.WHITE)

      count_rect = rl.Rectangle(self.rect.x + self.COUNT_OFFSET, self.rect.y, pill_w - self.COUNT_OFFSET, pill_h)
      gui_label(count_rect, str(alert_count), font_size=36,
                alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)


class NetworkIcon(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 54, 44))  # max size of all icons
    self._net_type = NetworkType.none
    self._net_strength = 0

    self._wifi_slash_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_slash.png", 50, 44)
    self._wifi_none_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_none.png", 50, 37)
    self._wifi_low_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_low.png", 50, 37)
    self._wifi_medium_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_medium.png", 50, 37)
    self._wifi_full_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_full.png", 50, 37)

    self._cell_none_txt = gui_app.texture("icons_mici/settings/network/cell_strength_none.png", 54, 36)
    self._cell_low_txt = gui_app.texture("icons_mici/settings/network/cell_strength_low.png", 54, 36)
    self._cell_medium_txt = gui_app.texture("icons_mici/settings/network/cell_strength_medium.png", 54, 36)
    self._cell_high_txt = gui_app.texture("icons_mici/settings/network/cell_strength_high.png", 54, 36)
    self._cell_full_txt = gui_app.texture("icons_mici/settings/network/cell_strength_full.png", 54, 36)

  def _update_state(self):
    device_state = ui_state.sm['deviceState']
    self._net_type = device_state.networkType
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _render(self, _):
    if self._net_type == NetworkType.wifi:
      # There is no 1
      draw_net_txt = {0: self._wifi_none_txt,
                      2: self._wifi_low_txt,
                      3: self._wifi_medium_txt,
                      4: self._wifi_full_txt,
                      5: self._wifi_full_txt}.get(self._net_strength, self._wifi_low_txt)
    elif self._net_type in (NetworkType.cell2G, NetworkType.cell3G, NetworkType.cell4G, NetworkType.cell5G):
      draw_net_txt = {0: self._cell_none_txt,
                      2: self._cell_low_txt,
                      3: self._cell_medium_txt,
                      4: self._cell_high_txt,
                      5: self._cell_full_txt}.get(self._net_strength, self._cell_none_txt)
    else:
      draw_net_txt = self._wifi_slash_txt

    draw_x = self._rect.x + (self._rect.width - draw_net_txt.width) / 2
    draw_y = self._rect.y + (self._rect.height - draw_net_txt.height) / 2

    if draw_net_txt == self._wifi_slash_txt:
      # Offset by difference in height between slashless and slash icons to make center align match
      draw_y -= (self._wifi_slash_txt.height - self._wifi_none_txt.height) / 2

    rl.draw_texture_ex(draw_net_txt, rl.Vector2(draw_x, draw_y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * 0.9)))


class OnAirIcon(Widget):
  """Home footer On-Air badge. Red = on, gray = off. Tap handled by MiciHomeLayout."""

  def __init__(self):
    super().__init__()
    self._on = gui_app.texture("icons_mici/on_air_on.png", 120, 48)
    self._off = gui_app.texture("icons_mici/on_air_off.png", 120, 48)
    self.set_rect(rl.Rectangle(0, 0, 120, 48))
    self.set_enabled(False)

  def _render(self, _):
    txt = self._on if ui_state.params.get_bool("LivestreamEnabled") else self._off
    y = self.rect.y + (self.rect.height - txt.height) / 2
    x = self.rect.x
    rl.draw_texture_ex(txt, rl.Vector2(x, y), 0.0, 1.0, rl.WHITE)
    if on_air_ui_blocked():
      draw_on_air_slash(x, y, txt.width, txt.height)


class MiciHomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self._on_settings_click: Callable | None = None
    self._on_alerts_click: Callable | None = None
    self._alert_count_callback: Callable[[], int] | None = None

    self._mouse_down_t: None | float = None
    self._did_long_press = False
    self._is_pressed_prev = False

    self._version_text = self._get_version_text()

    self._experimental_icon = IconWidget("icons_mici/experimental_mode.png", (48, 48))
    self._on_air_icon = OnAirIcon()
    self._egpu_icon = IconWidget("icons_mici/egpu_green.png", (50, 37))
    self._egpu_icon_gray = IconWidget("icons_mici/egpu_gray.png", (50, 37))
    self._mic_icon = IconWidget("icons_mici/microphone.png", (32, 46))
    self._body_icon = IconWidget("icons_mici/body.png", (54, 37))

    self._alerts_pill = AlertsPill()

    self._status_bar_layout = HBoxLayout([
      IconWidget("icons_mici/settings.png", (48, 48), opacity=0.9),
      NetworkIcon(),
      self._experimental_icon,
      self._on_air_icon,
      self._egpu_icon,
      self._egpu_icon_gray,
      self._body_icon,
      self._mic_icon,
    ], spacing=18)

    self._version_label = UnifiedLabel("", font_size=36, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._large_version_label = UnifiedLabel("", font_size=64, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._date_label = UnifiedLabel("", font_size=36, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._branch_label = UnifiedLabel("", font_size=36, text_color=rl.GRAY, font_weight=FontWeight.ROMAN, scroll=True)
    self._trip_at = 0.0
    self._last_txt = ("Last ", "0 mi 0%")
    self._week_txt = ("Week ", "0 mi 0%")

  def _update_state(self):
    if self.is_pressed and not self._is_pressed_prev:
      self._mouse_down_t = time.monotonic()
    elif not self.is_pressed and self._is_pressed_prev:
      self._mouse_down_t = None
      self._did_long_press = False
    self._is_pressed_prev = self.is_pressed

    if self._mouse_down_t is not None:
      if time.monotonic() - self._mouse_down_t > 0.5:
        # long gating for experimental mode - only allow toggle if longitudinal control is available
        if ui_state.has_longitudinal_control and ui_state.experimental_mode_confirmed:
          ui_state.experimental_mode = not ui_state.experimental_mode
          ui_state.params.put("ExperimentalMode", ui_state.experimental_mode, block=True)
        self._mouse_down_t = None
        self._did_long_press = True

    self._refresh_trip()

  def _fmt_trip(self, meters: float, eng_m: float) -> str:
    if ui_state.is_metric:
      dist, unit = meters / 1000.0, "km"
    else:
      dist, unit = meters / 1609.344, "mi"
    pct = int(round(100.0 * eng_m / meters)) if meters > 1 else 0
    return f"{int(round(dist))} {unit} {pct}%"

  def _refresh_trip(self):
    now = time.monotonic()
    if now - self._trip_at < 1.0:
      return
    self._trip_at = now
    try:
      t = json.loads(open(TRIP_PATH).read())
    except Exception:
      t = {}
    if (t.get("trip_m") or 0) > 10:
      last = (t.get("trip_m", 0) or 0, t.get("eng_m", 0) or 0)
    else:
      last = (t.get("last_m", 0) or 0, t.get("last_eng_m", 0) or 0)
    self._last_txt = ("Last ", self._fmt_trip(*last))
    self._week_txt = ("Week ", self._fmt_trip(t.get("week_m", 0) or 0, t.get("week_eng_m", 0) or 0))

  def set_callbacks(self, on_settings: Callable | None = None, on_alerts: Callable | None = None,
                    alert_count_callback: Callable[[], int] | None = None,
                    max_severity_callback: Callable[[], int | None] | None = None):
    self._on_settings_click = on_settings
    self._on_alerts_click = on_alerts
    self._alert_count_callback = alert_count_callback
    self._alerts_pill.set_alert_count_callback(alert_count_callback, max_severity_callback)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if not self._did_long_press:
      r = self._on_air_icon.rect
      if r.x <= mouse_pos.x <= r.x + r.width and r.y <= mouse_pos.y <= r.y + r.height:
        try_toggle_on_air()
        return
      relative_x = mouse_pos.x - self.rect.x
      has_alerts = self._alert_count_callback and self._alert_count_callback() > 0
      if has_alerts and relative_x > self.rect.width - ALERTS_ZONE_WIDTH:
        if self._on_alerts_click:
          self._on_alerts_click()
      elif self._on_settings_click:
        self._on_settings_click()
    self._did_long_press = False

  def _get_version_text(self) -> tuple[str, str, str, str] | None:
    version = ui_state.params.get("Version")
    branch = ui_state.params.get("GitBranch")
    commit = ui_state.params.get("GitCommit")

    if not all((version, branch, commit)):
      return None

    commit_date_raw = ui_state.params.get("GitCommitDate")
    try:
      # GitCommitDate format from get_commit_date(): '%ct %ci' e.g. "'1708012345 2024-02-15 ...'"
      unix_ts = int(commit_date_raw.strip("'").split()[0])
      date_str = datetime.datetime.fromtimestamp(unix_ts).strftime("%b %d")
    except (ValueError, IndexError, TypeError, AttributeError):
      date_str = ""

    return version, branch, commit[:7], date_str

  def _render(self, _):
    # TODO: why is there extra space here to get it to be flush?
    text_pos = rl.Vector2(self.rect.x - 2 + HOME_PADDING, self.rect.y - 16)
    font = gui_app.font(FontWeight.DISPLAY)
    s_ox, s_oy, s_w, s_h, s_adv = _glyph_ink(font, "S", WORDMARK_SIZE)
    e_ox, _e_oy, e_w, _e_h, e_adv = _glyph_ink(font, "E", WORDMARK_SIZE)
    x_ox, _x_oy, _x_w, _x_h, _x_adv = _glyph_ink(font, "X", WORDMARK_SIZE)
    letter_gap = max(2.0, (s_adv + e_ox) - (s_ox + s_w))
    bar_w = max(e_w * 1.32, s_w * 0.98)
    rl.draw_text_ex(font, "S", text_pos, WORDMARK_SIZE, 0, LABEL_WHITE)
    gx = text_pos.x + s_ox + s_w + letter_gap
    draw_tesla_three(gx, text_pos.y + s_oy, bar_w, s_h, LABEL_WHITE)
    rl.draw_text_ex(font, "XYPILOT", rl.Vector2(gx + bar_w + letter_gap - x_ox, text_pos.y), WORDMARK_SIZE, 0, LABEL_WHITE)

    if self._version_text is not None:
      # release branch
      release_branch = self._version_text[1] in RELEASE_BRANCHES
      version_pos = rl.Rectangle(text_pos.x, text_pos.y + WORDMARK_SIZE + 16, 100, 44)
      self._version_label.set_text(self._version_text[0])
      self._version_label.set_position(version_pos.x, version_pos.y)
      self._version_label.render()

      self._date_label.set_text(" " + self._version_text[3])
      self._date_label.set_position(version_pos.x + self._version_label.text_width + 10, version_pos.y)
      self._date_label.render()

      self._branch_label.set_max_width(gui_app.width - self._version_label.text_width - self._date_label.text_width - 32)
      self._branch_label.set_text(" " + ("release" if release_branch else self._version_text[1]))
      self._branch_label.set_position(version_pos.x + self._version_label.text_width + self._date_label.text_width + 20, version_pos.y)
      self._branch_label.render()

      y2 = version_pos.y + self._date_label.font_size + 7
      f36 = gui_app.font(FontWeight.ROMAN)
      ll, lv = self._last_txt
      wl, wv = self._week_txt
      x = version_pos.x
      rl.draw_text_ex(f36, ll, rl.Vector2(x, y2), 36, 0, rl.GRAY)
      x += measure_text_cached(f36, ll, 36).x
      rl.draw_text_ex(f36, lv, rl.Vector2(x, y2), 36, 0, LABEL_WHITE)
      x += measure_text_cached(f36, lv, 36).x + 20
      rl.draw_text_ex(f36, wl, rl.Vector2(x, y2), 36, 0, rl.GRAY)
      x += measure_text_cached(f36, wl, 36).x
      rl.draw_text_ex(f36, wv, rl.Vector2(x, y2), 36, 0, LABEL_WHITE)

    # ***** Center-aligned bottom section icons *****
    self._experimental_icon.set_visible(ui_state.experimental_mode)
    self._egpu_icon.set_visible(ui_state.sm["deviceState"].chestnutPresent and ui_state.usbgpu_compiled)
    self._egpu_icon_gray.set_visible(ui_state.sm["deviceState"].chestnutPresent and not ui_state.usbgpu_compiled)
    self._mic_icon.set_visible(ui_state.recording_audio)
    self._body_icon.set_visible(bool(ui_state.is_body))

    footer_rect = rl.Rectangle(self.rect.x + HOME_PADDING, self.rect.y + self.rect.height - 48, self.rect.width - HOME_PADDING, 48)
    self._status_bar_layout.render(footer_rect)

    # TODO: add alignment to hboxlayout and add to there
    self._alerts_pill.set_position(self.rect.x + self.rect.width - self._alerts_pill.rect.width - HOME_PADDING,
                                   self.rect.y + self.rect.height - self._alerts_pill.rect.height)
    self._alerts_pill.render()
