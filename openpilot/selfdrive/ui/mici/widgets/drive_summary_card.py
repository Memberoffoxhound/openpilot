"""Trip-complete card (DriveSummary param): an extra hop between the onroad
page and home when a trip ends.

Looks like a normal-status alert: opaque black over the whole screen, an Inter
Bold lowercase headline (alert text1 style) with a check badge in the user's
theme color to its right (drive_summary.accent_rgb: the fork's theme manager,
else comma green), then the stats.

The main layout draws it as an overlay above its scroller. On the onroad ->
offroad edge, when the trip is due (toggle on, recorded drive, stopped,
>= 0.1 mi and 30 s), it slides in from the top over the onroad page, and the
stock scroll to home waits. After SHOW_S, or a tap, the stock scroll to home
runs and the card moves with the onroad page (attached to its scroller
position), sideways like home sliding in today. No exit animation of its own. When it isn't due, the scroll happens
at once (stock). Going back onroad removes it at once and cancels the hand-off.
Smooth entry, no bounce (card_slide.py), no on-screen timer.

  trip complete (check)
   6.8mi      81%         4         1.2mi            evenly spaced columns, each value
   driven   engaged   day streak best stretch        centered over its label (best only if it fits)
  [====green====|blue|==green==|yellow|=====green=====]   connect-style timeline
  Today 7mi 81%          Week 42mi 64%                   (trip_row.draw_trip_block)

Data comes from drive_summary.py (the trip the recorder just finished). Today/Week and
the day streak come from stats_fn() when the fork has home trip stats
(stats_view keys today_m/today_e/week_m/week_e/streak_days), else from the
few days of totals drive_summary keeps itself. Everything is drawn in code:
no new assets.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.lib import drive_summary as ds
from openpilot.selfdrive.ui.mici.widgets.card_slide import SHOWN, CardSlide, attached_dx
from openpilot.selfdrive.ui.mici.widgets.trip_row import draw_trip_block, fmt_trip
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

CARD_H = 240              # the whole home screen: opaque, so the home icons never show under it
PAD = 18
BADGE_GAP = 14
UNIT_GAP = 2
HEADLINE = "trip complete"
HEAD_SIZE, HEAD_Y = 62, 2          # alert text1 is 70-82 Inter Bold; 62 leaves room for the stats
VAL_SIZE, UNIT_SIZE, LBL_SIZE = 46, 24, 22
VAL_Y, LBL_Y = 80, 130
TL_Y, TL_H = 161, 18        # 1.5x the first 12 px bar: readable on the small screen; 8 px under the labels
TRIP_Y = 189
WHITE = (255, 255, 255)
VALUE_A, DIM_A = 0.9, 0.65
ASCENT = 0.80              # Inter baseline as a fraction of the raylib font size (x FONT_SCALE in draw)


def _col(rgb, a: float) -> rl.Color:
  return rl.Color(rgb[0], rgb[1], rgb[2], max(0, min(255, int(255 * a))))


def accent_rgb() -> tuple[int, int, int]:
  return ds.accent_rgb()


def draw_check_badge(cx: float, cy: float, r: float, rgb, a: float) -> None:
  rl.draw_circle_v(rl.Vector2(cx, cy), r, _col(rgb, a))
  t = max(3.0, r * 0.22)
  p1 = rl.Vector2(cx - r * 0.45, cy + r * 0.02)
  p2 = rl.Vector2(cx - r * 0.12, cy + r * 0.36)
  p3 = rl.Vector2(cx + r * 0.48, cy - r * 0.32)
  white = _col(WHITE, a)
  rl.draw_line_ex(p1, p2, t, white)
  rl.draw_line_ex(p2, p3, t, white)
  rl.draw_circle_v(p2, t / 2, white)


class DriveSummaryCard:
  """Drawn by the main layout as an overlay above the onroad page, the moment a trip ends:
  the card hops in first, then the stock scroll to home follows (HomeHandoff). Main layout
  hooks: hold_home() on the offroad edge, release_home() every tick, cancel() on the onroad
  edge, render(rect) after the scroller, dismiss_on_tap() in its tap handler."""

  def __init__(self, stats_fn: Callable[[], dict] | None = None):
    self._stats_fn = stats_fn
    self._drive: dict | None = None
    self._shown_at: float | None = None
    self._cols: list[tuple[str, str, str]] = []
    self._today = ("Today ", "")
    self._week = ("Week ", "")
    self._accent: tuple[int, int, int] = ds.COMMA_GREEN
    self._slide = CardSlide(CARD_H, 1 / gui_app.target_fps)
    self._handoff = ds.HomeHandoff()

  @property
  def visible(self) -> bool:
    """On screen: entering, shown, or sliding away."""
    return self._slide.drawn and not ui_state.started

  @property
  def holding(self) -> bool:
    """Up and not yet dismissed: the main layout keeps the stock scroll to home waiting.
    Time-based too, so it lets go after SHOW_S even when the card isn't being drawn (settings open)."""
    return (self._slide.state == SHOWN and self._shown_at is not None and
            time.monotonic() - self._shown_at < ds.SHOW_S)

  def dismiss(self) -> None:
    """Dismiss (timeout or tap): the main layout scrolls to home and the card rides the onroad page off."""
    self._slide.hide()

  def dismiss_on_tap(self) -> bool:
    """Main layout's tap hook: a tap while the card is on screen only dismisses it."""
    if self.visible:
      self.dismiss()
      return True
    return False

  # -- main-layout hand-off -------------------------------------------------------

  def hold_home(self) -> bool:
    """Offroad edge. True: the card is hopping in, hold the stock scroll to home.
    False: not due (toggle off, short trip, still moving, ...): stock, scroll now."""
    shown = self._begin()
    return not self._handoff.offroad(shown)

  def release_home(self) -> bool:
    """Every tick. True once, when the card goes away: scroll to home now."""
    return self._handoff.release(self.holding)

  def cancel(self) -> None:
    """Onroad edge: the card is gone at once and nothing is pending; onroad takes over."""
    self._handoff.onroad()
    self._slide.cut()
    self._shown_at = None

  def _begin(self) -> bool:
    try:
      params = ui_state.params
      drive = ds.due_summary(params)
      if drive is None:
        return False
      ds.recorder.shown = True
      data = ds.add_drive(ds.get_json(params, ds.PARAM_LAST), drive)   # Today/Week fallback incl. this trip
      self._drive = drive
      self._load_texts(data)
    except Exception:
      return False
    self._shown_at = time.monotonic()
    self._slide.show()
    return True

  def _load_texts(self, data: dict | None) -> None:
    metric = bool(ui_state.is_metric)
    st: dict = {}
    if self._stats_fn is not None:
      try:
        st = self._stats_fn() or {}
      except Exception:
        st = {}
    if "today_m" not in st:
      st = {**ds.today_week(data), "streak_days": ds.day_streak(data)}
    self._accent = accent_rgb()
    self._cols = ds.card_columns(self._drive or {}, int(st.get("streak_days") or 0), metric)
    self._today = ("Today ", fmt_trip(float(st.get("today_m") or 0), float(st.get("today_e") or 0), metric))
    self._week = ("Week ", fmt_trip(float(st.get("week_m") or 0), float(st.get("week_e") or 0), metric))

  # -- drawing ---------------------------------------------------------------

  def render(self, rect: rl.Rectangle, page_x: float | None = None) -> None:
    """page_x: the onroad page's current x in the main layout's scroller. Once dismissed, the card
    rides it, so it leaves with the stock scroll to home."""
    if ui_state.started:
      self.cancel()
      return
    if self._shown_at is not None and time.monotonic() - self._shown_at >= ds.SHOW_S:
      self.dismiss()
    self._slide.height, self._slide.width = rect.height, rect.width   # fully off-screen at both ends
    pos = self._slide.step(attached_dx(rect.x if page_x is None else page_x, rect.x))
    if pos is None:
      self._shown_at = None
      return
    if self._drive is not None:
      self.draw(rect.x + pos[0], rect.y + pos[1], rect.width, rect.height, 1.0)

  def draw(self, x: float, y: float, w: float, h: float = CARD_H, alpha: float = 1.0) -> None:
    a = alpha
    # opaque like a normal-status alert, over the whole home screen (no home icons peeking through)
    rl.draw_rectangle(int(x), int(y), int(w), int(h), _col((0, 0, 0), a))

    bold = gui_app.font(FontWeight.DISPLAY)
    roman = gui_app.font(FontWeight.ROMAN)
    cx = x + PAD

    # headline: alert text1 style (Inter Bold, lowercase, white 0.9), the dominant element; theme check badge to its right
    rl.draw_text_ex(bold, HEADLINE, rl.Vector2(cx, y + HEAD_Y), HEAD_SIZE, 0, _col(WHITE, VALUE_A * a))
    br = HEAD_SIZE * 0.30
    hw = measure_text_cached(bold, HEADLINE, HEAD_SIZE).x
    bcx = min(cx + hw + BADGE_GAP + br, x + w - PAD - br)
    draw_check_badge(bcx, y + HEAD_Y + HEAD_SIZE * 1.16 * 0.56, br, self._accent, a)

    # stats: evenly spaced columns; each value (+ small unit, one baseline) centered over its label
    vs, us, ls = VAL_SIZE, UNIT_SIZE, LBL_SIZE
    vy, ly = y + VAL_Y, y + LBL_Y
    slots = ds.column_slots(self._cols, w - 2 * PAD,
                         lambda v, u: measure_text_cached(bold, v, vs).x + (UNIT_GAP + measure_text_cached(bold, u, us).x if u else 0),
                         lambda lbl: measure_text_cached(roman, lbl, ls).x)
    for (v, u, lbl), (center, vw, lw) in zip(self._cols, slots, strict=False):
      sx = x + PAD + center
      v0 = sx - vw / 2
      rl.draw_text_ex(bold, v, rl.Vector2(v0, vy), vs, 0, _col(WHITE, VALUE_A * a))
      if u:
        ux = v0 + measure_text_cached(bold, v, vs).x + UNIT_GAP
        uy = vy + (vs - us) * ASCENT * 1.16
        rl.draw_text_ex(bold, u, rl.Vector2(ux, uy), us, 0, _col(WHITE, DIM_A * a))
      rl.draw_text_ex(roman, lbl, rl.Vector2(sx - lw / 2, ly), ls, 0, _col(WHITE, DIM_A * a))

    self.draw_timeline(x + PAD, y + TL_Y, w - 2 * PAD, TL_H, str(self._drive.get("tl") or "") if self._drive else "", a)
    draw_trip_block(roman, bold, x + PAD, y + TRIP_Y, w - 2 * PAD, self._today, self._week, alpha=a)

  @staticmethod
  def draw_timeline(x: float, y: float, w: float, h: float, codes: str, a: float = 1.0) -> None:
    """connect-style status bar with rounded ends: a round cap in the first / last run's color at
    each end, then every run drawn square between the caps' centers (so even a run thinner than
    the cap keeps the pill shape at any thickness)."""
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 1.0, 8, _col(WHITE, 0.15 * a))
    n = len(codes)
    if n == 0:
      return
    runs = ds.timeline_runs(codes)
    r = h / 2
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, h, h), 1.0, 8, _col(ds.COLORS[runs[0][0]], a))
    rl.draw_rectangle_rounded(rl.Rectangle(x + w - h, y, h, h), 1.0, 8, _col(ds.COLORS[runs[-1][0]], a))
    lo, hi = x + r, x + w - r
    for st, start, length in runs:
      x0 = max(lo, round(x + w * start / n))
      x1 = min(hi, round(x + w * (start + length) / n))
      if x1 > x0:
        rl.draw_rectangle_rec(rl.Rectangle(x0, y, max(1, x1 - x0), h), _col(ds.COLORS[st], a))
    # connect's status gradient: a little darker toward the bottom (inset from the rounded ends)
    rl.draw_rectangle_gradient_v(int(x + r), int(y), int(w - 2 * r), int(h), _col((0, 0, 0), 0), _col((0, 0, 0), 0.35 * a))
