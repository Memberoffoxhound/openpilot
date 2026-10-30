"""tripstats store and UI hook: days, Sunday weeks, streaks, pruning, a bad param, the stale-clock guard,
device-local days in more than one zone, and a drive ending by Park (Tesla) or by ignition (everything else)."""
import ast
import json
import types
from datetime import date, datetime
from pathlib import Path

import pytest

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import recorder as rc, store

PKG = Path(ts.__file__).parent


def wall(*a) -> float:
  return datetime(*a).timestamp()       # device local time


def drv(m=1000.0, e=800.0, best_m=300.0, **kw):
  return {"id": "r", "m": m, "e": e, "best_m": best_m, "dur": 600.0, "tl": "eem", "end": 0.0, "off": 0, **kw}


def add(data, drive, w, zone=None):
  return store.add_drive(data, store.stamp(drive, w, zone))


def fresh():
  return store.load(None)


def at(*a):
  return datetime(*a)


# -- days, weeks, months --------------------------------------------------------------------

def test_day_rollover_at_local_midnight():
  d = add(fresh(), drv(m=1000), wall(2026, 10, 29, 23, 59, 59))
  d = add(d, drv(m=500), wall(2026, 10, 30, 0, 0, 1))
  assert d["days"] == {"2026-10-29": [1000.0, 800.0], "2026-10-30": [500.0, 800.0]}
  assert store.view(d, at=at(2026, 10, 30, 12))["today_m"] == 500
  assert store.view(d, at=at(2026, 10, 29, 12))["today_m"] == 1000


def test_week_starts_sunday():
  d = fresh()
  for day, m in ((24, 100.0), (25, 200.0), (28, 400.0), (31, 800.0)):  # Sat 24, Sun 25, Wed 28, Sat 31
    d = add(d, drv(m=m, e=m / 2), wall(2026, 10, day, 12))
  d = add(d, drv(m=1600.0, e=0.0), wall(2026, 11, 1, 12))              # next Sunday
  v = store.view(d, at=at(2026, 10, 31, 20))                                        # Saturday night
  assert [w["id"] for w in v["week_days"]][0] == "2026-10-25" and v["week_days"][-1]["id"] == "2026-10-31"
  assert v["week_m"] == 200 + 400 + 800 and v["week_e"] == 700 and v["week_pct"] == 50
  v = store.view(d, at=at(2026, 11, 1, 8))                                          # Sunday: a new week
  assert v["week_m"] == 1600 and v["today_m"] == 1600 and v["week_days"][0]["id"] == "2026-11-01"
  v = store.view(d, at=at(2026, 10, 25, 0, 0, 1))                                    # Sunday just after midnight
  assert v["today_m"] == 200 and v["week_days"][0]["id"] == "2026-10-25" and v["week_m"] == 1400   # Sat 24 is last week


def test_months_and_lifetime():
  d = fresh()
  for mo in (3, 5, 9, 10):
    d = add(d, drv(m=1000.0 * mo, e=500.0 * mo), wall(2026, mo, 15, 12))
  v = store.view(d, at=at(2026, 10, 29, 12))
  assert [m["id"] for m in v["months"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
  assert [m["m"] for m in v["months"]] == [5000, 0, 0, 0, 9000, 10000] and v["months"][-1]["current"]
  assert v["life_m"] == 27000 and v["life_e"] == 13500 and v["pct"] == 50        # March counts in lifetime
  v = store.view(d, at=at(2027, 2, 1, 12))                                          # across a year end
  assert [m["id"] for m in v["months"]][:2] == ["2026-09", "2026-10"]


# -- streaks --------------------------------------------------------------------------------

def test_streak_current_and_best():
  d = fresh()
  for day in (1, 2, 3, 4, 5, 10, 11, 12):
    d = add(d, drv(), wall(2026, 10, day, 12))
  d = add(d, drv(e=0.5), wall(2026, 10, 13, 12))      # driven, not engaged: doesn't count
  assert store.streaks(d["days"], date(2026, 10, 12)) == (3, 5)
  assert store.streaks(d["days"], date(2026, 10, 13)) == (3, 5)   # nothing engaged yet today: yesterday's run
  assert store.streaks(d["days"], date(2026, 10, 14)) == (0, 5)
  v = store.view(d, at=at(2026, 10, 13, 12))
  assert v["streak_now"] == 3 and v["streak_days"] == 5          # the card / Statistics show the best ever
  assert store.streaks({}, date(2026, 10, 1)) == (0, 0)


def test_best_streak_outlives_pruning():
  d = fresh()
  for day in range(1, 8):
    d = add(d, drv(), wall(2025, 1, day, 12))
  assert d["streak_max"] == 7
  d = add(d, drv(), wall(2026, 10, 29, 12))
  assert "2025-01-01" not in d["days"] and d["streak_max"] == 7
  assert store.view(d, at=at(2026, 10, 29, 13))["streak_days"] == 7


def test_drive_in_progress_counts_today_and_streak():
  d = add(fresh(), drv(), wall(2026, 10, 28, 12))
  v = store.view(d, [drv(m=2000.0, e=2000.0, best_m=1500.0)], at=at(2026, 10, 29, 9))
  assert v["today_m"] == 2000 and v["streak_now"] == 2 and v["longest_m"] == 1500 and v["life_m"] == 3000
  assert "2026-10-29" not in d["days"]                             # view never writes the store


# -- dating, pruning, a bad param ------------------------------------------------------------

def test_drive_over_midnight_is_dated_when_it_ends():
  d = add(fresh(), drv(m=50000.0, start=wall(2026, 10, 29, 23, 30)), wall(2026, 10, 30, 0, 20))
  assert list(d["days"]) == ["2026-10-30"]


def test_400_days_kept():
  d = fresh()
  for i in range(420):
    d = add(d, drv(m=10.0, e=10.0), wall(2025, 9, 1, 12) + i * 86400)
  ks = sorted(d["days"])
  assert len(ks) == store.DAYS_KEEP and ks[-1] == "2026-10-25" and ks[0] == "2025-09-21"
  assert d["life"] == [4200.0, 4200.0]                              # lifetime keeps the pruned days


def test_missing_old_or_corrupt_param_starts_clean(tmp_path):
  p = Params(tmp_path)
  assert store.load(p) == fresh() == store.load(None)
  for raw in (b"{", b"[]", b"null", json.dumps({"days": {"2026-10-01": [1, 1]}, "record_m": 5}).encode()):  # bad / v1
    p.d[store.PARAM] = raw
    assert store.load(p) == fresh()
  p.d[store.PARAM] = json.dumps({"v": 2, "days": {"2026-10-01": [100, 50], "junk": [1, 1], "2026-10-02": "x",
                                                  "2026-10-03": [None, 1]},
                                 "life": "x", "record_m": "x", "streak_max": None,
                                 "open": [drv(), {"m": "x"}, 7], "last": {"id": "no m"}}).encode()
  d = store.load(p)
  assert d["days"] == {"2026-10-01": [100.0, 50.0]} and d["life"] == [0.0, 0.0] and d["record_m"] == 0.0
  assert d["streak_max"] == 0 and len(d["open"]) == 1 and "last" not in d
  store.view(d)                                                     # whatever survived renders


def test_roundtrip_through_params_and_raw_file(tmp_path):
  for known in (True, False):                                       # an older params library: raw file
    p = Params(tmp_path, known)
    d = add(fresh(), drv(), wall(2026, 10, 29, 12))
    store.save(p, d)
    assert store.load(p) == {**d, "open": []}


# -- device-local days, any zone -----------------------------------------------------------

def test_day_follows_device_zone(tz):
  w = datetime.fromisoformat("2026-10-30T03:30:00+00:00").timestamp()     # 22:30 Oct 29 in Chicago, 12:30 Oct 30 in Tokyo
  tz("America/Chicago")
  assert store.day_key(w, store.offset(w)) == "2026-10-29"
  tz("Asia/Tokyo")
  assert store.day_key(w, store.offset(w)) == "2026-10-30"
  d = add(fresh(), drv(), w)
  assert store.view(d, at=datetime.fromtimestamp(w))["today_m"] == 1000


def test_week_boundary_in_tokyo(tz):
  tz("Asia/Tokyo")
  sun = datetime.fromisoformat("2026-10-24T15:00:01+00:00").timestamp()   # Sun Oct 25 00:00:01 JST
  d = add(fresh(), drv(m=300.0), sun - 2)                       # Sat 23:59:59 JST
  d = add(d, drv(m=700.0), sun)
  v = store.view(d, at=datetime.fromtimestamp(sun + 60))
  assert v["week_days"][0]["id"] == "2026-10-25" and v["week_m"] == 700 and v["today_m"] == 700


def test_dst_change_keeps_days_and_weeks(tz):
  tz("America/Chicago")                                                    # DST ends Sun Nov 1 2026, 2:00 -> 1:00
  d = fresh()
  for h in (0.5, 1.5, 2.5, 23.5):                                          # hours after local midnight, by the clock
    d = add(d, drv(m=100.0), datetime(2026, 11, 1).timestamp() + h * 3600)
  assert d["days"]["2026-11-01"][0] == 400.0                               # a 25 h day: all four on Nov 1
  d = add(d, drv(m=50.0), wall(2026, 11, 2, 0, 0, 1))
  assert d["days"]["2026-11-02"][0] == 50.0
  v = store.view(d, at=at(2026, 11, 7, 23))
  assert v["week_days"][0]["id"] == "2026-11-01" and v["week_m"] == 450
  tz("America/Chicago")                                                    # DST starts Sun Mar 8 2026: a 23 h day
  d = add(fresh(), drv(m=10.0), wall(2026, 3, 8, 23, 59))
  assert list(d["days"]) == ["2026-03-08"]


# -- the UI hook: tick() over a fake ui_state ------------------------------------------------

class Params:
  def __init__(self, root, known=True):
    self.root, self.known, self.d = root, known, {}

  def get_param_path(self):
    return str(self.root)

  def check_key(self, key):
    if not self.known:
      raise KeyError(key)

  def get(self, key, return_default=False):
    v = self.d.get(key)
    if key == store.PARAM and isinstance(v, (bytes, str)):
      try:
        return json.loads(v)
      except ValueError:
        return None
    return v

  def put(self, key, value, block=False):
    self.d[key] = value

  def put_bool(self, key, value, block=False):
    self.d[key] = value

  def get_bool(self, key):
    return bool(self.d.get(key))


class World:
  """The UI process: a fake ui_state and clocks driving tripstats.tick()."""

  def __init__(self, monkeypatch, tmp_path, start=None, valid=True):
    self.mono = 100.0
    self.wall = start or wall(2026, 10, 29, 17)
    self.valid = valid
    self.params = Params(tmp_path)
    self.params.d["DriveSummary"] = True
    self.v, self.engaged = 0.0, False
    self.ui = types.SimpleNamespace(params=self.params, started=False, started_frame=0, sm=self)
    self.recv_frame = {"selfdriveState": 1}
    monkeypatch.setattr(ts, "time", types.SimpleNamespace(monotonic=lambda: self.mono))
    monkeypatch.setattr(ts, "wall_now", lambda: self.wall)
    monkeypatch.setattr(ts, "system_time_valid", lambda: self.valid)
    self.restart(monkeypatch)

  def restart(self, monkeypatch):
    """A new UI process: nothing in memory, only the param."""
    monkeypatch.setattr(ts, "live", ts.DriveRecorder())
    monkeypatch.setattr(ts, "_data", None)
    monkeypatch.setattr(ts, "_held", [])
    monkeypatch.setattr(ts, "_saved_t", 0.0)
    monkeypatch.setattr(ts, "_enabled_cache", (0.0, False))
    monkeypatch.setattr(ts, "_zone", (-1e9, None))
    monkeypatch.setattr(ts, "_lookup_t", None)

  def __getitem__(self, k):
    if k == "carState":
      return types.SimpleNamespace(vEgo=self.v, gasPressed=False)
    return types.SimpleNamespace(enabled=self.engaged, state="enabled" if self.engaged else "disabled", alertStatus="normal")

  def run(self, seconds, **kw):
    for k, val in kw.items():
      setattr(self.ui if k == "started" else self, k, val)
    for _ in range(int(seconds * 20)):
      ts.tick(self.ui)
      self.mono += 0.05
      self.wall += 0.05

  def stored(self):
    return store.load(self.params)


def test_ignition_path_card_at_offroad_edge_then_stored(monkeypatch, tmp_path):
  """Any car with an ignition switch: started drops at ignition off; the card is due at that edge."""
  w = World(monkeypatch, tmp_path)
  w.run(1, started=True)
  w.run(100, v=20.0, engaged=True)                     # 2000 m engaged
  w.run(1, v=0.0)
  during = ts.view(w.params)
  assert during["today_m"] == pytest.approx(2000, rel=0.01)    # Home counts the drive in progress
  w.run(0.05, started=False)                                    # ignition off: the offroad edge
  card = ts.due_summary(w.params)
  assert card is not None and card["m"] == pytest.approx(2000, rel=0.01)
  assert ts.view(w.params)["today_m"] == during["today_m"]      # card Day == Home Day
  assert w.stored()["days"] == {}                               # not stored until MERGE_S offroad
  w.run(rc.MERGE_S + 0.2)
  d = w.stored()
  assert d["days"]["2026-10-29"][0] == pytest.approx(2000, rel=0.01) and d["open"] == []
  assert ts.view(w.params)["today_m"] == pytest.approx(during["today_m"], abs=0.1)   # no double count
  assert ts.due_summary(w.params) is None                       # once


def test_tesla_park_path_card_at_park_while_still_onroad(monkeypatch, tmp_path):
  """Tesla keeps ignition on in Park: started only drops when parkd's ParkOffroadState reaches PARKED
  (hardwared's not_parked). The card is up at the first Park sample, while still onroad and stopped."""
  w = World(monkeypatch, tmp_path)
  w.run(1, started=True)
  w.run(60, v=25.0, engaged=True)
  w.run(1, v=0.0, engaged=False)                       # Park: stopped, ignition still on, still started
  card = ts.due_summary(w.params)
  assert card is not None and card["m"] == pytest.approx(1500, rel=0.01)
  assert ts.view(w.params)["today_m"] == pytest.approx(card["m"], abs=0.1)
  w.run(3)                                             # PARK_HOLD_S: still onroad, nothing stored, same numbers
  assert w.stored()["days"] == {} and ts.view(w.params)["today_m"] == pytest.approx(card["m"], abs=0.1)
  w.run(rc.MERGE_S + 0.2, started=False)               # parkd PARKED -> offroad the normal way -> stored
  assert w.stored()["days"]["2026-10-29"][0] == pytest.approx(card["m"], abs=0.1)
  w.run(1, started=True)                               # R/D: back onroad, a new drive
  w.run(10, v=10.0)
  assert ts.view(w.params)["today_m"] == pytest.approx(card["m"] + 100, rel=0.01)


def test_records_with_the_card_toggle_off(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path)
  w.params.d["DriveSummary"] = False
  w.run(1, started=True)
  w.run(20, v=10.0)
  w.run(0.05, v=0.0, started=False)
  assert ts.due_summary(w.params) is None              # no card ...
  w.run(rc.MERGE_S + 0.2)
  assert w.stored()["days"]["2026-10-29"][0] == pytest.approx(200, rel=0.02)   # ... Home still counts


def test_stale_clock_holds_the_drive_until_valid(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path, start=wall(2026, 7, 4, 12), valid=False)    # booted on a stale July clock
  w.run(1, started=True)
  w.run(30, v=20.0, engaged=True)
  w.run(rc.MERGE_S + 0.2, v=0.0, started=False)
  d = w.stored()
  assert d["days"] == {} and len(d["open"]) == 1        # held, never on July 4
  assert ts.view(w.params)["today_m"] == pytest.approx(600, rel=0.01)
  w.restart(monkeypatch)                                # survives a UI restart
  w.wall, w.valid = wall(2026, 10, 29, 17, 5), True     # clock synced
  w.run(0.1)
  d = w.stored()
  assert list(d["days"]) == ["2026-10-29"] and d["open"] == [] and d["days"]["2026-10-29"][0] == pytest.approx(600, rel=0.01)


def test_ui_restart_mid_drive_keeps_what_was_driven(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path)
  w.run(1, started=True)
  w.run(ts.SAVE_S + 1, v=20.0)                          # saved once mid-drive
  saved = w.stored()["open"]
  assert len(saved) == 1 and saved[0]["m"] > 500
  w.restart(monkeypatch)                                # UI crash / restart while driving
  w.run(0.1)
  assert w.stored()["days"]["2026-10-29"][0] == pytest.approx(saved[0]["m"], abs=0.1)


def test_web_gui_reads_the_same_numbers(monkeypatch, tmp_path):
  from openpilot.system.webgui import stats
  w = World(monkeypatch, tmp_path)
  w.run(1, started=True)
  w.run(ts.SAVE_S + 1, v=20.0, engaged=True)
  monkeypatch.setattr("openpilot.common.params.Params", lambda: w.params)
  out = stats._collect(str(tmp_path))
  assert out["trips"]["today_m"] == pytest.approx(w.stored()["open"][0]["m"])
  assert out["current"]["m"] == w.stored()["open"][0]["m"] and out["src"]["trips"].startswith("DriveSummaryLast")


# -- portability ---------------------------------------------------------------------------

def test_module_is_brand_free_and_light():
  """No car brand, fork, raylib or hard-coded zone in the module; openpilot imports only from common and
  itself, plus cereal (lazily) to read the GPS fix in tz.py."""
  allowed = ("openpilot.common.params_compat", "openpilot.common.time_helpers", "openpilot.common.swaglog",
             "openpilot.selfdrive.ui.tripstats", "openpilot.selfdrive.ui.layouts.settings.common")  # theme: optional, in a try
  for f in sorted(PKG.glob("*.py")):
    tree = ast.parse(f.read_text())
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    ok = allowed + (("openpilot.cereal",) if f.name == "tz.py" else ())
    assert all(not m.startswith(("openpilot", "opendbc", "cereal", "pyray")) or m.startswith(ok) for m in mods), (f.name, mods)
    tree.body = tree.body[1:]
    code = ast.unparse(tree).lower()
    for word in ("tesla", "jetlink", "gear", "park", "chicago", "america/", "asia/", "europe/", "australia/"):
      assert word not in code, (f.name, word)
  assert (PKG / "README.md").is_file()

