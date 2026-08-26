"""Theme → voice setup QR. Lands on the LAN console /grok page."""

import time

import pyray as rl

from openpilot.common.qrcode import make_texture
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.weather_news import config as grok_cfg
from openpilot.selfdrive.weather_news import grok as grok_api
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.nav_widget import NavWidget


class GrokQrPage(NavWidget):
  QR_REFRESH_INTERVAL = 15.0

  def __init__(self):
    super().__init__()
    self._qr_texture: rl.Texture | None = None
    self._last_qr_generation = float("-inf")
    self._url = ""
    who = grok_cfg.display_name().lower()
    self._label = UnifiedLabel(f"scan for {who} setup", font_size=48, font_weight=FontWeight.BOLD, line_height=0.8)
    self._sub = UnifiedLabel("", font_size=28, font_weight=FontWeight.MEDIUM, line_height=0.9)

  def _url_now(self) -> str:
    return grok_api.console_url("/grok")

  def _generate_qr_code(self) -> None:
    url = self._url_now()
    self._url = url
    self._sub.set_text(url.replace("http://", ""))
    try:
      if self._qr_texture and self._qr_texture.id != 0:
        rl.unload_texture(self._qr_texture)
      self._qr_texture = make_texture(url, inverted=True)
    except Exception as e:
      cloudlog.warning(f"grok QR failed: {e}")
      self._qr_texture = None

  def _check_qr_refresh(self) -> None:
    now = time.monotonic()
    if now - self._last_qr_generation >= self.QR_REFRESH_INTERVAL:
      self._generate_qr_code()
      self._last_qr_generation = now

  def _render(self, rect: rl.Rectangle):
    self._check_qr_refresh()
    if not self._qr_texture:
      error_font = gui_app.font(FontWeight.BOLD)
      rl.draw_text_ex(
        error_font, "QR Code Error", rl.Vector2(self._rect.x + 20, self._rect.y + self._rect.height // 2 - 15),
        30, 0.0, rl.RED,
      )
      return

    scale = self._rect.height / self._qr_texture.height
    pos = rl.Vector2(round(self._rect.x + 8), round(self._rect.y))
    rl.draw_texture_ex(self._qr_texture, pos, 0.0, scale, rl.WHITE)

    label_x = self._rect.x + 8 + self._rect.height + 24
    self._label.set_max_width(int(self._rect.width - label_x))
    self._label.set_position(label_x, self._rect.y + 16)
    self._label.render()
    self._sub.set_max_width(int(self._rect.width - label_x - 8))
    self._sub.set_position(label_x, self._rect.y + self._rect.height - 56)
    self._sub.render()

  def __del__(self):
    if self._qr_texture and self._qr_texture.id != 0:
      rl.unload_texture(self._qr_texture)
