"""S3XYPilot statistics. Three snap widgets on the C4 536x240."""
from __future__ import annotations

import math
import time

import pyray as rl

from openpilot.selfdrive.ui.layouts.settings.common import spawn_trip_job, theme_color
from openpilot.selfdrive.ui.layouts.settings.trip_seed import chicago_now
from openpilot.selfdrive.ui.layouts.settings.trip_stats import stats_view
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller

TESLA_GREEN = rl.Color(80, 230, 150, 255)
WHITE = rl.Color(255, 255, 255, int(255 * 0.9))
BLACK = rl.Color(0, 0, 0, 255)
LABEL = rl.Color(142, 142, 147, 255)
DIM = rl.Color(100, 100, 100, 255)
TRACK = rl.Color(42, 42, 48, 255)
BAR = rl.Color(170, 170, 170, 255)
WEEKDAYS_H = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _metric() -> bool:
  return bool(ui_state.is_metric)


def _unit_m() -> float:
  return 1000.0 if _metric() else 1609.344


def _fmt_dist(meters: float, tenths: bool = False) -> str:
  v, u = meters / _unit_m(), ("km" if _metric() else "mi")
  if tenths and v < 100:
    txt = f"{v:.1f}"
  elif v >= 1000:
    txt = f"{v:,.0f}"
  else:
    txt = f"{v:.0f}"
  return f"{txt} {u}"


def _fmt_pair(eng: float, tot: float) -> str:
  u = "km" if _metric() else "mi"

  def _n(m: float) -> str:
    v = m / _unit_m()
    if v >= 1000:
      return f"{v:,.0f}"
    if 0 < v < 10:
      return f"{v:.1f}"
    return f"{v:.0f}"

  return f"{_n(eng)} / {_n(tot)} {u}"


def _draw_check(cx: float, cy: float, r: float, on: bool) -> None:
  if on:
    rl.draw_circle(int(cx), int(cy), r, theme_color())
    p1 = rl.Vector2(cx - r * 0.40, cy + r * 0.04)
    p2 = rl.Vector2(cx - r * 0.08, cy + r * 0.40)
    p3 = rl.Vector2(cx + r * 0.46, cy - r * 0.34)
    rl.draw_line_ex(p1, p2, max(3.0, r * 0.28), WHITE)
    rl.draw_line_ex(p2, p3, max(3.0, r * 0.28), WHITE)
  else:
    rl.draw_ring(rl.Vector2(cx, cy), r - 2.2, r, 0, 360, 28, DIM)


def _nice_top_m(peak_m: float) -> float:
  u = _unit_m()
  v = max(0.0, peak_m) / u
  if v <= 0:
    return u
  mag = 10 ** math.floor(math.log10(v))
  for m in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
    if v <= m * mag + 1e-9:
      return m * mag * u
  return 10 * mag * u


def _draw_hbars(rect: rl.Rectangle, totals: list[float], engaged: list[float],
                current: int, labels: list[str]) -> None:
  n = max(1, len(totals))
  scale = _nice_top_m(max(totals) if totals else 0.0)
  gap = 3.0
  row_h = max(22.0, (rect.height - gap * (n - 1)) / n)
  lab_sz = 28 if row_h >= 30 else 24
  val_sz = 26 if row_h >= 30 else 22
  if row_h < 26:
    lab_sz = val_sz = 22
  lfont = gui_app.font(FontWeight.ROMAN)
  vfont = gui_app.font(FontWeight.BOLD)
  label_w = 8.0
  for lab in labels:
    label_w = max(label_w, measure_text_cached(lfont, lab, lab_sz).x + 10)
  track_x = rect.x + label_w
  track_w = max(40.0, rect.width - label_w)
  bar_h = max(18.0, row_h - 2)
  accent = theme_color()
  for i, tot in enumerate(totals):
    eng = engaged[i] if i < len(engaged) else 0.0
    y = rect.y + i * (row_h + gap)
    cy = y + row_h / 2
    lab = labels[i] if i < len(labels) else ""
    lw = measure_text_cached(lfont, lab, lab_sz)
    rl.draw_text_ex(lfont, lab, rl.Vector2(rect.x, cy - lw.y / 2), lab_sz, 0, LABEL)
    ty = cy - bar_h / 2
    rl.draw_rectangle_rounded(rl.Rectangle(track_x, ty, track_w, bar_h), 0.35, 6, TRACK)
    tw = 0.0 if scale <= 0 else track_w * min(1.0, tot / scale)
    if tw > 6:
      fill_col = WHITE if i == current else BAR
      rl.draw_rectangle_rounded(rl.Rectangle(track_x, ty, tw, bar_h), 0.35, 6, fill_col)
    ew = 0.0 if scale <= 0 else track_w * min(1.0, eng / scale)
    if ew > 6:
      rl.draw_rectangle_rounded(rl.Rectangle(track_x, ty, ew, bar_h), 0.35, 6, accent)
    txt = _fmt_pair(eng, tot)
    vw = measure_text_cached(vfont, txt, val_sz)
    while val_sz > 16 and vw.x > track_w - 12:
      val_sz -= 1
      vw = measure_text_cached(vfont, txt, val_sz)
    pad_x = 10.0
    if tw >= vw.x + pad_x * 2:
      tx = track_x + pad_x
      if ew >= vw.x + pad_x * 2:
        ink = WHITE
      elif i == current:
        ink = BLACK
      else:
        ink = WHITE
    else:
      tx = min(track_x + max(tw + 8, pad_x), track_x + track_w - vw.x - 6)
      ink = WHITE
    rl.draw_text_ex(vfont, txt, rl.Vector2(tx, cy - vw.y / 2), val_sz, 0, ink)


class _StatsPage(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, float(gui_app.width), float(gui_app.height)))
    self._at = 0.0
    self._view: dict = stats_view()

  def _update_state(self):
    now = time.monotonic()
    if now - self._at < 1.0:
      return
    self._at = now
    self._view = stats_view()


class StatsEngageWidget(_StatsPage):
  def _render(self, _):
    v = self._view
    r = self.rect
    right = r.x + r.width - 18
    pad = 12.0
    lfont = gui_app.font(FontWeight.ROMAN)
    vfont = gui_app.font(FontWeight.BOLD)
    rows = (
      ("Total Miles", _fmt_dist(float(v.get("life_m") or 0)), WHITE),
      ("Engaged", _fmt_dist(float(v.get("life_e") or 0)), WHITE),
      ("Longest streak", _fmt_dist(float(v.get("longest_m") or 0), tenths=True), TESLA_GREEN),
    )
    sizes = ((36, 34, 36), (36, 32, 36), (34, 30, 34), (32, 28, 32))
    lab_sz = val_sz = tsz = 36
    gap_lv = 12.0
    pair_w = 0.0
    ring_d = 176.0
    for lab_sz, val_sz, tsz in sizes:
      pair_w = 0.0
      for label, val, _col in rows:
        pair_w = max(pair_w, measure_text_cached(lfont, label, lab_sz).x + gap_lv +
                     measure_text_cached(vfont, val, val_sz).x)
      ring_d = min(r.height - 8.0, right - pair_w - 16.0 - pad)
      if ring_d >= 170.0:
        break
    ring_d = max(164.0, min(220.0, ring_d))
    cx = r.x + pad + ring_d / 2
    cy = r.y + r.height / 2
    outer = ring_d / 2 - 1
    inner = outer - 13
    pct = int(v.get("pct") or 0)
    gap = 26.0
    start = 90.0 + gap / 2
    track_span = 360.0 - gap
    rl.draw_ring(rl.Vector2(cx, cy), inner, outer, start, start + track_span, 64, TRACK)
    if pct > 0:
      rl.draw_ring(rl.Vector2(cx, cy), inner, outer, start, start + track_span * (pct / 100.0), 64, theme_color())

    hole = inner * 2 - 12
    num = f"{pct}%"
    nfont = gui_app.font(FontWeight.DISPLAY)
    sfont = gui_app.font(FontWeight.BOLD)
    sub = "Engaged"
    nsz = 86
    nw = measure_text_cached(nfont, num, nsz)
    while nsz > 52 and nw.x > hole:
      nsz -= 2
      nw = measure_text_cached(nfont, num, nsz)
    ssz = 24
    sw = measure_text_cached(sfont, sub, ssz)
    while ssz > 14 and sw.x > hole:
      ssz -= 1
      sw = measure_text_cached(sfont, sub, ssz)
    block = nw.y + 2 + sw.y
    ny = cy - block / 2
    rl.draw_text_ex(nfont, num, rl.Vector2(cx - nw.x / 2, ny), nsz, 0, WHITE)
    rl.draw_text_ex(sfont, sub, rl.Vector2(cx - sw.x / 2, ny + nw.y + 1), ssz, 0, LABEL)

    y = r.y + 8
    streak = int(v.get("streak_days") or 0)
    title = f"{streak} Day Streak" if streak != 1 else "1 Day Streak"
    tfont = gui_app.font(FontWeight.BOLD)
    tw = measure_text_cached(tfont, title, tsz)
    rl.draw_text_ex(tfont, title, rl.Vector2(right - tw.x, y), tsz, 0, WHITE)
    y += 40

    week = v.get("week_days") or []
    cr = 13.0
    step = 30.0
    span = step * 7
    left = right - span
    for i in range(7):
      on = i < len(week) and float((week[i] or {}).get("e") or 0) > 1
      _draw_check(left + i * step + step / 2, y + cr, cr, on)
    y += 36

    val_col_w = max((measure_text_cached(vfont, val, val_sz).x for _l, val, _c in rows), default=0.0)
    row_h = max(40.0, (r.y + r.height - 8 - y) / 3)
    for label, val, col in rows:
      vw = measure_text_cached(vfont, val, val_sz)
      lw = measure_text_cached(lfont, label, lab_sz)
      mid = y + row_h / 2
      rl.draw_text_ex(vfont, val, rl.Vector2(right - vw.x, mid - vw.y / 2), val_sz, 0, col)
      rl.draw_text_ex(lfont, label, rl.Vector2(right - val_col_w - gap_lv - lw.x, mid - lw.y / 2), lab_sz, 0, LABEL)
      y += row_h


class StatsWeekHWidget(_StatsPage):
  def _render(self, _):
    v = self._view
    r = self.rect
    pad = 12.0
    font_b = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font_b, "Weekly Engaged", rl.Vector2(r.x + pad, r.y + 6), 36, 0, WHITE)
    right = _fmt_pair(float(v.get("week_e") or 0), float(v.get("week_m") or 0))
    rw = measure_text_cached(font_b, right, 30)
    rl.draw_text_ex(font_b, right, rl.Vector2(r.x + r.width - 18 - rw.x, r.y + 10), 30, 0, WHITE)
    week = v.get("week_days") or [{"m": 0.0, "e": 0.0}] * 7
    totals = [float(d.get("m") or 0) for d in week]
    engaged = [float(d.get("e") or 0) for d in week]
    current = (chicago_now().weekday() + 1) % 7
    chart = rl.Rectangle(r.x + pad, r.y + 46, r.width - pad - 18, r.height - 54)
    _draw_hbars(chart, totals, engaged, current, list(WEEKDAYS_H))


class StatsHistoryHWidget(_StatsPage):
  def _render(self, _):
    v = self._view
    r = self.rect
    pad = 12.0
    font_b = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font_b, "Monthly Engaged", rl.Vector2(r.x + pad, r.y + 6), 36, 0, WHITE)
    life = _fmt_pair(float(v.get("life_e") or 0), float(v.get("life_m") or 0))
    lw = measure_text_cached(font_b, life, 30)
    rl.draw_text_ex(font_b, life, rl.Vector2(r.x + r.width - 18 - lw.x, r.y + 10), 30, 0, WHITE)
    months = v.get("months") or []
    totals = [float(m.get("m") or 0) for m in months]
    engaged = [float(m.get("e") or 0) for m in months]
    current = 0
    labels = []
    for i, m in enumerate(months):
      try:
        mo = int(str(m.get("id") or "0-01").split("-")[1])
        labels.append(MONTHS[mo - 1])
      except (ValueError, IndexError):
        labels.append("")
      if m.get("current"):
        current = i
    chart = rl.Rectangle(r.x + pad, r.y + 46, r.width - pad - 18, r.height - 54)
    _draw_hbars(chart, totals, engaged, current, labels)


class StatsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._scroller._snap_items = True
    self._scroller._spacing = 0
    self._scroller._pad = 0
    self._items = (StatsEngageWidget(), StatsWeekHWidget(), StatsHistoryHWidget())
    self._scroller.add_widgets(list(self._items))
    self._folded = False

  def show_event(self):
    super().show_event()
    if not self._folded:
      self._folded = True
      spawn_trip_job("stats")
