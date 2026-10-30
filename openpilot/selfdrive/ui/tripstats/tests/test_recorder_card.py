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
  assert rc.classify(True, "enabled", "normal") == rc.ENGAGED
  assert rc.classify(True, "overriding", "normal") == rc.OVERRIDE
  assert rc.classify(True, "preEnabled", "normal") == rc.OVERRIDE
  assert rc.classify(False, "disabled", "normal") == rc.MANUAL          # stopped or moving: connect's blue
  assert rc.classify(True, "enabled", "userPrompt") == rc.PROMPT
  assert rc.classify(True, "overriding", "userPrompt") == rc.OVERRIDE   # same start: connect pushes overriding last
  assert rc.classify(False, "disabled", "critical") == rc.CRITICAL
  assert rc.classify(True, "enabled", "critical", "userBookmark/permanent") == rc.FLAG
  assert rc.classify(False, "disabled", "normal", "userBookmarkNotPaired/permanent") == rc.FLAG


def test_connect_palette():
  # commaai/connect src/theme.js palette.states / src/colors.js; Timeline/index.jsx segmentColor
  assert rc.COLORS[rc.MANUAL] == (0x17, 0x58, 0x86)     # drivingBlue blue500 (segment background)
  assert rc.COLORS[rc.ENGAGED] == (0x17, 0x86, 0x45)    # engagedGreen green400 (.engage)
  assert rc.COLORS[rc.OVERRIDE] == (0x91, 0x9b, 0x95)   # engagedGrey (.overriding)
  assert rc.COLORS[rc.PROMPT] == (0xda, 0x6f, 0x25)     # alertOrange orange50 (.alert.userPrompt)
  assert rc.COLORS[rc.CRITICAL] == (0xc9, 0x22, 0x31)   # alertRed red100 (.alert.critical)
  assert rc.COLORS[rc.FLAG] == (0xe3, 0xd7, 0x56)       # userBookmark yellow500 (.bookmark)
  assert set(rc.COLORS) == set(range(len(rc.CODES)))


# route 3e2de7ed673817c2/00000095--637348a3fa (Tesla, Highland 387ed94): (t, enabled, state) changes.
# Each engage starts in "overriding" (gas held): connect shows grey there, and no alert or bookmark.
ROUTE_95 = [(0.0, False, "disabled"), (25.5, True, "overriding"), (27.4, True, "enabled"), (31.5, True, "overriding"),
            (32.0, True, "enabled"), (32.5, True, "overriding"), (33.1, False, "disabled"), (37.4, True, "overriding"),
            (38.4, True, "enabled"), (44.0, False, "disabled"), (73.0, True, "overriding"), (73.8, True, "enabled"),
            (78.7, False, "disabled"), (109.8, True, "overriding"), (111.7, True, "enabled"), (127.9, False, "disabled"),
            (137.7, True, "overriding"), (139.0, True, "enabled"), (161.0, False, "disabled"), (172.9, False, "disabled")]


def test_route_95_has_no_yellow():
  rec = rc.DriveRecorder()
  for (t0, en, st), (t1, _, _) in zip(ROUTE_95[:-1], ROUTE_95[1:], strict=True):
    drive(rec, t1 - t0, 5.0, en, t0, state=st)
  runs = tc.timeline_runs(rec.timeline.codes())
  assert {r[0] for r in runs} == {rc.MANUAL, rc.ENGAGED, rc.OVERRIDE}
  assert rc.FLAG not in {r[0] for r in runs} and rc.COLORS[rc.OVERRIDE] == (0x91, 0x9b, 0x95)
  assert rec.timeline.codes()[:14] == "m" * 13 + "o"     # 25.5 s blue, then the engage's grey


def test_bookmark_shows_over_everything():
  rec = rc.DriveRecorder()
  t = drive(rec, 11, 20.0, True, 0.0, state="enabled")
  t = drive(rec, 0.1, 20.0, True, t, state="enabled", alert_status="critical", alert_type="userBookmark/permanent")
  drive(rec, 9, 20.0, True, t, state="enabled")
  assert rec.timeline.codes() == "eeeeefeeeee"           # a 0.1 s bookmark still colors its 2 s bucket


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
  assert out["tl"][0] == "e" and "m" in out["tl"] and out["tl"][-1] == "m"
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
  assert tc.timeline_runs("ssmo") == [(rc.MANUAL, 0, 3), (rc.OVERRIDE, 3, 1)]   # stored before: "s" (stopped) is blue now


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


def test_layers_last_started_is_on_top():
  # connect draws each engage / overriding / alert event in start order, so the newest one shows
  ly = rc.Layers()
  assert ly.status(0.0, False, "disabled", "normal") == rc.MANUAL
  assert ly.status(1.0, False, "disabled", "userPrompt", "a") == rc.PROMPT
  assert ly.status(2.0, True, "enabled", "userPrompt", "a") == rc.ENGAGED      # engage started after the alert
  assert ly.status(3.0, True, "enabled", "userPrompt", "b") == rc.ENGAGED      # same alertStatus: same event
  assert ly.status(3.5, True, "enabled", "normal") == rc.ENGAGED
  assert ly.status(3.6, True, "enabled", "userPrompt", "b") == rc.PROMPT       # a new alert event
  assert ly.status(4.0, True, "overriding", "userPrompt", "b") == rc.OVERRIDE  # override started last
  ly2 = rc.Layers()
  assert ly2.status(0.0, True, "preEnabled", "normal") == rc.OVERRIDE
  assert ly2.status(1.0, True, "preEnabled", "userPrompt") == rc.PROMPT          # alert started after it
  assert ly2.status(2.0, True, "overriding", "userPrompt") == rc.OVERRIDE        # a new state is a new event
  assert ly.status(5.0, True, "overriding", "critical", "c") == rc.CRITICAL
  assert ly.status(6.0, True, "overriding", "normal", "c") == rc.OVERRIDE
  assert ly.status(6.5, True, "preEnabled", "normal") == rc.OVERRIDE
  assert ly.status(7.0, True, "enabled", "normal", "userBookmark/permanent") == rc.FLAG   # bookmark always on top
  assert ly.status(7.9, True, "enabled", "normal", "userBookmark/permanent") == rc.FLAG
  assert ly.status(8.0, True, "enabled", "normal", "userBookmark/permanent") == rc.ENGAGED  # connect: 1 s wide
  assert ly.status(8.5, True, "enabled", "normal") == rc.ENGAGED
  assert ly.status(9.0, False, "disabled", "normal") == rc.MANUAL


def test_recorder_uses_start_order():
  rec = rc.DriveRecorder()
  t = drive(rec, 4, 20.0, False, 0.0, state="disabled", alert_status="userPrompt", alert_type="x")
  drive(rec, 4, 20.0, True, t, state="enabled", alert_status="userPrompt", alert_type="x")
  assert rec.timeline.codes() == "ppee"                 # the later engage covers the earlier alert, as in connect
