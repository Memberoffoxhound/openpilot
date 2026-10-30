"""tripstats recorder and card formatting. Pure, no raylib."""
import pytest

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import card as tc, recorder as rc, store

MI = 1609.344


def summary(m=3000.0, dur=300.0, end=1_760_000_000.0, **kw):
  return {"id": "r", "start": end - dur, "end": end, "dur": dur, "m": m, "e": m * 0.8, "best_m": m / 2, "tl": "eeem", **kw}


def drive(rec, seconds, v, enabled, t0, wall0=1_760_000_000.0, dt=0.05, **kw):
  t = t0
  while t < t0 + seconds - 1e-9:
    assert rec.update(True, t, wall0 + t, v, enabled, **kw) is None
    t += dt
  return t


def test_classify():
  assert rc.classify(True, "enabled", "normal", False, 20) == rc.ENGAGED
  assert rc.classify(True, "overriding", "normal", False, 20) == rc.OVERRIDE
  assert rc.classify(True, "enabled", "normal", True, 20) == rc.OVERRIDE       # gas while engaged
  assert rc.classify(False, "disabled", "normal", True, 20) == rc.MANUAL       # gas while manual is just manual
  assert rc.classify(False, "disabled", "normal", False, 0.0) == rc.STANDBY
  assert rc.classify(True, "enabled", "userPrompt", False, 20) == rc.PROMPT
  assert rc.classify(False, "disabled", "critical", False, 20) == rc.CRITICAL


def test_connect_palette():
  # commaai/connect src/theme.js palette.states / src/colors.js
  assert rc.COLORS[rc.ENGAGED] == (0x17, 0x86, 0x45)    # engagedGreen green400
  assert rc.COLORS[rc.MANUAL] == (0x17, 0x58, 0x86)     # drivingBlue blue500
  assert rc.COLORS[rc.PROMPT] == (0xda, 0x6f, 0x25)     # alertOrange orange50
  assert rc.COLORS[rc.CRITICAL] == (0xc9, 0x22, 0x31)   # alertRed red100
  assert rc.COLORS[rc.STANDBY] == (0x91, 0x9b, 0x95)    # engagedGrey
  assert rc.COLORS[rc.OVERRIDE] == (0xe3, 0xd7, 0x56)   # yellow500


def test_timeline_buckets_and_dominance():
  tl = rc.Timeline(n=8, bucket_s=1.0)
  tl.add(rc.ENGAGED, 2.0)
  tl.add(rc.MANUAL, 0.6)
  tl.add(rc.ENGAGED, 0.4)
  tl.add(rc.PROMPT, 0.05)           # any alert time colors the bucket
  assert tl.codes() == "eemp"


def test_timeline_constant_memory_compaction():
  tl = rc.Timeline(n=160, bucket_s=2.0)
  for i in range(3 * 3600 * 20):    # 3 h at 20 Hz
    tl.add(rc.ENGAGED if (i // 2000) % 4 else rc.MANUAL, 0.05)
  assert len(tl.buckets) == 160
  codes = tl.codes()
  assert 80 < len(codes) <= 160 and set(codes) == {"e", "m"}
  assert sum(sum(b) for b in tl.buckets) == pytest.approx(3 * 3600, rel=1e-6)


def test_timeline_crossing_a_bucket_edge_splits_time():
  tl = rc.Timeline(n=4, bucket_s=1.0)
  tl.add(rc.ENGAGED, 0.9)
  tl.add(rc.MANUAL, 0.3)
  assert tl.buckets[0][rc.MANUAL] == pytest.approx(0.1)
  assert tl.buckets[1][rc.MANUAL] == pytest.approx(0.2)


def test_recorder_distance_engaged_best_stretch():
  rec = rc.DriveRecorder()
  t = drive(rec, 100, 20.0, True, 0.0, drive_id="r1")       # 2000 m engaged
  t = drive(rec, 10, 20.0, False, t)                         # 200 m manual
  assert rec.cur_m == 0
  t = drive(rec, 50, 20.0, True, t)                          # 1000 m engaged
  assert rec.cur_m == pytest.approx(1000, rel=0.01)
  t = drive(rec, 20, 0.0, False, t)                          # stopped
  assert rec.update(False, t, 1_760_000_000.0 + t, 0.0, False) is None          # offroad: wait MERGE_S
  out = rec.update(False, t + rc.MERGE_S, 1_760_000_000.0 + t + rc.MERGE_S, 0.0, False)
  assert out["id"] == "r1" and out["shown"] is False
  assert out["m"] == pytest.approx(3200, rel=0.01)
  assert out["e"] == pytest.approx(3000, rel=0.01)
  assert out["best_m"] == pytest.approx(2000, rel=0.01)
  assert out["dur"] == pytest.approx(180, rel=0.01)
  assert store.engaged_pct(out["e"], out["m"]) == 94
  assert out["tl"][0] == "e" and "m" in out["tl"] and out["tl"][-1] == "s"
  assert out["end"] == pytest.approx(1_760_000_000.0 + t)      # ends when offroad began
  assert rec.update(False, t + 10, 0, 0, False) is None      # only once


def test_short_offroad_gap_is_the_same_drive():
  """A ~1 s onroad cycle (step-aside) must not end the drive and use up the card."""
  rec = rc.DriveRecorder()
  t = drive(rec, 60, 20.0, True, 0.0, drive_id="r1")         # 1200 m
  for k in range(int(1.0 / 0.05)):                            # 1 s offroad
    assert rec.update(False, t + k * 0.05, 0.0, 0.0, False) is None
  t = drive(rec, 60, 20.0, True, t + 1.0, drive_id="r2")     # new route id after the cycle: same drive
  t2 = t
  while (out := rec.update(False, t2, 5000.0, 0.0, False)) is None:
    t2 += 0.05
  assert out["id"] == "r1" and out["m"] == pytest.approx(2400, rel=0.01)
  assert out["dur"] == pytest.approx(120, rel=0.01)
  assert rc.MERGE_S <= t2 - t < rc.MERGE_S + 0.1


def test_recorder_route_id_arrives_late_and_dt_is_capped():
  rec = rc.DriveRecorder()
  rec.update(True, 0.0, 1000.0, 10.0, True)
  assert rec.drive_id == "t1000"
  rec.update(True, 0.05, 1000.05, 10.0, True, drive_id="00000022--abc")
  assert rec.drive_id == "00000022--abc"
  rec.update(True, 60.0, 1060.0, 10.0, True)                 # UI stall: at most 1 s counts
  assert rec.m == pytest.approx(10.5, abs=0.01)


def test_recorder_tracks_last_speed():
  r = rc.DriveRecorder()
  r.update(True, 0.0, 1e9, 10.0, True)
  r.update(True, 0.1, 1e9, 0.0, True)
  assert r.last_v == 0.0
  r.update(True, 0.2, 1e9, 12.0, True)
  assert r.last_v == 12.0


def test_best_stretch_resets_on_every_engagement_and_record_keeps_best():
  r = rc.DriveRecorder()
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
  # the stored record follows the best stretch
  data = store.add_drive(store.load(None), store.stamp(r.summary(1.7e9 + t), 1.7e9 + t))
  assert data["record_m"] == pytest.approx(400, abs=2)
  data = store.add_drive(data, store.stamp({"id": "b", "m": 100.0, "e": 50.0, "best_m": 50.0}, 1.7e9 + t))
  assert data["record_m"] == pytest.approx(400, abs=2)       # a shorter stretch doesn't lower it


def test_card_columns():
  cols = tc.card_columns(summary(m=6.78 * MI, best_m=1.21 * MI) | {"e": 0.81 * 6.78 * MI}, 4, metric=False)
  assert cols == [("6.8", "mi", "driven"), ("81", "%", "engaged"), ("4", "", "day streak"), ("1.2", "mi", "best stretch")]
  assert tc.card_columns(summary(m=52 * MI), 0, metric=False)[0] == ("52", "mi", "driven")
  assert tc.card_columns(summary(m=5000), 0, metric=True)[0] == ("5.0", "km", "driven")


def test_timeline_runs():
  assert tc.timeline_runs("eeemmoeec") == [(rc.ENGAGED, 0, 3), (rc.MANUAL, 3, 2), (rc.OVERRIDE, 5, 1),
                                           (rc.ENGAGED, 6, 2), (rc.CRITICAL, 8, 1)]
  assert tc.timeline_runs("") == []


def test_accent_uses_theme_else_comma_green(monkeypatch):
  import builtins
  import sys
  import types
  assert tc.COMMA_GREEN == (0x17, 0x86, 0x45) == rc.COLORS[rc.ENGAGED]
  fake = types.ModuleType("openpilot.selfdrive.ui.layouts.settings.common")
  fake.THEME_OPENPILOT_RGB = (0, 255, 64)
  fake.theme_rgb = lambda params=None: (62, 140, 235)
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.layouts.settings.common", fake)
  assert tc.accent_rgb() == (62, 140, 235)
  fake.theme_rgb = lambda params=None: (0, 255, 64)                # openpilot theme: timeline's comma green
  assert tc.accent_rgb() == tc.COMMA_GREEN
  fake.theme_rgb = lambda params=None: (300, -5, 64.7)          # out-of-range theme value: clamped, no crash
  assert tc.accent_rgb() == (255, 0, 64)
  for bad in (lambda params=None: (1, 2), lambda params=None: None, lambda params=None: 1 / 0):
    fake.theme_rgb = bad                                           # broken theme manager: comma green
    assert tc.accent_rgb() == tc.COMMA_GREEN
  # a fork with a settings.common but no theme manager, and a fork without the module at all
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.layouts.settings.common", types.ModuleType("x"))
  assert tc.accent_rgb() == tc.COMMA_GREEN
  monkeypatch.delitem(sys.modules, "openpilot.selfdrive.ui.layouts.settings.common")
  real = builtins.__import__

  def no_common(name, *a, **k):
    if name.endswith("settings.common"):
      raise ImportError(name)
    return real(name, *a, **k)
  monkeypatch.setattr(builtins, "__import__", no_common)
  assert tc.accent_rgb() == tc.COMMA_GREEN


def test_card_columns_even_and_centered():
  cols = [("6.8", "mi", "driven"), ("81", "%", "engaged"), ("4", "", "day streak"), ("1.2", "mi", "best stretch")]
  def vw(v, u):
    return 20.0 * len(v + u)

  def lw(lbl):
    return 9.0 * len(lbl)
  slots = tc.column_slots(cols, 500, vw, lw)
  assert [c for c, _, _ in slots] == [62.5, 187.5, 312.5, 437.5]          # evenly spaced slot centers
  assert all(c - max(v, label) / 2 >= i * 125 - 1e-9 and c + max(v, label) / 2 <= (i + 1) * 125 + 1e-9
             for i, (c, v, label) in enumerate(slots))                      # each column stays in its slot
  # too wide for 4: best stretch drops, the other 3 re-space evenly; never below 3
  # the real card: best stretch (~120 px) next to day streak (~100 px) fits a 125 px slot with a 10 px gap
  real = tc.column_slots(cols, 500, lambda v, u: 80.0, lambda lbl: {"best stretch": 120.0, "day streak": 100.0}.get(lbl, 80.0))
  assert len(real) == 4
  wide = tc.column_slots(cols, 500, vw, lambda lbl: 13.0 * len(lbl))
  assert len(wide) == 3 and [round(c, 1) for c, _, _ in wide] == [83.3, 250.0, 416.7]
  assert len(tc.column_slots(cols, 100, vw, lw)) == 3


def _rec(m=5000.0, dur=600.0, last_v=0.0, active=True):
  r = rc.DriveRecorder()
  r.active, r.m, r.e, r.dur, r.last_v, r.drive_id = active, m, m * 0.8, dur, last_v, "route1"
  return r


def test_due_summary_rules(monkeypatch):
  monkeypatch.setattr(ts, "enabled", lambda params: True)
  d = ts.due_summary(None, _rec())
  assert d is not None and d["id"] == "route1" and d["m"] == 5000.0
  assert ts.due_summary(None, _rec(m=150.0)) is None          # < 0.1 mi: stock
  assert ts.due_summary(None, _rec(dur=20.0)) is None         # < 30 s: stock
  assert ts.due_summary(None, _rec(last_v=8.0)) is None       # still moving (an onroad cycle): stock
  assert ts.due_summary(None, _rec(active=False)) is None     # nothing recorded: stock
  monkeypatch.setattr(ts, "enabled", lambda params: False)
  assert ts.due_summary(None, _rec()) is None                 # toggle off: stock
