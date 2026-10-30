"""The "Day 52mi 24%   Week 330mi 64%" row (home) and block (trip card)."""
from __future__ import annotations

import pyray as rl

from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.tripstats.store import engaged_pct

GREY = rl.Color(200, 200, 200, 255)   # secondary text on home and the card: readable in daylight
WHITE = rl.Color(255, 255, 255, 255)
ROW_GAP = 14             # between Day and Week on home
HOME_LABEL = 34          # grey roman label on home, as big as the value
BLOCK_LABEL = 30          # grey roman label on the card
BLOCK_VALUE = 34          # white Inter Bold value (home + card)


def fmt_trip(meters: float, eng_m: float, metric: bool) -> str:
  dist, unit = (meters / 1000.0, "km") if metric else (meters / 1609.344, "mi")
  return f"{int(round(dist))}{unit} {engaged_pct(eng_m, meters)}%"


def _fit(roman: rl.Font, bold: rl.Font, pairs, ls: int, avail_fn) -> tuple[int, int]:
  """Label / value sizes from ls / BLOCK_VALUE, shrinking together until avail_fn(widths) holds."""
  vs = BLOCK_VALUE
  while ls > 20 and not avail_fn([(measure_text_cached(roman, lbl, ls).x, measure_text_cached(bold, val, vs).x) for lbl, val in pairs]):
    ls, vs = ls - 1, vs - 1
  return ls, vs


def _draw_pair(roman: rl.Font, bold: rl.Font, x: float, y: float, lbl: str, val: str, ls: int, vs: int) -> float:
  """Grey roman label + white bold value on one baseline (the card's stat style). Returns the end x."""
  rl.draw_text_ex(roman, lbl, rl.Vector2(x, y + (vs - ls) * 0.8 * 1.16), ls, 0, GREY)
  x += measure_text_cached(roman, lbl, ls).x + 10
  rl.draw_text_ex(bold, val, rl.Vector2(x, y), vs, 0, WHITE)
  return x + measure_text_cached(bold, val, vs).x


def draw_trip_row(roman: rl.Font, bold: rl.Font, x: float, y: float, avail: float, day_txt: tuple[str, str],
                  week_txt: tuple[str, str]) -> tuple[float, int]:
  """Home: Day / Week on one line, the card's fonts and colors, label as big as the value. Returns (width, value size)."""
  ls, vs = _fit(roman, bold, (day_txt, week_txt), HOME_LABEL, lambda ws: sum(lw + 10 + vw for lw, vw in ws) + ROW_GAP <= avail)
  end = _draw_pair(roman, bold, x, y, *day_txt, ls, vs)
  end = _draw_pair(roman, bold, end + ROW_GAP, y, *week_txt, ls, vs)
  return end - x, vs


def draw_trip_block(roman: rl.Font, bold: rl.Font, x: float, y: float, w: float, day_txt: tuple[str, str],
                    week_txt: tuple[str, str]) -> None:
  """Card: two columns, grey label + white bold value on one baseline, shrinking together to fit."""
  col_w = w / 2
  ls, vs = _fit(roman, bold, (day_txt, week_txt), BLOCK_LABEL, lambda ws: all(lw + 10 + vw <= col_w - 12 for lw, vw in ws))
  for i, (lbl, val) in enumerate((day_txt, week_txt)):
    _draw_pair(roman, bold, x + i * col_w, y, lbl, val, ls, vs)
