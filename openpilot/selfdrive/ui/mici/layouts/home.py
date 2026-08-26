import datetime
import json
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
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_DIR
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.weather_news import config as grok_cfg
from openpilot.common.version import RELEASE_BRANCHES

HEAD_BUTTON_FONT_SIZE = 40
HOME_PADDING = 8
ALERTS_ZONE_WIDTH = 180
TRIP_PATH = "/data/trip_meter.json"
WORDMARK_SIZE = 80
LABEL_WHITE = rl.Color(255, 255, 255, int(255 * 0.9))


def _wordmark_font() -> rl.Font:
  """Dies/KAYOver TESLA.ttf for SEXYPILOT. Falls back to Inter DISPLAY."""
  try:
    chars = "SEXYPILOT"
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


class LongModeBadge(Widget):
  """Footer: Tesla T + TACC, or comma + LONG. 48px tall like experimental."""
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
    for ch, sz in zip(letters, sizes):
      rl.draw_text_ex(self._font, ch, rl.Vector2(lx + (self.COL_W - sz.x) / 2, cy), lsz, 0, LABEL_WHITE)
      cy += sz.y + gap


class VoiceHomeIcon(IconWidget):
  """50px home mark. Swaps to the Gemini sparkle when Gemini is the active provider."""

  def __init__(self):
    super().__init__("icons_mici/grok.png", (50, 50), opacity=0.9)
    self._marks = {
      "grok": self._texture,
      "gemini": gui_app.texture("icons_mici/gemini.png", 50, 50),
    }

  def _render(self, _) -> None:
    tex = self._marks["gemini"] if grok_cfg.provider() == "gemini" else self._marks["grok"]
    color = rl.Color(255, 255, 255, int(self._opacity * 255))
    rl.draw_texture_ex(tex, rl.Vector2(self._rect.x, self._rect.y), 0.0, 1.0, color)


_GROK_STATUS = {
  "queued": "Thinking",
  "fetching weather": "Thinking",
  "getting news": "Thinking",
  "asking grok": "Thinking",
  "speaking": "Speaking",
  "failed": "Couldn't reach Grok",
  "enable grok": "Turn Grok on",
  "scan QR": "Add an API key",
}


class GrokOverlay(Widget):
  """Tesla-style full-screen wait. Shown while the selected AI is generating."""

  def __init__(self):
    super().__init__()
    self._marks = {
      "grok": gui_app.texture("icons_mici/grok_lg.png", 160, 160),
      "gemini": gui_app.texture("icons_mici/gemini_lg.png", 160, 160),
    }
    self._font = gui_app.font(FontWeight.DISPLAY)
    self._small = gui_app.font(FontWeight.ROMAN)
    self._t0 = time.monotonic()
    self._caption = "Thinking"
    self.set_enabled(True)

  def set_caption(self, text: str) -> None:
    self._caption = text

  def _render(self, _rect: rl.Rectangle) -> None:
    rect = self.rect
    t = time.monotonic() - self._t0
    rl.draw_rectangle_rec(rect, rl.Color(0, 0, 0, 230))
    cx = rect.x + rect.width * 0.5
    cy = rect.y + rect.height * 0.42
    pulse = 0.94 + 0.06 * (0.5 + 0.5 * math.sin(t * 2.2))
    sz = 160.0 * pulse
    gemini = grok_cfg.provider() == "gemini"
    mark = self._marks["gemini"] if gemini else self._marks["grok"]
    name = grok_cfg.display_name()
    src = rl.Rectangle(0, 0, float(mark.width), float(mark.height))
    dst = rl.Rectangle(cx, cy, sz, sz)
    rl.draw_texture_pro(mark, src, dst, rl.Vector2(sz * 0.5, sz * 0.5), t * 18.0, rl.WHITE)
    ring_r = 108.0
    start = (t * 140.0) % 360.0
    rl.draw_ring(rl.Vector2(cx, cy), ring_r - 2.5, ring_r, start, start + 78.0, 40, rl.Color(255, 255, 255, 180))
    nw = measure_text_cached(self._font, name, 36)
    rl.draw_text_ex(self._font, name, rl.Vector2(cx - nw.x * 0.5, cy + 128), 36, 0, rl.WHITE)
    cap = self._caption
    if cap == "Couldn't reach Grok":
      cap = f"Couldn't reach {name}"
    elif cap == "Turn Grok on":
      cap = f"Turn {name} on"
    cw = measure_text_cached(self._small, cap, 22)
    rl.draw_text_ex(self._small, cap, rl.Vector2(cx - cw.x * 0.5, cy + 172), 22, 0, rl.Color(160, 160, 168, 255))


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
    self._wordmark_font = _wordmark_font()

    self._experimental_icon = IconWidget("icons_mici/experimental_mode.png", (48, 48))
    self._experimental_icon.set_enabled(True)
    self._experimental_icon.set_click_callback(self._toggle_experimental)
    self._long_badge = LongModeBadge()
    self._egpu_icon = IconWidget("icons_mici/egpu_green.png", (50, 37))
    self._egpu_icon_gray = IconWidget("icons_mici/egpu_gray.png", (50, 37))
    self._mic_icon = IconWidget("icons_mici/microphone.png", (32, 46))
    self._body_icon = IconWidget("icons_mici/body.png", (54, 37))
    self._grok_icon = VoiceHomeIcon()
    self._grok_icon.set_click_callback(self._grok_ondemand)
    self._grok_overlay = GrokOverlay()
    self._grok_busy = False
    self._grok_saw = False
    self._grok_t0 = 0.0

    self._alerts_pill = AlertsPill()

    self._status_bar_layout = HBoxLayout([
      IconWidget("icons_mici/settings.png", (48, 48), opacity=0.9),
      NetworkIcon(),
      self._grok_icon,
      self._long_badge,
      self._experimental_icon,
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
    self._last_txt = ("Today ", "0mi 0%")
    self._week_txt = ("Week ", "0mi 0%")

  def _update_state(self):
    self._refresh_trip()

  def _fmt_trip(self, meters: float, eng_m: float) -> str:
    if ui_state.is_metric:
      dist, unit = meters / 1000.0, "km"
    else:
      dist, unit = meters / 1609.344, "mi"
    pct = int(round(100.0 * eng_m / meters)) if meters > 1 else 0
    return f"{int(round(dist))}{unit} {pct}%"

  def _refresh_trip(self):
    now = time.monotonic()
    if now - self._trip_at < 1.0:
      return
    self._trip_at = now
    try:
      t = json.loads(open(TRIP_PATH).read())
    except Exception:
      t = {}
    self._last_txt = ("Today ", self._fmt_trip(t.get("today_m", 0) or 0, t.get("today_eng_m", 0) or 0))
    self._week_txt = ("Week ", self._fmt_trip(t.get("week_m", 0) or 0, t.get("week_eng_m", 0) or 0))

  def set_callbacks(self, on_settings: Callable | None = None, on_alerts: Callable | None = None,
                    alert_count_callback: Callable[[], int] | None = None,
                    max_severity_callback: Callable[[], int | None] | None = None):
    self._on_settings_click = on_settings
    self._on_alerts_click = on_alerts
    self._alert_count_callback = alert_count_callback
    self._alerts_pill.set_alert_count_callback(alert_count_callback, max_severity_callback)

  def _toggle_experimental(self):
    if not ui_state.has_longitudinal_control or not ui_state.experimental_mode_confirmed:
      return
    on = not ui_state.experimental_mode
    ui_state.experimental_mode = on
    ui_state.params.put_bool("ExperimentalMode", on)

  def _grok_status(self) -> str:
    try:
      v = ui_state.params.get("WeatherNewsStatus")
      if isinstance(v, bytes):
        v = v.decode(errors="replace")
      return (v or "").strip()
    except Exception:
      return ""

  def _grok_ondemand(self):
    if self._grok_busy:
      return
    self._grok_busy = True
    self._grok_saw = False
    self._grok_t0 = time.monotonic()
    self._grok_overlay = GrokOverlay()
    try:
      ui_state.params.put("WeatherNewsStatus", "queued")
    except Exception:
      pass
    grok_cfg.request_ondemand()

  def _sync_grok_overlay(self) -> None:
    if not self._grok_busy:
      return
    st = self._grok_status()
    if st:
      self._grok_saw = True
    cap = _GROK_STATUS.get(st, "Thinking")
    if st == "playing":
      self._grok_busy = False
      return
    if st == "failed":
      self._grok_overlay.set_caption(cap)
      if time.monotonic() - self._grok_t0 > 2.5:
        self._grok_busy = False
      return
    if not st and self._grok_saw:
      self._grok_busy = False
      return
    self._grok_overlay.set_caption(cap)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    on_grok = (self._grok_icon.is_visible and
               rl.check_collision_point_rec(mouse_pos, self._grok_icon.rect))
    if self._grok_busy and not on_grok:
      self._grok_busy = False
      return
    if (self._experimental_icon.is_visible and self._experimental_icon.enabled and
        rl.check_collision_point_rec(mouse_pos, self._experimental_icon.rect)):
      return
    if on_grok:
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
      # GitCommitDate format from get_commit_date(): '%ct %ci' e.g. "'1708012345 2024-02-15 ...'"
      unix_ts = int(commit_date_raw.strip("'").split()[0])
      date_str = datetime.datetime.fromtimestamp(unix_ts).strftime("%b %d")
    except (ValueError, IndexError, TypeError, AttributeError):
      date_str = ""

    return version, branch, commit[:7], date_str

  def _render(self, _):
    # TODO: why is there extra space here to get it to be flush?
    text_pos = rl.Vector2(self.rect.x - 2 + HOME_PADDING, self.rect.y + 2)
    # C4 is 536px. TESLA.ttf @ 80 is ~580px of ink.
    wm = 60 if self.rect.width < 1000 else WORDMARK_SIZE
    rl.draw_text_ex(self._wordmark_font, "SEXYPILOT", text_pos, wm, 0, LABEL_WHITE)

    if self._version_text is not None:
      # release branch
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
      f = gui_app.font(FontWeight.ROMAN)
      ll, lv = self._last_txt
      wl, wv = self._week_txt
      avail = self.rect.width - HOME_PADDING * 2
      lsz = 36
      while lsz > 22:
        vsz = max(18, lsz - 6)
        w = (measure_text_cached(f, ll, lsz).x + measure_text_cached(f, lv, vsz).x +
             16 + measure_text_cached(f, wl, lsz).x + measure_text_cached(f, wv, vsz).x)
        if w <= avail:
          break
        lsz -= 1
      vsz = max(18, lsz - 6)
      x = version_pos.x
      vy = y2 + (lsz - vsz)
      rl.draw_text_ex(f, ll, rl.Vector2(x, y2), lsz, 0, rl.GRAY)
      x += measure_text_cached(f, ll, lsz).x
      rl.draw_text_ex(f, lv, rl.Vector2(x, vy), vsz, 0, LABEL_WHITE)
      x += measure_text_cached(f, lv, vsz).x + 16
      rl.draw_text_ex(f, wl, rl.Vector2(x, y2), lsz, 0, rl.GRAY)
      x += measure_text_cached(f, wl, lsz).x
      rl.draw_text_ex(f, wv, rl.Vector2(x, vy), vsz, 0, LABEL_WHITE)

    # ***** Center-aligned bottom section icons *****
    op_long = bool(ui_state.has_longitudinal_control)
    self._experimental_icon.set_visible(op_long)
    self._experimental_icon.set_enabled(op_long)
    self._experimental_icon._opacity = 1.0 if ui_state.experimental_mode else 0.4
    self._egpu_icon.set_visible(ui_state.sm["deviceState"].chestnutPresent and ui_state.usbgpu_compiled)
    self._egpu_icon_gray.set_visible(ui_state.sm["deviceState"].chestnutPresent and not ui_state.usbgpu_compiled)
    self._mic_icon.set_visible(ui_state.recording_audio)
    self._body_icon.set_visible(bool(ui_state.is_body))
    grok_on = grok_cfg.voice_enabled()
    self._grok_icon.set_visible(grok_on)
    self._grok_icon.set_enabled(grok_on)

    footer_rect = rl.Rectangle(self.rect.x + HOME_PADDING, self.rect.y + self.rect.height - 48, self.rect.width - HOME_PADDING, 48)
    self._status_bar_layout.render(footer_rect)

    # TODO: add alignment to hboxlayout and add to there
    self._alerts_pill.set_position(self.rect.x + self.rect.width - self._alerts_pill.rect.width - HOME_PADDING,
                                   self.rect.y + self.rect.height - self._alerts_pill.rect.height)
    self._alerts_pill.render()

    self._sync_grok_overlay()
    if self._grok_busy:
      self._grok_overlay.set_rect(self.rect)
      self._grok_overlay.render()
