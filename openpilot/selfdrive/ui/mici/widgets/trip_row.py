"""The "Today 52mi 24%   Week 330mi 64%" row (home) and block (trip card)."""
from __future__ import annotations

import pyray as rl

from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.lib.drive_summary import engaged_pct

GREY = rl.Color(200, 200, 200, 255)   # secondary text on home and the card: readable in daylight
WHITE = rl.Color(255, 255, 255, 255)
ROW_GAP = 16
BLOCK_LABEL = 30          # grey label, home style but bigger
BLOCK_VALUE = 34          # white bold value


def fmt_trip(meters: float, eng_m: float, metric: bool) -> str:
  dist, unit = (meters / 1000.0, "km") if metric else (meters / 1609.344, "mi")
  return f"{int(round(dist))}{unit} {engaged_pct(eng_m, meters)}%"


def draw_trip_row(font: rl.Font, x: float, y: float, avail: float, last_txt: tuple[str, str],
                  week_txt: tuple[str, str]) -> tuple[float, int]:
  """Labels at lsz, values at lsz - 6 on one band, shrinking together to fit avail. Returns (width, lsz)."""
  ll, lv = last_txt
  wl, wv = week_txt
  lsz = 36
  while lsz > 22:
    vsz = max(18, lsz - 6)
    w = (measure_text_cached(font, ll, lsz).x + measure_text_cached(font, lv, vsz).x +
         ROW_GAP + measure_text_cached(font, wl, lsz).x + measure_text_cached(font, wv, vsz).x)
    if w <= avail:
      break
    lsz -= 1
  vsz = max(18, lsz - 6)
  x0 = x
  vy = y + (lsz - vsz)
  rl.draw_text_ex(font, ll, rl.Vector2(x, y), lsz, 0, GREY)
  x += measure_text_cached(font, ll, lsz).x
  rl.draw_text_ex(font, lv, rl.Vector2(x, vy), vsz, 0, WHITE)
  x += measure_text_cached(font, lv, vsz).x + ROW_GAP
  rl.draw_text_ex(font, wl, rl.Vector2(x, y), lsz, 0, GREY)
  x += measure_text_cached(font, wl, lsz).x
  rl.draw_text_ex(font, wv, rl.Vector2(x, vy), vsz, 0, WHITE)
  x += measure_text_cached(font, wv, vsz).x
  return x - x0, lsz


def draw_trip_block(roman: rl.Font, bold: rl.Font, x: float, y: float, w: float, last_txt: tuple[str, str],
                    week_txt: tuple[str, str]) -> None:
  """Two columns, grey label + white bold value on one baseline, shrinking together to fit."""
  col_w = w / 2
  ls, vs = BLOCK_LABEL, BLOCK_VALUE
  while ls > 20:
    fits = all(measure_text_cached(roman, lbl.strip(), ls).x + 10 + measure_text_cached(bold, val, vs).x <= col_w - 12
               for lbl, val in (last_txt, week_txt))
    if fits:
      break
    ls, vs = ls - 1, vs - 1
  for i, (lbl, val) in enumerate((last_txt, week_txt)):
    cx = x + i * col_w
    lbl = lbl.strip()
    rl.draw_text_ex(roman, lbl, rl.Vector2(cx, y + (vs - ls) * 0.8 * 1.16), ls, 0, GREY)
    rl.draw_text_ex(bold, val, rl.Vector2(cx + measure_text_cached(roman, lbl, ls).x + 10, y), vs, 0, WHITE)
