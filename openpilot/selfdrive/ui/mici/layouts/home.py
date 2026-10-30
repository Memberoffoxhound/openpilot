from __future__ import annotations

import datetime
import math
import time

from openpilot.cereal import log
import pyray as rl
from collections.abc import Callable
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.layouts import HBoxLayout
from openpilot.system.ui.widgets.icon_widget import IconWidget
from openpilot.system.ui.widgets.label import UnifiedLabel, gui_label
from importlib.resources import as_file
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_DIR, TextAlignment, TextAlignmentVertical
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.ui_state import ui_state, ChestnutState
from openpilot.selfdrive.ui.layouts.settings.trip_stats import stats_view
from openpilot.selfdrive.ui.mici.widgets.trip_row import GREY, WHITE, draw_trip_row, fmt_trip
from openpilot.common.version import RELEASE_BRANCHES

HOME_PADDING = 8
ALERTS_ZONE_WIDTH = 180
MICI_WORDMARK_SIZE = 80


def _wordmark_font() -> rl.Font:
  """TeslaPilot wordmark glyphs from TESLA.ttf (T-E-S-L-A-P-I-L-O-T). Falls back to Inter DISPLAY."""
  try:
    chars = "TESLAPILOT"
    cps = sorted(map(ord, chars))
    buf = rl.ffi.new("int[]", cps)
    with as_file(FONT_DIR) as fs:
      font = rl.load_font_ex((fs / "TESLA.ttf").as_posix(), 200, rl.ffi.cast("int *", buf), len(cps))
    if font.glyphCount > 0:
      rl.gen_texture_mipmaps(font.texture)
      rl.set_texture_filter(font.texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
      return font
  except Exception:
    pass
  return gui_app.font(FontWeight.DISPLAY)


NetworkType = log.DeviceState.NetworkType

class AlertsPill(Widget):
  ICON_OFFSET = 12
  COUNT_OFFSET = 40

  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 104, 52))

    self._pill_bg_txt = gui_app.texture("icons_mici/alerts_pill.png", 104, 52)
    self._alert_count_callback: Callable[[], int] | None = None
    self._alert_icon_callback: Callable[[], rl.Texture | None] | None = None

  def set_alert_count_callback(self, callback: Callable[[], int] | None,
                               icon_callback: Callable[[], rl.Texture | None] | None = None):
    self._alert_count_callback = callback
    self._alert_icon_callback = icon_callback

  def _render(self, _):
    alert_count = self._alert_count_callback() if self._alert_count_callback else 0
    if alert_count > 0:
      pill_w, pill_h = self._pill_bg_txt.width, self._pill_bg_txt.height
      rl.draw_texture_ex(self._pill_bg_txt, rl.Vector2(self.rect.x, self.rect.y), 0.0, 1.0, rl.WHITE)

      warning_txt = self._alert_icon_callback() if self._alert_icon_callback else None
      if warning_txt is not None:
        scale = 36 / max(warning_txt.width, warning_txt.height)
        warn_x = self.rect.x + self.ICON_OFFSET
        warn_y = self.rect.y + (pill_h - warning_txt.height * scale) / 2
        rl.draw_texture_ex(warning_txt, rl.Vector2(warn_x, warn_y), 0.0, scale, rl.WHITE)

      count_rect = rl.Rectangle(self.rect.x + self.COUNT_OFFSET, self.rect.y, pill_w - self.COUNT_OFFSET, pill_h)
      gui_label(count_rect, str(alert_count), font_size=36,
                alignment=TextAlignment.CENTER,
                alignment_vertical=TextAlignmentVertical.MIDDLE)


class NetworkIcon(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 60, 47))  # max size of all icons
    self._net_type = NetworkType.none
    self._net_strength = 0

    self._wifi_slash_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_slash.png", 54, 47)
    self._wifi_none_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_none.png", 54, 40)
    self._wifi_low_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_low.png", 54, 40)
    self._wifi_medium_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_medium.png", 54, 40)
    self._wifi_full_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_full.png", 54, 40)

    self._cell_none_txt = gui_app.texture("icons_mici/settings/network/cell_strength_none.png", 60, 40)
    self._cell_low_txt = gui_app.texture("icons_mici/settings/network/cell_strength_low.png", 60, 40)
    self._cell_medium_txt = gui_app.texture("icons_mici/settings/network/cell_strength_medium.png", 60, 40)
    self._cell_high_txt = gui_app.texture("icons_mici/settings/network/cell_strength_high.png", 60, 40)
    self._cell_full_txt = gui_app.texture("icons_mici/settings/network/cell_strength_full.png", 60, 40)

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


class LongModeBadge(Widget):

  H = 48
  LOGO_W = 48
  COL_W = 16

  def __init__(self):
    super().__init__()
    self._comma = gui_app.texture("icons_mici/settings/comma_icon.png", 27, 48)
    self._tesla = gui_app.texture("icons_mici/tesla_t.png", 48, 48)
    self._font = gui_app.font(FontWeight.BOLD)
    self._op = False
    self.set_rect(rl.Rectangle(0, 0, float(self.LOGO_W + 4 + self.COL_W), float(self.H)))
    self.set_enabled(False)

  def _update_state(self):
    self._op = bool(ui_state.has_longitudinal_control)

  def _render(self, _) -> None:
    x, y = self.rect.x, self.rect.y
    tex = self._comma if self._op else self._tesla
    tx = x + (self.LOGO_W - tex.width) / 2
    ty = y + (self.H - tex.height) / 2
    rl.draw_texture_ex(tex, rl.Vector2(tx, ty), 0.0, 1.0, rl.WHITE)
    letters = "LONG" if self._op else "TACC"
    lsz = 11
    sizes = [measure_text_cached(self._font, ch, lsz) for ch in letters]
    gap = max(0.0, (self.H - sum(s.y for s in sizes)) / (len(letters) + 1))
    lx = x + self.LOGO_W + 2
    cy = y + gap
    for ch, sz in zip(letters, sizes, strict=False):
      rl.draw_text_ex(self._font, ch, rl.Vector2(lx + (self.COL_W - sz.x) / 2, cy), lsz, 0, WHITE)
      cy += sz.y + gap


class MiciHomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self._on_settings_click: Callable | None = None
    self._on_alerts_click: Callable | None = None
    self._alert_count_callback: Callable[[], int] | None = None

    self._version_text = self._get_version_text()
    self._wordmark_font = _wordmark_font()

    self._long_badge = LongModeBadge()
    self._usb_icon = IconWidget("icons_mici/usb.png", (62, 40))
    self._chestnut_icon = IconWidget("icons_mici/chestnut_green.png", (54, 40))
    self._chestnut_loading_icon = IconWidget("icons_mici/chestnut.png", (68, 40))
    self._chestnut_failed_icon = IconWidget("icons_mici/chestnut_orange.png", (68, 40))
    self._mic_icon = IconWidget("icons_mici/microphone.png", (32, 46))
    self._body_icon = IconWidget("icons_mici/body.png", (54, 37))

    self._alerts_pill = AlertsPill()

    self._status_bar_layout = HBoxLayout([
      IconWidget("icons_mici/settings.png", (48, 48), opacity=0.9),
      NetworkIcon(),
      self._long_badge,
      self._usb_icon,
      self._chestnut_icon,
      self._chestnut_loading_icon,
      self._chestnut_failed_icon,
      self._body_icon,
      self._mic_icon,
    ], spacing=18)

    self._version_label = UnifiedLabel("", font_size=36, text_color=GREY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._date_label = UnifiedLabel("", font_size=36, text_color=GREY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._branch_label = UnifiedLabel("", font_size=36, text_color=GREY, font_weight=FontWeight.ROMAN, scroll=True)
    self._trip_at = 0.0
    self._day_txt = ("Day", "0mi 0%")
    self._week_txt = ("Week", "0mi 0%")
    self._trip_hit = rl.Rectangle(0, 0, 0, 0)
    self._on_stats_click: Callable | None = None

  def _update_state(self):
    self._refresh_trip()

  def _refresh_trip(self):
    now = time.monotonic()
    if now - self._trip_at < 1.0:
      return
    self._trip_at = now
    t = stats_view()
    self._day_txt = ("Day", fmt_trip(t["today_m"], t["today_e"], ui_state.is_metric))
    self._week_txt = ("Week", fmt_trip(t["week_m"], t["week_e"], ui_state.is_metric))

  def set_callbacks(self, on_settings: Callable | None = None, on_alerts: Callable | None = None,
                    on_stats: Callable | None = None,
                    alert_count_callback: Callable[[], int] | None = None,
                    alert_icon_callback: Callable[[], rl.Texture | None] | None = None):
    self._on_settings_click = on_settings
    self._on_alerts_click = on_alerts
    self._on_stats_click = on_stats
    self._alert_count_callback = alert_count_callback
    self._alerts_pill.set_alert_count_callback(alert_count_callback, alert_icon_callback)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if (self._on_stats_click and self._trip_hit.width > 0 and
        rl.check_collision_point_rec(mouse_pos, self._trip_hit)):
      self._on_stats_click()
      return
    relative_x = mouse_pos.x - self.rect.x
    has_alerts = self._alert_count_callback and self._alert_count_callback() > 0
    if has_alerts and relative_x > self.rect.width - ALERTS_ZONE_WIDTH:
      if self._on_alerts_click:
        self._on_alerts_click()
    elif self._on_settings_click:
      self._on_settings_click()

  def _get_version_text(self) -> tuple[str, str, str, str] | None:
    version = ui_state.params.get("Version")
    branch = ui_state.params.get("GitBranch")
    commit = ui_state.params.get("GitCommit")

    if not all((version, branch, commit)):
      return None

    commit_date_raw = ui_state.params.get("GitCommitDate")
    try:
      unix_ts = int(commit_date_raw.strip("'").split()[0])
      date_str = datetime.datetime.fromtimestamp(unix_ts).strftime("%b %d")
    except (ValueError, IndexError, TypeError, AttributeError):
      date_str = ""

    return version, branch, commit[:7], date_str

  def _render(self, _):
    text_pos = rl.Vector2(self.rect.x - 2 + HOME_PADDING, self.rect.y + 2)
    mark = "TESLAPILOT"
    avail = max(200, self.rect.width - HOME_PADDING * 2)
    wm = MICI_WORDMARK_SIZE
    while wm > 28:
      if measure_text_cached(self._wordmark_font, mark, wm).x <= avail:
        break
      wm -= 2
    rl.draw_text_ex(self._wordmark_font, mark, text_pos, wm, 0, WHITE)

    if self._version_text is not None:
      release_branch = self._version_text[1] in RELEASE_BRANCHES
      version_pos = rl.Rectangle(text_pos.x, text_pos.y + wm + 16, 100, 44)
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
      avail = self.rect.width - HOME_PADDING * 2
      row_w, lsz = draw_trip_row(gui_app.font(FontWeight.ROMAN), gui_app.font(FontWeight.DISPLAY), version_pos.x, y2, avail, self._day_txt, self._week_txt)
      self._trip_hit = rl.Rectangle(version_pos.x - 4, y2 - 4, min(avail, row_w) + 8, lsz * 1.16 + 8)

    # ***** Center-aligned bottom section icons *****
    usb_connected = ui_state.usb_connected
    usb_unknown = ui_state.usb_unknown
    chestnut_state = ui_state.chestnut_state
    # zoompilot's chestnut icons (sunnypilot/mici/layouts/home.py _set_chestnut_visibility),
    # which also show Jetlink: ui_state.chestnut_state is the link's with no chestnut fitted
    loading = chestnut_state == ChestnutState.LOADING
    # ready, and only a swap window away: steady rather than the loading pulse,
    # dim rather than the solid green of a model that is driving
    waiting = chestnut_state == ChestnutState.WAITING
    self._usb_icon.set_visible(usb_connected and usb_unknown)
    self._chestnut_loading_icon.set_opacity(0.35 + 0.65 * (0.5 - 0.5 * math.cos(rl.get_time() * 6.0)))
    self._chestnut_loading_icon.set_visible(not usb_unknown and loading)
    self._chestnut_icon.set_opacity(0.5 if waiting else 1.0)
    self._chestnut_icon.set_visible(not usb_unknown and not loading and
                                    chestnut_state in (ChestnutState.READY, ChestnutState.ACTIVE, ChestnutState.WAITING))
    self._chestnut_failed_icon.set_visible(not usb_unknown and chestnut_state in (ChestnutState.UNCOMPILED, ChestnutState.FAILED))
    self._mic_icon.set_visible(ui_state.recording_audio)
    self._body_icon.set_visible(bool(ui_state.is_body))

    footer_rect = rl.Rectangle(self.rect.x + HOME_PADDING, self.rect.y + self.rect.height - 48, self.rect.width - HOME_PADDING, 48)
    self._status_bar_layout.render(footer_rect)

    self._alerts_pill.set_position(self.rect.x + self.rect.width - self._alerts_pill.rect.width - HOME_PADDING,
                                   self.rect.y + self.rect.height - self._alerts_pill.rect.height)
    self._alerts_pill.render()
