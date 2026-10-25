"""Onroad engaged-streak icon (DriveSummary param): a 50 px circle in the
bottom-right corner of the camera window, opposite the steering wheel.

Engaged only: it fades in and out with the other engaged HUD elements, using
the steering wheel icon's alpha filter (HudRenderer.engaged_alpha), so there
is no timing of its own and no disengaged state.

Shows the current continuous engaged stretch (drive_summary.recorder.cur_m,
which is 0 at the start of every engagement) in the user's unit: one decimal
under 10, whole numbers from 10. "STREAK" sits above the number when it fits
inside the circle.

The ring is progress toward the user's streak record (best stretch ever,
drive_summary.streak_record_m). It fills clockwise from 12 o'clock in the
user's theme color (drive_summary.accent_rgb, comma green on forks without a
theme manager), and is full once the record is reached or beaten. With no
record yet, only the neutral track shows. Drawn inside the camera content
rect, so it never reaches the confidence-ball side panel. Code-drawn.
"""
from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.lib import drive_summary as ds
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

SIZE = 50
RIGHT = 21                 # mirrors the wheel's 21 px left margin
BOTTOM = 14                # same bottom margin as the wheel
LABEL = "STREAK"
POLL_S = 2.0               # theme + record re-read
TEXT_W = 34                # number + unit stay inside the ring's chord


def _c(rgb, a: float) -> rl.Color:
  return rl.Color(rgb[0], rgb[1], rgb[2], max(0, min(255, int(255 * a))))


class StreakIcon:
  def __init__(self):
    self._held_m: float | None = None
    self._poll_t = -1e9
    self._accent = ds.COMMA_GREEN
    self._record_m = 0.0

  def render(self, rect: rl.Rectangle, alpha: float = 1.0) -> None:
    """alpha: the shared engaged-UI fade (HudRenderer.engaged_alpha)."""
    if not ds.enabled(ui_state.params):
      return
    engaged = ui_state.status != UIStatus.DISENGAGED and ui_state.engaged
    shown_m, self._held_m = ds.streak_view(engaged, alpha, ds.recorder.cur_m, self._held_m)
    if shown_m is None:
      return
    now = rl.get_time()
    if now - self._poll_t > POLL_S:
      self._poll_t = now
      self._accent = ds.accent_rgb()
      self._record_m = ds.streak_record_m(ui_state.params)
    metric = bool(ui_state.is_metric)
    unit_m = 1000.0 if metric else 1609.344
    frac = ds.streak_record_frac(shown_m, self._record_m)
    self.draw(*icon_pos(rect), shown_m / unit_m, alpha, metric, self._accent, frac)

  @staticmethod
  def draw(x: float, y: float, dist: float, a: float, metric: bool,
           accent=ds.COMMA_GREEN, frac: float | None = None) -> None:
    """dist in the user's unit; frac: progress toward the record (drive_summary.streak_record_frac),
    None = no record yet."""
    cx, cy = x + SIZE / 2, y + SIZE / 2
    rl.draw_circle_v(rl.Vector2(cx, cy), SIZE / 2, _c((10, 10, 14), 0.78 * a))
    rl.draw_ring(rl.Vector2(cx, cy), 21.5, 24, 0, 360, 48, _c(WHITE_RGB, 0.16 * a))
    if frac is not None and frac > 0:
      # raylib angles: 0 = +x, clockwise on screen; start at 12 o'clock
      rl.draw_ring(rl.Vector2(cx, cy), 21.5, 24, -90, -90 + 360 * frac, 48, _c(accent, 0.95 * a))
    bold = gui_app.font(FontWeight.DISPLAY)
    v, u = ds.fmt_streak(dist), ("km" if metric else "mi")
    vs, us, ls = 17, 10, 7
    wv, wu = measure_text_cached(bold, v, vs).x, measure_text_cached(bold, u, us).x
    while wv + 1 + wu > TEXT_W and vs > 12:
      vs -= 1
      wv = measure_text_cached(bold, v, vs).x
    x0 = cx - (wv + 1 + wu) / 2
    top = cy - 3
    rl.draw_text_ex(bold, v, rl.Vector2(x0, top), vs, 0, _c(WHITE_RGB, 0.92 * a))
    rl.draw_text_ex(bold, u, rl.Vector2(x0 + wv + 1, top + (vs - us) * 0.8 * 1.16), us, 0, _c(WHITE_RGB, 0.65 * a))
    wl = measure_text_cached(bold, LABEL, ls).x
    if label_fits(wl):
      rl.draw_text_ex(bold, LABEL, rl.Vector2(cx - wl / 2, cy - 13), ls, 0, _c(WHITE_RGB, 0.7 * a))


def icon_pos(rect: rl.Rectangle) -> tuple[float, float]:
  """Top-left of the icon: bottom-right of the camera content rect."""
  return rect.x + rect.width - RIGHT - SIZE, rect.y + rect.height - BOTTOM - SIZE


def label_fits(width: float, r_inner: float = 20.0, dy: float = 9.0) -> bool:
  """STREAK sits ~10 px above center: it must fit the circle's chord there."""
  return width <= 2 * (r_inner * r_inner - dy * dy) ** 0.5


WHITE_RGB = (255, 255, 255)
