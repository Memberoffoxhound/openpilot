"""Drive summary card and Home row: layout rules and hooks in the UI files. No raylib needed.
The recorder, store and card formatting are tested in selfdrive/ui/tripstats/tests."""
from pathlib import Path

from openpilot.selfdrive.ui import tripstats as ts

UI = Path(__file__).resolve().parents[1]


def test_ui_hooks_present():
  main = (UI / "mici/layouts/main.py").read_text()
  assert "tripstats.tick(ui_state)" in main
  assert "draw_trip_row(" in (UI / "mici/layouts/home.py").read_text()


def test_home_text_daylight_readable():
  """Home and card text: full white primary, >= 200 grey secondary (raylib GRAY 130 washed out in sun)."""
  import re
  row = (UI / "mici/widgets/trip_row.py").read_text()
  assert "GREY = rl.Color(200, 200, 200, 255)" in row and "WHITE = rl.Color(255, 255, 255, 255)" in row
  home = (UI / "mici/layouts/home.py").read_text()
  assert "rl.GRAY" not in home and "0.9))" not in home.split("class MiciHomeLayout")[1]
  assert home.count("text_color=") == 3 and "text_color=WHITE" not in home   # version/date/branch: card label grey
  # home's Today/Week row is the card's stat style: roman grey label + Inter Bold (DISPLAY) white value
  assert "draw_trip_row(gui_app.font(FontWeight.ROMAN), gui_app.font(FontWeight.DISPLAY)" in home
  card = (UI / "mici/widgets/drive_summary_card.py").read_text()
  value, dim = map(float, re.search(r"VALUE_COL, DIM_COL = _col\(WHITE, ([\d.]+)\), _col\(WHITE, ([\d.]+)\)", card).groups())
  assert value == 1.0 and dim >= 0.78


def test_card_layout_rules():
  """Alert-style card: opaque full screen (no home icons under it, no timer dots), Inter Bold lowercase
  headline as the biggest text, two-column Today/Week block, everything inside 240 px."""
  import ast
  src = (UI / "mici/widgets/drive_summary_card.py").read_text()
  consts = {}
  for node in ast.parse(src).body:
    if isinstance(node, ast.Assign):
      for tgt in node.targets:
        names = [tgt] if isinstance(tgt, ast.Name) else list(getattr(tgt, "elts", []))
        vals = [node.value] if isinstance(tgt, ast.Name) else list(getattr(node.value, "elts", []))
        for n, v in zip(names, vals, strict=False):
          if isinstance(n, ast.Name) and isinstance(v, ast.Constant):
            consts[n.id] = v.value
  assert 0.25 <= consts["ENTER_S"] <= 0.3
  assert consts["HEADLINE"] == consts["HEADLINE"].lower() == "trip summary"
  draw_src = src.split("def draw(self")[1].split("def draw_timeline")[0]
  # badge right of the headline: headline drawn at the left pad, badge center after its measured width
  assert "rl.Vector2(cx, y + HEAD_Y + (HEAD_SIZE - hs)" in draw_src and "cx + hw + BADGE_GAP + br" in draw_src
  # a headline too wide for the badge shrinks (same baseline); "trip summary" never does
  assert consts["LAST_HEADLINE"] == "last trip summary" and consts["VAL_SIZE"] < consts["HEAD_MIN"] < consts["HEAD_SIZE"]
  assert "while hw > room and hs > HEAD_MIN" in draw_src
  assert draw_src.index("draw_text_ex(bold, self._head") < draw_src.index("draw_check_badge(")
  assert "br, tc.accent_rgb())" in draw_src and "_accent" not in src   # badge reads the theme live, no stale copy
  assert "tc.column_slots(" in draw_src and "sx - lw / 2" in draw_src and "sx - vw / 2" in draw_src
  assert "drive" not in " ".join(v for k, v in consts.items() if isinstance(v, str))
  assert consts["HEAD_SIZE"] > consts["VAL_SIZE"] > consts["LBL_SIZE"]
  assert consts["HEAD_Y"] < consts["VAL_Y"] < consts["LBL_Y"] < consts["TL_Y"] < consts["TRIP_Y"]
  assert consts["TRIP_Y"] + 34 * 1.16 <= 240
  # thicker route bar (1.5x the original 12 px), clear of the labels above and the Today/Week text below
  assert consts["TL_H"] == 18
  assert consts["LBL_Y"] + consts["LBL_SIZE"] * 1.16 + 4 <= consts["TL_Y"]
  assert consts["TL_Y"] + consts["TL_H"] + 6 <= consts["TRIP_Y"]
  assert "draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 1.0" in src     # rounded ends kept
  assert "FontWeight.DISPLAY" in src and "draw_trip_block(" in src
  row = (UI / "mici/widgets/trip_row.py").read_text()
  assert "def draw_trip_block(" in row and "BLOCK_VALUE = 34" in row and "BLOCK_LABEL = 30" in row


def test_show_time_is_twenty_seconds():
  assert ts.SHOW_S == 20.0
  assert sum(ln.startswith("SHOW_S =") for ln in (UI / "tripstats/__init__.py").read_text().splitlines()) == 1


def test_home_row_day_label_fit(monkeypatch):
  """Home: "Day" label as big as the value with values at full size when it fits; both shrink together, never past avail."""
  import importlib
  import sys
  import types

  def measure(font, text, size):
    return types.SimpleNamespace(x=0.5 * size * len(text))

  monkeypatch.setitem(sys.modules, "openpilot.system.ui.lib.text_measure", types.SimpleNamespace(measure_text_cached=measure))
  monkeypatch.delitem(sys.modules, "openpilot.selfdrive.ui.mici.widgets.trip_row", raising=False)   # fresh import, dropped after
  tr = importlib.import_module("openpilot.selfdrive.ui.mici.widgets.trip_row")
  assert tr.HOME_LABEL == tr.BLOCK_VALUE == 34 and tr.ROW_GAP == 14 and tr.BLOCK_LABEL == 30
  for src in ("mici/layouts/home.py", "mici/widgets/drive_summary_card.py"):
    assert '("Day", ' in (UI / src).read_text() and '"Today ' not in (UI / src).read_text()
  monkeypatch.setattr(tr, "_draw_pair", lambda r, b, x, y, lbl, val, ls, vs: x + tr.measure_text_cached(0, lbl, ls).x + 10 +
                      tr.measure_text_cached(0, val, vs).x)
  row = (("Day", "52mi 24%"), ("Week", "330mi 64%"))
  need = sum(0.5 * 34 * (len(lbl) + len(val)) + 10 for lbl, val in row) + tr.ROW_GAP
  assert tr.draw_trip_row(None, None, 0, 0, need, *row) == (need, 34)
  w, vs = tr.draw_trip_row(None, None, 0, 0, need - 1, *row)
  assert vs == 33 and w <= need - 1
