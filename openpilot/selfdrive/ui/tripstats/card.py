"""Pure formatting for the drive summary card: show rule, stat columns, timeline runs, accent color."""
from __future__ import annotations

from openpilot.selfdrive.ui.tripstats.recorder import CODES, MANUAL
from openpilot.selfdrive.ui.tripstats.store import engaged_pct

MIN_SHOW_M = 160.9           # 0.1 mi: shorter drives never show the card
MIN_SHOW_S = 30.0
COL_GAP = 10                 # minimum space between neighboring stat columns
COMMA_GREEN = (0x17, 0x86, 0x45)   # comma connect's engagedGreen, same as the timeline's engaged color


def eligible(drive: dict | None) -> bool:
  """Long enough for a card: >= 0.1 mi and >= 30 s."""
  return bool(drive) and float(drive.get("m") or 0) >= MIN_SHOW_M and float(drive.get("dur") or 0) >= MIN_SHOW_S


def fmt_dist(meters: float, metric: bool) -> tuple[str, str]:
  d = meters / 1000.0 if metric else meters / 1609.344
  return (f"{d:.1f}" if d < 9.95 else f"{int(round(d))}"), ("km" if metric else "mi")


def card_columns(drive: dict, streak_days: int, metric: bool) -> list[tuple[str, str, str]]:
  """(value, unit, label) columns; the last (best stretch) is dropped by the card if it doesn't fit."""
  m, e, best = float(drive.get("m") or 0), float(drive.get("e") or 0), float(drive.get("best_m") or 0)
  dv, du = fmt_dist(m, metric)
  bv, bu = fmt_dist(best, metric)
  return [(dv, du, "driven"), (str(engaged_pct(e, m)), "%", "engaged"),
          (str(int(streak_days)), "", "day streak"), (bv, bu, "best stretch")]


def column_slots(cols, avail: float, value_w, label_w, gap: float = COL_GAP) -> list[tuple[float, float, float]]:
  """[(center x, value width, label width)] in equal slots of avail / n. Trailing columns drop
  (never below 3) while neighbors would come closer than gap or an edge column would overflow."""
  widths = [(value_w(v, u), label_w(lbl)) for v, u, lbl in cols]

  def fits(n: int) -> bool:
    slot = avail / n
    ws = [max(vw, lw) for vw, lw in widths[:n]]
    return (all((a + b) / 2 + gap <= slot for a, b in zip(ws, ws[1:], strict=False)) and
            ws[0] <= slot and ws[-1] <= slot)

  n = len(cols)
  while n > 3 and not fits(n):
    n -= 1
  slot = avail / max(1, n)
  return [(slot * (i + 0.5), vw, lw) for i, (vw, lw) in enumerate(widths[:n])]


def timeline_runs(codes: str) -> list[tuple[int, int, int]]:
  """Run-length (status, start, length) over the bucket codes."""
  runs: list[tuple[int, int, int]] = []
  for i, ch in enumerate(codes):
    st = CODES.find(ch)
    st = MANUAL if st < 0 else st
    if runs and runs[-1][0] == st:
      runs[-1] = (st, runs[-1][1], runs[-1][2] + 1)
    else:
      runs.append((st, i, 1))
  return runs


def accent_rgb() -> tuple[int, int, int]:
  """The fork's theme color (read live, so a theme change shows on the next frame).
  The stock openpilot theme, or no theme manager, uses comma green to match the timeline."""
  try:
    from openpilot.selfdrive.ui.layouts.settings.common import theme_rgb, THEME_OPENPILOT_RGB
    rgb = tuple(theme_rgb())
    if rgb == tuple(THEME_OPENPILOT_RGB):
      return COMMA_GREEN
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return r, g, b
  except Exception:
    return COMMA_GREEN
