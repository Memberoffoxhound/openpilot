"""The home screen's "Today 52mi 24%   Week 330mi 64%" row, shared by home and the drive-summary card.

Labels at lsz in grey, values at lsz - 6 in white on the same baseline band,
shrinking together until the row fits avail.
"""
from __future__ import annotations

import pyray as rl

from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.lib.drive_summary import engaged_pct

LABEL_WHITE_A = int(255 * 0.9)
GRAY_RGB = (130, 130, 130)   # raylib GRAY, which home used for the labels
ROW_GAP = 16


def fmt_trip(meters: float, eng_m: float, metric: bool) -> str:
  if metric:
    dist, unit = meters / 1000.0, "km"
  else:
    dist, unit = meters / 1609.344, "mi"
  return f"{int(round(dist))}{unit} {engaged_pct(eng_m, meters)}%"


def fit_trip_row(font: rl.Font, last_txt: tuple[str, str], week_txt: tuple[str, str], avail: float,
                 max_size: int = 36) -> tuple[int, int]:
  ll, lv = last_txt
  wl, wv = week_txt
  lsz = max_size
  while lsz > 22:
    vsz = max(18, lsz - 6)
    w = (measure_text_cached(font, ll, lsz).x + measure_text_cached(font, lv, vsz).x +
         ROW_GAP + measure_text_cached(font, wl, lsz).x + measure_text_cached(font, wv, vsz).x)
    if w <= avail:
      break
    lsz -= 1
  return lsz, max(18, lsz - 6)


def draw_trip_row(font: rl.Font, x: float, y: float, avail: float, last_txt: tuple[str, str], week_txt: tuple[str, str],
                  alpha: float = 1.0, max_size: int = 36) -> tuple[float, int]:
  """Draw the row with its top at y. Returns (width drawn, label size)."""
  ll, lv = last_txt
  wl, wv = week_txt
  lsz, vsz = fit_trip_row(font, last_txt, week_txt, avail, max_size)
  grey = rl.Color(*GRAY_RGB, int(255 * alpha))
  white = rl.Color(255, 255, 255, int(LABEL_WHITE_A * alpha))
  x0 = x
  vy = y + (lsz - vsz)
  rl.draw_text_ex(font, ll, rl.Vector2(x, y), lsz, 0, grey)
  x += measure_text_cached(font, ll, lsz).x
  rl.draw_text_ex(font, lv, rl.Vector2(x, vy), vsz, 0, white)
  x += measure_text_cached(font, lv, vsz).x + ROW_GAP
  rl.draw_text_ex(font, wl, rl.Vector2(x, y), lsz, 0, grey)
  x += measure_text_cached(font, wl, lsz).x
  rl.draw_text_ex(font, wv, rl.Vector2(x, vy), vsz, 0, white)
  x += measure_text_cached(font, wv, vsz).x
  return x - x0, lsz


BLOCK_LABEL = 30          # grey label, home style but bigger
BLOCK_VALUE = 34          # white bold value


def draw_trip_block(roman: rl.Font, bold: rl.Font, x: float, y: float, w: float, last_txt: tuple[str, str],
                    week_txt: tuple[str, str], alpha: float = 1.0) -> None:
  """Two columns, "Today  7mi 81%" | "Week  42mi 64%": grey regular label, white bold value, larger than
  the home row and on one baseline. Sizes shrink together if a column doesn't fit."""
  col_w = w / 2
  ls, vs = BLOCK_LABEL, BLOCK_VALUE
  while ls > 20:
    fits = all(measure_text_cached(roman, lbl.strip(), ls).x + 10 + measure_text_cached(bold, val, vs).x <= col_w - 12
               for lbl, val in (last_txt, week_txt))
    if fits:
      break
    ls, vs = ls - 1, vs - 1
  grey = rl.Color(*GRAY_RGB, int(255 * alpha))
  white = rl.Color(255, 255, 255, int(LABEL_WHITE_A * alpha))
  for i, (lbl, val) in enumerate((last_txt, week_txt)):
    cx = x + i * col_w
    lbl = lbl.strip()
    # values are taller: drop the label so both sit on one baseline
    rl.draw_text_ex(roman, lbl, rl.Vector2(cx, y + (vs - ls) * 0.8 * 1.16), ls, 0, grey)
    rl.draw_text_ex(bold, val, rl.Vector2(cx + measure_text_cached(roman, lbl, ls).x + 10, y), vs, 0, white)
