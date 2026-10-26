"""Drive summary (selfdrive/ui/lib/drive_summary.py): recorder math, the
connect-style timeline buckets, persistence, show-once rules, Today/Week and
day-streak fallbacks, and the card formatting. No raylib needed."""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from openpilot.selfdrive.ui.lib import drive_summary as ds

UI = Path(__file__).resolve().parents[1]
MI = 1609.344


def drive(rec, seconds, v, enabled, t0, wall0=1_760_000_000.0, dt=0.05, **kw):
  t = t0
  while t < t0 + seconds - 1e-9:
    assert rec.update(True, t, wall0 + t, v, enabled, **kw) is None
    t += dt
  return t


# -- classify / palette ------------------------------------------------------------

def test_classify():
  assert ds.classify(True, "enabled", "normal", False, 20) == ds.ENGAGED
  assert ds.classify(True, "overriding", "normal", False, 20) == ds.OVERRIDE
  assert ds.classify(True, "enabled", "normal", True, 20) == ds.OVERRIDE       # gas while engaged
  assert ds.classify(False, "disabled", "normal", True, 20) == ds.MANUAL       # gas while manual is just manual
  assert ds.classify(False, "disabled", "normal", False, 0.0) == ds.STANDBY
  assert ds.classify(True, "enabled", "userPrompt", False, 20) == ds.PROMPT
  assert ds.classify(False, "disabled", "critical", False, 20) == ds.CRITICAL


def test_connect_palette():
  # commaai/connect src/theme.js palette.states / src/colors.js
  assert ds.COLORS[ds.ENGAGED] == (0x17, 0x86, 0x45)    # engagedGreen green400
  assert ds.COLORS[ds.MANUAL] == (0x17, 0x58, 0x86)     # drivingBlue blue500
  assert ds.COLORS[ds.PROMPT] == (0xda, 0x6f, 0x25)     # alertOrange orange50
  assert ds.COLORS[ds.CRITICAL] == (0xc9, 0x22, 0x31)   # alertRed red100
  assert ds.COLORS[ds.STANDBY] == (0x91, 0x9b, 0x95)    # engagedGrey
  assert ds.COLORS[ds.OVERRIDE] == (0xe3, 0xd7, 0x56)   # yellow500


# -- timeline --------------------------------------------------------------------------

def test_timeline_buckets_and_dominance():
  tl = ds.Timeline(n=8, bucket_s=1.0)
  tl.add(ds.ENGAGED, 2.0)
  tl.add(ds.MANUAL, 0.6)
  tl.add(ds.ENGAGED, 0.4)
  tl.add(ds.PROMPT, 0.05)           # any alert time colors the bucket
  assert tl.codes() == "eemp"


def test_timeline_constant_memory_compaction():
  tl = ds.Timeline(n=160, bucket_s=2.0)
  for i in range(3 * 3600 * 20):    # 3 h at 20 Hz
    tl.add(ds.ENGAGED if (i // 2000) % 4 else ds.MANUAL, 0.05)
  assert len(tl.buckets) == 160
  codes = tl.codes()
  assert 80 < len(codes) <= 160 and set(codes) == {"e", "m"}
  assert sum(sum(b) for b in tl.buckets) == pytest.approx(3 * 3600, rel=1e-6)


def test_timeline_crossing_a_bucket_edge_splits_time():
  tl = ds.Timeline(n=4, bucket_s=1.0)
  tl.add(ds.ENGAGED, 0.9)
  tl.add(ds.MANUAL, 0.3)
  assert tl.buckets[0][ds.MANUAL] == pytest.approx(0.1)
  assert tl.buckets[1][ds.MANUAL] == pytest.approx(0.2)


# -- recorder ---------------------------------------------------------------------------

def test_recorder_distance_engaged_best_stretch():
  rec = ds.DriveRecorder()
  t = drive(rec, 100, 20.0, True, 0.0, drive_id="r1")       # 2000 m engaged
  t = drive(rec, 10, 20.0, False, t)                         # 200 m manual
  assert rec.cur_m == 0
  t = drive(rec, 50, 20.0, True, t)                          # 1000 m engaged
  assert rec.cur_m == pytest.approx(1000, rel=0.01)
  t = drive(rec, 20, 0.0, False, t)                          # stopped
  assert rec.update(False, t, 1_760_000_000.0 + t, 0.0, False) is None          # offroad: wait MERGE_S
  out = rec.update(False, t + ds.MERGE_S, 1_760_000_000.0 + t + ds.MERGE_S, 0.0, False)
  assert out["id"] == "r1" and not out["shown"]
  assert out["m"] == pytest.approx(3200, rel=0.01)
  assert out["e"] == pytest.approx(3000, rel=0.01)
  assert out["best_m"] == pytest.approx(2000, rel=0.01)
  assert out["dur"] == pytest.approx(180, rel=0.01)
  assert ds.engaged_pct(out["e"], out["m"]) == 94
  assert out["tl"][0] == "e" and "m" in out["tl"] and out["tl"][-1] == "s"
  assert out["end"] == pytest.approx(1_760_000_000.0 + t)      # ends when offroad began
  assert rec.update(False, t + 10, 0, 0, False) is None      # only once


def test_short_offroad_gap_is_the_same_drive():
  """A ~1 s onroad cycle (step-aside) must not end the drive and use up the card."""
  rec = ds.DriveRecorder()
  t = drive(rec, 60, 20.0, True, 0.0, drive_id="r1")         # 1200 m
  for k in range(int(1.0 / 0.05)):                            # 1 s offroad
    assert rec.update(False, t + k * 0.05, 0.0, 0.0, False) is None
  t = drive(rec, 60, 20.0, True, t + 1.0, drive_id="r2")     # new route id after the cycle: same drive
  t2 = t
  while (out := rec.update(False, t2, 5000.0, 0.0, False)) is None:
    t2 += 0.05
  assert out["id"] == "r1" and out["m"] == pytest.approx(2400, rel=0.01)
  assert out["dur"] == pytest.approx(120, rel=0.01)
  assert ds.MERGE_S <= t2 - t < ds.MERGE_S + 0.1


def test_recorder_route_id_arrives_late_and_dt_is_capped():
  rec = ds.DriveRecorder()
  rec.update(True, 0.0, 1000.0, 10.0, True)
  assert rec.drive_id == "t1000"
  rec.update(True, 0.05, 1000.05, 10.0, True, drive_id="00000022--abc")
  assert rec.drive_id == "00000022--abc"
  rec.update(True, 60.0, 1060.0, 10.0, True)                 # UI stall: at most 1 s counts
  assert rec.m == pytest.approx(10.5, abs=0.01)


def test_recorder_is_brand_free():
  """No car-brand or fork imports, and no brand names in code (docstring aside)."""
  import ast
  tree = ast.parse((UI / "lib/drive_summary.py").read_text())
  # optional swap-in: fork import only inside try/except in this function (fallback tested below)
  swap = {"accent_rgb": "openpilot.selfdrive.ui.layouts.settings.common"}
  for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in swap]:
    tries = [t for t in ast.walk(fn) if isinstance(t, ast.Try)]
    assert tries and any(isinstance(i, ast.ImportFrom) and i.module == swap[fn.name] for i in tries[0].body), fn.name
  allowed = {"openpilot.common.swaglog", *swap.values()}
  mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
  mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
  assert all(m.split(".")[0] not in ("openpilot", "opendbc", "cereal") or m in allowed for m in mods), mods
  tree.body = tree.body[1:]     # drop the module docstring
  code = ast.unparse(tree).lower()
  for word in ("tesla", "jetlink", "gear", "park"):
    assert word not in code, word


# -- persistence / show rules -------------------------------------------------------------

def summary(m=3000.0, dur=300.0, end=1_760_000_000.0, **kw):
  return {"id": "r", "start": end - dur, "end": end, "dur": dur, "m": m, "e": m * 0.8, "best_m": m / 2,
          "tl": "eeem", "shown": False, **kw}


def test_add_drive_keeps_days_and_last():
  data = None
  for i in range(20):
    end = datetime(2026, 10, 1 + i, 18).timestamp()
    data = ds.add_drive(data, summary(m=1000.0, end=end))
  assert len(data["days"]) == ds.DAYS_KEEP and data["last"]["end"] == end
  data = ds.add_drive(data, summary(m=500.0, end=end + 60))
  assert data["days"]["2026-10-20"] == [1500.0, 1200.0]


def test_today_week_and_streak_fallbacks():
  days = {"2026-10-18": [1000, 900], "2026-10-19": [2000, 1000], "2026-10-21": [500, 0.5], "2026-10-22": [3000, 2000],
          "2026-10-17": [9999, 9999]}
  data = {"days": days}
  tw = ds.today_week(data, today=date(2026, 10, 22))         # Thursday; week starts Sunday Oct 18
  assert tw == {"today_m": 3000, "today_e": 2000, "week_m": 6500, "week_e": 3900.5}
  assert ds.day_streak(data, today=date(2026, 10, 22)) == 1  # Oct 21 had < 1 m engaged
  assert ds.day_streak(data, today=date(2026, 10, 20)) == 3  # nothing yet today: Oct 17-19
  assert ds.day_streak({}, today=date(2026, 10, 22)) == 0


class FakeParams:
  def __init__(self, root, known=True):
    self.root, self.known, self.d = root, known, {}

  def get_param_path(self):
    return str(self.root)

  def check_key(self, key):
    if not self.known:
      raise KeyError(key)
    return key

  def get(self, key, return_default=False):
    return self.d.get(key)

  def put(self, key, value):
    self.d[key] = value

  def put_bool(self, key, value):
    self.d[key] = value


@pytest.mark.parametrize("known", [True, False])
def test_params_roundtrip(tmp_path, known):
  p = FakeParams(tmp_path, known)
  assert ds.get_json(p, ds.PARAM_LAST) is None and not ds.get_bool(p, ds.PARAM_ENABLED)
  ds.put_bool(p, ds.PARAM_ENABLED, True)
  assert ds.get_bool(p, ds.PARAM_ENABLED)
  ds.put_json(p, ds.PARAM_LAST, ds.add_drive(None, summary()))
  if not known:
    assert json.loads((tmp_path / ds.PARAM_LAST).read_text())["last"]["id"] == "r"
  assert ds.get_json(p, ds.PARAM_LAST)["last"]["id"] == "r"


# -- formatting ---------------------------------------------------------------------

def test_card_columns():
  cols = ds.card_columns(summary(m=6.78 * MI, best_m=1.21 * MI) | {"e": 0.81 * 6.78 * MI}, 4, metric=False)
  assert cols == [("6.8", "mi", "driven"), ("81", "%", "engaged"), ("4", "", "day streak"), ("1.2", "mi", "best stretch")]
  assert ds.card_columns(summary(m=52 * MI), 0, metric=False)[0] == ("52", "mi", "driven")
  assert ds.card_columns(summary(m=5000), 0, metric=True)[0] == ("5.0", "km", "driven")


def test_timeline_runs():
  assert ds.timeline_runs("eeemmoeec") == [(ds.ENGAGED, 0, 3), (ds.MANUAL, 3, 2), (ds.OVERRIDE, 5, 1),
                                           (ds.ENGAGED, 6, 2), (ds.CRITICAL, 8, 1)]
  assert ds.timeline_runs("") == []


def test_record_kept():
  data = ds.add_drive(None, {"id": "a", "m": 9000, "e": 8000, "best_m": 3000, "end": 1.7e9})
  data = ds.add_drive(data, {"id": "b", "m": 4000, "e": 2000, "best_m": 1200, "end": 1.7e9})
  assert ds.own_record_m(data) == 3000 and ds.own_record_m(None) == 0 and ds.own_record_m({"record_m": "x"}) == 0


def test_accent_uses_theme_else_comma_green(monkeypatch):
  import builtins
  import sys
  import types
  assert ds.COMMA_GREEN == (0x17, 0x86, 0x45) == ds.COLORS[ds.ENGAGED]
  fake = types.ModuleType("openpilot.selfdrive.ui.layouts.settings.common")
  fake.theme_rgb = lambda params=None: (62, 140, 235)
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.layouts.settings.common", fake)
  assert ds.accent_rgb() == (62, 140, 235)
  fake.theme_rgb = lambda params=None: (0, 255, 64)
  assert ds.accent_rgb() == (0, 255, 64)
  # a fork with a settings.common but no theme manager, and a fork without the module at all
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.layouts.settings.common", types.ModuleType("x"))
  assert ds.accent_rgb() == ds.COMMA_GREEN
  monkeypatch.delitem(sys.modules, "openpilot.selfdrive.ui.layouts.settings.common")
  real = builtins.__import__

  def no_common(name, *a, **k):
    if name.endswith("settings.common"):
      raise ImportError(name)
    return real(name, *a, **k)
  monkeypatch.setattr(builtins, "__import__", no_common)
  assert ds.accent_rgb() == ds.COMMA_GREEN


def test_card_columns_even_and_centered():
  cols = [("6.8", "mi", "driven"), ("81", "%", "engaged"), ("4", "", "day streak"), ("1.2", "mi", "best stretch")]
  def vw(v, u):
    return 20.0 * len(v + u)

  def lw(lbl):
    return 9.0 * len(lbl)
  slots = ds.column_slots(cols, 500, vw, lw)
  assert [c for c, _, _ in slots] == [62.5, 187.5, 312.5, 437.5]          # evenly spaced slot centers
  assert all(c - max(v, label) / 2 >= i * 125 - 1e-9 and c + max(v, label) / 2 <= (i + 1) * 125 + 1e-9
             for i, (c, v, label) in enumerate(slots))                      # each column stays in its slot
  # too wide for 4: best stretch drops, the other 3 re-space evenly; never below 3
  # the real card: best stretch (~120 px) next to day streak (~100 px) fits a 125 px slot with a 10 px gap
  real = ds.column_slots(cols, 500, lambda v, u: 80.0, lambda lbl: {"best stretch": 120.0, "day streak": 100.0}.get(lbl, 80.0))
  assert len(real) == 4
  wide = ds.column_slots(cols, 500, vw, lambda lbl: 13.0 * len(lbl))
  assert len(wide) == 3 and [round(c, 1) for c, _, _ in wide] == [83.3, 250.0, 416.7]
  assert len(ds.column_slots(cols, 100, vw, lw)) == 3


def test_ui_hooks_present():
  main = (UI / "mici/layouts/main.py").read_text()
  assert "drive_summary.tick(ui_state)" in main
  home = (UI / "mici/layouts/home.py").read_text()
  assert "_drive_summary" not in home and "DriveSummaryCard" not in home     # the card lives in the main layout now
  assert "draw_trip_row(" in home and "measure_text_cached(f, ll" not in home   # row code lives in trip_row.py only
  arv = (UI / "mici/onroad/augmented_road_view.py").read_text()
  assert "streak" not in arv.lower()                                         # streak pill removed
  assert not (UI / "mici/onroad/streak_icon.py").exists()
  assert "engaged_alpha" not in (UI / "mici/onroad/hud_renderer.py").read_text()


def test_card_v3_layout_rules():
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
  assert consts["CARD_H"] == 240
  assert consts["HEADLINE"] == consts["HEADLINE"].lower() == "trip complete"
  draw_src = src.split("def draw(self")[1].split("def draw_timeline")[0]
  # badge right of the headline: headline drawn at the left pad, badge center after its measured width
  assert "rl.Vector2(cx, y + HEAD_Y)" in draw_src and "cx + hw + BADGE_GAP + br" in draw_src
  assert draw_src.index("draw_text_ex(bold, HEADLINE") < draw_src.index("draw_check_badge(")
  assert "ds.column_slots(" in draw_src and "sx - lw / 2" in draw_src and "sx - vw / 2" in draw_src
  assert "drive" not in " ".join(v for k, v in consts.items() if isinstance(v, str))
  assert consts["HEAD_SIZE"] > consts["VAL_SIZE"] > consts["LBL_SIZE"]
  assert consts["HEAD_Y"] < consts["VAL_Y"] < consts["LBL_Y"] < consts["TL_Y"] < consts["TRIP_Y"]
  assert consts["TRIP_Y"] + 34 * 1.16 <= consts["CARD_H"]
  # thicker route bar (1.5x the original 12 px), clear of the labels above and the Today/Week text below
  assert consts["TL_H"] == 18
  assert consts["LBL_Y"] + consts["LBL_SIZE"] * 1.16 + 4 <= consts["TL_Y"]
  assert consts["TL_Y"] + consts["TL_H"] + 6 <= consts["TRIP_Y"]
  assert "draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 1.0" in src     # rounded ends kept
  assert "FontWeight.DISPLAY" in src and "draw_trip_block(" in src
  assert "draw_circle" not in src.split("def draw_check_badge")[0]      # no dot indicators
  row = (UI / "mici/widgets/trip_row.py").read_text()
  assert "def draw_trip_block(" in row and "BLOCK_VALUE = 34" in row and "BLOCK_LABEL = 30" in row


# -- card motion: alert-style bounce in, slide back up to the home screen ------

FPS = 60


def _slide():
  from openpilot.selfdrive.ui.mici.widgets.card_slide import CardSlide
  return CardSlide(240, 1 / FPS, width=536)


def test_show_time_is_ten_seconds():
  assert ds.SHOW_S == 10.0
  line = [ln for ln in (UI / "lib/drive_summary.py").read_text().splitlines() if ln.startswith("SHOW_S =")][0]
  assert "#" in line and "change" in line.lower()


def _ys(sl, n, page_dx=0.0):
  out = []
  for _ in range(n):
    pos = sl.step(page_dx)
    out.append(None if pos is None else pos[1])
  return out


def test_card_enters_from_off_screen_smoothly_no_overshoot():
  from openpilot.selfdrive.ui.mici.widgets import card_slide
  assert 0.25 <= card_slide.ENTER_S <= 0.3
  assert not hasattr(card_slide, "EXIT_S")         # no exit animation of its own
  sl = _slide()
  assert sl.step() is None and not sl.drawn       # nothing before show()
  sl.show()
  ys = _ys(sl, FPS)
  assert ys[0] < -0.4 * 240                       # first frame still mostly above the screen
  assert all(b >= a for a, b in zip(ys, ys[1:], strict=False))   # monotonic: only ever moves down
  assert max(ys) <= 0.0                           # no overshoot: never past rect.y
  n = next(i for i, y in enumerate(ys) if y == 0.0) + 1
  assert abs(n / FPS - card_slide.ENTER_S) <= 1.5 / FPS                 # settled in ENTER_S
  for _ in range(int(ds.SHOW_S * FPS)):           # stays put while shown, ignoring the page
    assert sl.step(123.0) == (0.0, 0.0)


def test_card_leaves_with_the_page_no_vertical_exit():
  from openpilot.selfdrive.ui.mici.widgets.card_slide import attached_dx
  assert attached_dx(536.0 + 10, 10) == 536.0 and attached_dx(0, 0) == 0.0
  sl = _slide()
  sl.show()
  _ys(sl, FPS)
  sl.hide()
  for dx in (0.0, 0.0, 40.0, 180.0, 400.0, 535.0):   # wherever the scroller has the onroad page
    assert sl.step(dx) == (dx, 0.0)                 # x rides the page, y never moves
  assert sl.step(535.6) is None and not sl.drawn    # page fully out of view: stop drawing
  assert sl.step(0.0) is None                       # stays gone


def test_card_leave_failsafe_when_no_scroll():
  from openpilot.selfdrive.ui.mici.widgets import card_slide
  sl = _slide()
  sl.show()
  sl.hide()
  n = 0
  while sl.step(0.0) is not None:
    n += 1
    assert n < 5 * FPS
  assert abs(n / FPS - card_slide.LEAVE_MAX_S) <= 2 / FPS


def test_card_tap_mid_entry_and_onroad_cut():
  sl = _slide()
  sl.show()
  ys = _ys(sl, 5)
  sl.hide()                                       # tap while still entering: finishes the drop, rides the page
  pos = sl.step(30.0)
  assert pos[0] == 30.0 and ys[-1] < pos[1] <= 0.0
  assert sl.step(536.0) is None
  sl.show()
  sl.step()
  sl.cut()                                        # onroad resumed: gone this frame
  assert sl.step() is None and not sl.drawn
  sl.hide()                                       # hide when hidden is a no-op
  assert sl.step() is None


def test_card_uses_the_slide():
  src = (UI / "mici/widgets/drive_summary_card.py").read_text()
  assert "CardSlide(CARD_H, 1 / gui_app.target_fps)" in src
  assert "self._slide.hide()" in src.split("def dismiss(self)")[1].split("def ")[0]
  assert "self._slide.cut()" in src.split("def cancel(self)")[1].split("def ")[0]
  assert "self._slide.show()" in src.split("def _begin(self)")[1].split("def ")[0]
  assert "ds.due_summary(" in src.split("def _begin(self)")[1].split("def ")[0]
  assert "def _poll" not in src and "mark_shown" not in src     # only the hand-off shows it
  render = src.split("def render(self")[1].split("def draw(self")[0]
  assert "ds.SHOW_S" in render and "attached_dx(" in render and "rect.x + pos[0]" in render and "FADE_S" not in src
  slide = (UI / "mici/widgets/card_slide.py").read_text()
  assert "Bounce" not in slide and "pyray" not in slide


# -- the hop: trip card first, then the stock scroll to home -------------------

def test_home_handoff_pure():
  h = ds.HomeHandoff()
  assert h.offroad(card_shown=False) is True and not h.waiting      # not due: stock, scroll now
  assert h.release(card_holding=False) is False                     # nothing pending
  assert h.offroad(card_shown=True) is False and h.waiting          # due: hold the scroll
  assert h.release(card_holding=True) is False                      # card up: keep holding
  assert h.release(card_holding=False) is True                      # card going away: scroll now, once
  assert h.release(card_holding=False) is False
  h.offroad(card_shown=True)
  h.onroad()                                                        # onroad is back: nothing pending
  assert h.release(card_holding=False) is False


def _rec(m=5000.0, dur=600.0, last_v=0.0, active=True):
  r = ds.DriveRecorder()
  r.active, r.m, r.e, r.dur, r.last_v, r.drive_id = active, m, m * 0.8, dur, last_v, "route1"
  return r


def test_due_summary_rules(monkeypatch):
  monkeypatch.setattr(ds, "enabled", lambda params: True)
  d = ds.due_summary(None, _rec())
  assert d is not None and d["id"] == "route1" and d["m"] == 5000.0
  assert ds.due_summary(None, _rec(m=150.0)) is None          # < 0.1 mi: stock
  assert ds.due_summary(None, _rec(dur=20.0)) is None         # < 30 s: stock
  assert ds.due_summary(None, _rec(last_v=8.0)) is None       # still moving (an onroad cycle): stock
  assert ds.due_summary(None, _rec(active=False)) is None     # nothing recorded: stock
  monkeypatch.setattr(ds, "enabled", lambda params: False)
  assert ds.due_summary(None, _rec()) is None                 # toggle off: stock


def test_recorder_tracks_last_speed():
  r = ds.DriveRecorder()
  r.update(True, 0.0, 1e9, 10.0, True)
  r.update(True, 0.1, 1e9, 0.0, True)
  assert r.last_v == 0.0
  r.update(True, 0.2, 1e9, 12.0, True)
  assert r.last_v == 12.0


def _stock_scroll_rc() -> float:
  import re
  src = (UI.parents[1] / "system/ui/widgets/scroller.py").read_text()
  assert "self._scrolling_to_filter = FirstOrderFilter(0.0, SCROLL_RC, 1 / gui_app.target_fps)" in src
  return float(re.search(r"^SCROLL_RC = ([0-9.]+)", src, re.M).group(1))


class _MainSim:
  """Mirrors MiciMainLayout._handle_transitions + DriveSummaryCard (holding / render) + the stock
  scroller's smooth scroll_to (FirstOrderFilter(SCROLL_RC), snap within 1 px), stepped at 60 fps.
  page_dx is the onroad page's x: 0 on the onroad page, W once home is in place."""
  W = 536.0

  def __init__(self, due: bool):
    from openpilot.common.filter_simple import FirstOrderFilter
    from openpilot.selfdrive.ui.mici.widgets.card_slide import CardSlide, SHOWN
    self.SHOWN = SHOWN
    self.slide, self.h = CardSlide(240, 1 / FPS, width=self.W), ds.HomeHandoff()
    self.due, self.t, self.started, self.prev, self.shown_at = due, 0.0, True, True, None
    self.scrolls, self.scroll_t, self.ys, self.xs, self.pages = 0, None, [], [], []
    self.scroll = FirstOrderFilter(0.0, _stock_scroll_rc(), 1 / FPS)
    self.target: float | None = None

  def holding(self):
    return self.slide.state == self.SHOWN and self.shown_at is not None and self.t - self.shown_at < ds.SHOW_S

  def frame(self, tap=False):
    if self.started != self.prev:             # _handle_transitions
      self.prev = self.started
      if self.started:
        self.h.onroad()
        self.slide.cut()
        self.shown_at = None
      else:
        shown = False
        if self.due:
          self.slide.show()
          self.shown_at, shown = self.t, True
        if self.h.offroad(shown):
          self._scroll()
    if self.h.release(self.holding()):
      self._scroll()
    if self.target is not None:               # stock scroller layout (before the card overlay)
      self.scroll.update(self.target)
      if abs(self.scroll.x - self.target) < 1:
        self.scroll.x, self.target = self.target, None
    page_dx = self.scroll.x
    if tap and self.slide.drawn:              # main tap hook
      self.slide.hide()
    if self.shown_at is not None and self.t - self.shown_at >= ds.SHOW_S:   # card.render
      self.slide.hide()
    pos = None if self.started else self.slide.step(page_dx)
    if pos is None:
      self.shown_at = None
    self.ys.append(None if pos is None else pos[1])
    self.xs.append(None if pos is None else pos[0])
    self.pages.append(page_dx)
    self.t += 1 / FPS

  def _scroll(self):
    self.scrolls += 1
    self.scroll_t = self.t
    self.target = self.W


def test_not_due_is_stock_immediate_scroll():
  sim = _MainSim(due=False)
  sim.frame()
  sim.started = False
  sim.frame()
  assert sim.scrolls == 1 and sim.scroll_t == pytest.approx(1 / FPS)    # same frame as the edge
  for _ in range(15 * FPS):
    sim.frame()
  assert sim.scrolls == 1 and all(y is None for y in sim.ys) and sim.pages[-1] == sim.W


def test_due_card_first_then_leaves_with_the_stock_scroll():
  sim = _MainSim(due=True)
  sim.frame()
  sim.started = False
  edge = sim.t
  sim.frame()
  assert sim.scrolls == 0 and sim.ys[-1] is not None and sim.ys[-1] < -100   # card slides in, no scroll yet
  for _ in range(int((ds.SHOW_S - 0.1) * FPS)):
    sim.frame()
  assert sim.scrolls == 0 and sim.ys[-1] == 0.0 and sim.xs[-1] == 0.0       # up for SHOW_S over the onroad page
  while sim.scrolls == 0:
    sim.frame()
  assert sim.scroll_t - edge == pytest.approx(ds.SHOW_S, abs=2 / FPS)         # hand-off at SHOW_S
  start = len(sim.ys)
  while sim.ys[-1] is not None:
    sim.frame()
    assert sim.ys[-1] in (0.0, None)                                          # no vertical exit
    if sim.xs[-1] is not None:
      assert sim.xs[-1] == sim.pages[-1]                                      # rides the onroad page exactly
  leave = sim.xs[start - 1:-1]
  assert all(b >= a for a, b in zip(leave, leave[1:], strict=False))         # sideways, home's direction
  assert sim.pages[-1] >= sim.W - 0.5                                         # gone the frame home is in place
  for _ in range(5 * FPS):
    sim.frame()
  assert sim.scrolls == 1 and sim.ys[-1] is None and sim.pages[-1] == sim.W


def test_tap_hands_off_early():
  sim = _MainSim(due=True)
  sim.frame()
  sim.started = False
  for _ in range(2 * FPS):
    sim.frame()
  assert sim.scrolls == 0
  sim.frame(tap=True)
  sim.frame()
  assert sim.scrolls == 1 and sim.scroll_t < 2.2                              # tap: scroll right away
  for _ in range(12 * FPS):
    sim.frame()
  assert sim.scrolls == 1 and sim.ys[-1] is None


def test_onroad_resume_cancels_card_and_hand_off():
  sim = _MainSim(due=True)
  sim.frame()
  sim.started = False
  for _ in range(FPS):
    sim.frame()
  sim.started = True                                                          # R/D, ignition: onroad wins
  sim.frame()
  assert sim.ys[-1] is None and not sim.slide.drawn
  for _ in range(15 * FPS):
    sim.frame()
  assert sim.scrolls == 0 and sim.pages[-1] == 0.0                            # never scrolls to home


def test_main_layout_hooks():
  main = (UI / "mici/layouts/main.py").read_text()
  trans = main.split("def _handle_transitions(self)")[1].split("\n  def ")[0]
  assert "self._drive_summary.cancel()" in trans.split("if ui_state.started:")[1].split("elif")[0]
  assert "elif not self._drive_summary.hold_home():" in trans
  assert "if self._drive_summary.release_home():" in trans
  assert "self._onroad_time_delay = rl.get_time()" in trans and "ONROAD_DELAY" in trans     # stock onroad untouched
  assert "pop_widgets_to" not in trans.split("hold_home")[1].split("FIXME")[0]               # offroad never pops the nav stack
  render = main.split("def _render(self")[1].split("\n  def ")[0]
  assert render.index("super()._render(self._rect)") < render.index("self._drive_summary.render(self._rect, self._onroad_layout.rect.x)")
  assert "self._drive_summary.dismiss_on_tap()" in main.split("def _handle_mouse_release")[1]
  assert "not self._drive_summary.visible" in main                                            # no swiping under the card
  for word in ("tesla", "jetlink", "park"):
    assert word not in "\n".join(ln for ln in main.splitlines() if "_drive_summary" in ln or "DriveSummaryCard" in ln).lower()


def test_best_stretch_resets_on_every_engagement_and_record_keeps_best():
  r = ds.DriveRecorder()
  t = 0.0

  def run(seconds, v, enabled):
    nonlocal t
    for _ in range(int(seconds * 20)):
      r.update(True, t, 1.7e9 + t, v, enabled)
      t += 0.05

  run(1, 20.0, False)
  assert r.cur_m == 0.0
  run(10, 20.0, True)                       # first engagement: 200 m
  assert r.cur_m == pytest.approx(200, abs=2)
  run(0.05, 20.0, False)                    # one disengaged frame
  assert r.cur_m == 0.0
  run(5, 20.0, True)                        # new engagement starts from 0: 100 m
  assert r.cur_m == pytest.approx(100, abs=2)
  assert r.best_m == pytest.approx(200, abs=2)    # best stretch keeps the longer one
  run(15, 20.0, True)                       # same engagement grows past it
  assert r.cur_m == pytest.approx(400, abs=2) and r.best_m == pytest.approx(400, abs=2)
  # an offroad gap merged into the same drive: the restart comes back disengaged, so it resets too
  r.update(False, t, 1.7e9 + t, 0.0, False)
  t += 1.0
  run(0.05, 0.0, False)
  assert r.cur_m == 0.0 and r.best_m == pytest.approx(400, abs=2)
  # the saved record follows the best stretch
  data = ds.add_drive(None, r.summary(1.7e9 + t))
  assert ds.own_record_m(data) == pytest.approx(400, abs=2)
  data = ds.add_drive(data, {"id": "b", "m": 100.0, "e": 50.0, "best_m": 50.0, "end": 1.7e9 + t})
  assert ds.own_record_m(data) == pytest.approx(400, abs=2)       # a shorter streak doesn't lower it
