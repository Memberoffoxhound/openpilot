"""Onroad engaged-streak pill (DriveSummary param): a 50 px tall pill (the
steering wheel icon's height) in the bottom-right corner of the camera window,
opposite the wheel, growing left.

Engaged only: it fades in and out with the other engaged HUD elements, using
the steering wheel icon's alpha filter (HudRenderer.engaged_alpha), so there
is no timing of its own and no disengaged state.

Shows the current continuous engaged stretch (drive_summary.recorder.cur_m,
which is 0 at the start of every engagement) as a big number in the user's
unit: one decimal under 10, whole numbers from 10. Under it, a progress bar
toward the user's streak record (best stretch ever,
drive_summary.streak_record_m) in the user's theme color
(drive_summary.accent_rgb, comma green on forks without a theme manager),
full once the record is reached or beaten; with no record yet only the
neutral track shows. The unit sits at the right end of the bar row.

Never overlaps the torque bar: drive_summary.pill_rect clamps the width so the
pill stops short of the torque bar's largest extent (and the wheel). In a view
too narrow for that (beside the navigation panel) it is not drawn. Drawn inside
the camera content rect, so it never reaches the confidence-ball side panel.
Code-drawn.
"""
from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.lib import drive_summary as ds
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

POLL_S = 2.0               # theme + record re-read
VALUE_SIZE = 30            # number, shrinks to fit the pill (not below VALUE_MIN)
VALUE_MIN = 20
UNIT_SIZE = 12
PAD = 10                   # number's side padding inside the pill
BAR_INSET = 13             # progress bar's side inset (clear of the rounded ends)
BAR_H = 4
BAR_Y = 39                 # bar top, from the pill top
WHEEL = 50                 # the HUD steering wheel icon: 50 px, 21 px from the left, 14 px from the bottom
WHEEL_LEFT = 21


def _c(rgb, a: float) -> rl.Color:
  return rl.Color(rgb[0], rgb[1], rgb[2], max(0, min(255, int(255 * a))))


def keep_out(rect: rl.Rectangle) -> list[tuple[float, float, float, float]]:
  """What the pill must never touch inside the camera view: the torque bar at its largest and the wheel."""
  wheel = (rect.x + WHEEL_LEFT, rect.y + rect.height - ds.PILL_BOTTOM - WHEEL, WHEEL, WHEEL)
  return [ds.torque_bar_bounds(rect.x, rect.y, rect.width, rect.height), wheel]


def pill_rect(rect: rl.Rectangle):
  return ds.pill_rect(rect.x, rect.y, rect.width, rect.height, keep_out(rect))


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
    pill = pill_rect(rect)
    if pill is None:
      return
    now = rl.get_time()
    if now - self._poll_t > POLL_S:
      self._poll_t = now
      self._accent = ds.accent_rgb()
      self._record_m = ds.streak_record_m(ui_state.params)
    metric = bool(ui_state.is_metric)
    unit_m = 1000.0 if metric else 1609.344
    frac = ds.streak_record_frac(shown_m, self._record_m)
    self.draw(pill, shown_m / unit_m, alpha, metric, self._accent, frac)

  @staticmethod
  def draw(pill, dist: float, a: float, metric: bool, accent=ds.COMMA_GREEN, frac: float | None = None) -> None:
    """pill: (x, y, w, h) from pill_rect; dist in the user's unit; frac: progress toward the record
    (drive_summary.streak_record_frac), None = no record yet."""
    x, y, w, h = pill
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 1.0, 16, _c((10, 10, 14), 0.82 * a))
    bold = gui_app.font(FontWeight.DISPLAY)
    v, u = ds.fmt_streak(dist), ("km" if metric else "mi")
    vs = VALUE_SIZE
    wv = measure_text_cached(bold, v, vs).x
    while wv > w - 2 * PAD and vs > VALUE_MIN:
      vs -= 1
      wv = measure_text_cached(bold, v, vs).x
    rl.draw_text_ex(bold, v, rl.Vector2(x + (w - wv) / 2, y + 3 + (VALUE_SIZE - vs) * 0.5), vs, 0, _c(WHITE_RGB, 0.95 * a))
    # bar row: progress toward the record, then the unit
    wu = measure_text_cached(bold, u, UNIT_SIZE).x
    bx, by = x + BAR_INSET, y + BAR_Y
    bw = max(BAR_H, w - 2 * BAR_INSET - wu - 4)
    rl.draw_rectangle_rounded(rl.Rectangle(bx, by, bw, BAR_H), 1.0, 6, _c(WHITE_RGB, 0.2 * a))
    if frac is not None and frac > 0:
      rl.draw_rectangle_rounded(rl.Rectangle(bx, by, max(BAR_H, bw * frac), BAR_H), 1.0, 6, _c(accent, 0.95 * a))
    rl.draw_text_ex(bold, u, rl.Vector2(bx + bw + 4, by + BAR_H / 2 - UNIT_SIZE * 1.16 / 2), UNIT_SIZE, 0,
                    _c(WHITE_RGB, 0.7 * a))


WHITE_RGB = (255, 255, 255)
