"""Trip summary card: the onroad page's content while the car is parked or off.

begin() when a trip ends: it slides in over ENTER_S and stays the onroad page's content until
clear() (the next drive), so swiping back from home shows it again. update() returns True once,
SHOW_S after begin, if it's still in view: time for the stock scroll to home.

Optional hook: stats_fn() -> today_m/today_e/week_m/week_e/streak_days (else drive_summary's own totals).
"""
from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.lib import drive_summary as ds
from openpilot.selfdrive.ui.mici.widgets.trip_row import draw_trip_block, fmt_trip
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

ENTER_S = 0.28            # slide in from above, cubic ease-out, never past the top
PAD = 18
BADGE_GAP = 14
UNIT_GAP = 2
HEADLINE = "trip summary"
HEAD_SIZE, HEAD_Y = 62, 2          # alert text1 is 70-82 Inter Bold; 62 leaves room for the stats
VAL_SIZE, UNIT_SIZE, LBL_SIZE = 46, 24, 22
VAL_Y, LBL_Y = 80, 130
TL_Y, TL_H = 161, 18        # 1.5x the first 12 px bar: readable on the small screen; 8 px under the labels
TRIP_Y = 189
WHITE = (255, 255, 255)
ASCENT = 0.80              # Inter baseline as a fraction of the raylib font size (x FONT_SCALE in draw)


def _col(rgb, a: float) -> rl.Color:
  return rl.Color(rgb[0], rgb[1], rgb[2], max(0, min(255, int(255 * a))))


VALUE_COL, DIM_COL = _col(WHITE, 0.9), _col(WHITE, 0.65)
TRACK_COL, SHADE_COL = _col(WHITE, 0.15), _col((0, 0, 0), 0.35)
RUN_COLS = {st: _col(rgb, 1.0) for st, rgb in ds.COLORS.items()}


def draw_check_badge(cx: float, cy: float, r: float, rgb) -> None:
  rl.draw_circle_v(rl.Vector2(cx, cy), r, _col(rgb, 1.0))
  t = max(3.0, r * 0.22)
  p1 = rl.Vector2(cx - r * 0.45, cy + r * 0.02)
  p2 = rl.Vector2(cx - r * 0.12, cy + r * 0.36)
  p3 = rl.Vector2(cx + r * 0.48, cy - r * 0.32)
  white = _col(WHITE, 1.0)
  rl.draw_line_ex(p1, p2, t, white)
  rl.draw_line_ex(p2, p3, t, white)
  rl.draw_circle_v(p2, t / 2, white)


def slide_y(t: float, h: float) -> float:
  p = min(1.0, max(0.0, t / ENTER_S))
  return -h * (1.0 - p) ** 3


class DriveSummaryCard:
  def __init__(self, stats_fn: Callable[[], dict] | None = None):
    self._stats_fn = stats_fn
    self.drive: dict | None = None
    self._shown_at = 0.0
    self._holding = False
    self._cols: list[tuple[str, str, str]] = []
    self._slots: list[tuple[float, float, float]] = []
    self._slots_w = -1.0
    self._runs: list[tuple[int, int, int]] = []
    self._n_buckets = 0
    self._today = ("Today ", "")
    self._week = ("Week ", "")
    self._accent: tuple[int, int, int] = ds.COMMA_GREEN

  def begin(self) -> bool:
    """The trip just ended: True if it's long enough for a card and the card is up."""
    try:
      params = ui_state.params
      drive = ds.due_summary()
      if drive is None:
        return False
      self._load_texts(drive, ds.add_drive(ds.get_json(params, ds.PARAM_LAST), drive))   # Today/Week incl. this trip
    except Exception:
      return False
    self.drive, self._shown_at, self._holding = drive, time.monotonic(), True
    return True

  def clear(self) -> None:
    self.drive, self._holding = None, False

  def update(self, in_view: bool) -> bool:
    if not self._holding:
      return False
    t = time.monotonic() - self._shown_at
    if t >= ds.SHOW_S or (not in_view and t > ENTER_S):   # time's up, or tapped / swiped away
      self._holding = False
      return in_view
    return False

  def render(self, rect: rl.Rectangle) -> bool:
    if self.drive is None:
      return False
    self.draw(rect.x, rect.y + slide_y(time.monotonic() - self._shown_at, rect.height), rect.width, rect.height)
    return True

  def _load_texts(self, drive: dict, data: dict | None) -> None:
    metric = bool(ui_state.is_metric)
    st: dict = {}
    if self._stats_fn is not None:
      try:
        st = self._stats_fn() or {}
      except Exception:
        st = {}
    if "today_m" not in st:
      st = {**ds.today_week(data), "streak_days": ds.day_streak(data)}
    self._accent = ds.accent_rgb()
    self._cols = ds.card_columns(drive, int(st.get("streak_days") or 0), metric)
    self._slots_w = -1.0
    tl = str(drive.get("tl") or "")
    self._runs, self._n_buckets = ds.timeline_runs(tl), len(tl)
    self._today = ("Today ", fmt_trip(float(st.get("today_m") or 0), float(st.get("today_e") or 0), metric))
    self._week = ("Week ", fmt_trip(float(st.get("week_m") or 0), float(st.get("week_e") or 0), metric))

  def draw(self, x: float, y: float, w: float, h: float) -> None:
    rl.draw_rectangle(int(x), int(y), int(w), int(h), rl.BLACK)   # opaque, over the camera while parking

    bold = gui_app.font(FontWeight.DISPLAY)
    roman = gui_app.font(FontWeight.ROMAN)
    cx = x + PAD

    rl.draw_text_ex(bold, HEADLINE, rl.Vector2(cx, y + HEAD_Y), HEAD_SIZE, 0, VALUE_COL)
    br = HEAD_SIZE * 0.30
    hw = measure_text_cached(bold, HEADLINE, HEAD_SIZE).x
    bcx = min(cx + hw + BADGE_GAP + br, x + w - PAD - br)
    draw_check_badge(bcx, y + HEAD_Y + HEAD_SIZE * 1.16 * 0.56, br, self._accent)

    # stats: evenly spaced columns, each value (+ unit on its baseline) centered over its label
    vs, us, ls = VAL_SIZE, UNIT_SIZE, LBL_SIZE
    vy, ly = y + VAL_Y, y + LBL_Y
    if self._slots_w != w:
      self._slots_w = w
      self._slots = ds.column_slots(self._cols, w - 2 * PAD,
                                    lambda v, u: measure_text_cached(bold, v, vs).x + (UNIT_GAP + measure_text_cached(bold, u, us).x if u else 0),
                                    lambda lbl: measure_text_cached(roman, lbl, ls).x)
    for (v, u, lbl), (center, vw, lw) in zip(self._cols, self._slots, strict=False):
      sx = x + PAD + center
      v0 = sx - vw / 2
      rl.draw_text_ex(bold, v, rl.Vector2(v0, vy), vs, 0, VALUE_COL)
      if u:
        ux = v0 + measure_text_cached(bold, v, vs).x + UNIT_GAP
        uy = vy + (vs - us) * ASCENT * 1.16
        rl.draw_text_ex(bold, u, rl.Vector2(ux, uy), us, 0, DIM_COL)
      rl.draw_text_ex(roman, lbl, rl.Vector2(sx - lw / 2, ly), ls, 0, DIM_COL)

    self.draw_timeline(x + PAD, y + TL_Y, w - 2 * PAD, TL_H, self._runs, self._n_buckets)
    draw_trip_block(roman, bold, x + PAD, y + TRIP_Y, w - 2 * PAD, self._today, self._week)

  @staticmethod
  def draw_timeline(x: float, y: float, w: float, h: float, runs: list[tuple[int, int, int]], n: int) -> None:
    """connect-style status bar: round caps in the first / last run's color, runs drawn square between
    the caps' centers, so even a run thinner than the cap keeps the pill shape."""
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 1.0, 8, TRACK_COL)
    if n == 0:
      return
    r = h / 2
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, h, h), 1.0, 8, RUN_COLS[runs[0][0]])
    rl.draw_rectangle_rounded(rl.Rectangle(x + w - h, y, h, h), 1.0, 8, RUN_COLS[runs[-1][0]])
    lo, hi = x + r, x + w - r
    for st, start, length in runs:
      x0 = max(lo, round(x + w * start / n))
      x1 = min(hi, round(x + w * (start + length) / n))
      if x1 > x0:
        rl.draw_rectangle_rec(rl.Rectangle(x0, y, max(1, x1 - x0), h), RUN_COLS[st])
    # connect's status gradient: a little darker toward the bottom
    rl.draw_rectangle_gradient_v(int(x + r), int(y), int(w - 2 * r), int(h), rl.Color(0, 0, 0, 0), SHADE_COL)
