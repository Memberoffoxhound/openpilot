"""Where the week starts: the country of the GPS zone (CLDR), Sunday with no zone, and the current week rule
applied to stored days without moving any of them."""
import copy
import json
import zlib
from zoneinfo import ZoneInfo

import pytest

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import store, tz
from openpilot.selfdrive.ui.tripstats.tests.test_store import World, add, at, drv, fresh, wall

MON, FRI, SAT, SUN = 0, 4, 5, 6


@pytest.mark.parametrize("zone,first", [
  ("America/Chicago", SUN), ("America/Toronto", SUN), ("America/Mexico_City", SUN), ("Asia/Tokyo", SUN),
  ("America/Sao_Paulo", SUN), ("Asia/Kolkata", SUN), ("Asia/Jerusalem", SUN),
  ("Europe/London", MON), ("Europe/Berlin", MON), ("Europe/Paris", MON), ("Australia/Sydney", MON),
  ("Pacific/Auckland", MON), ("Asia/Shanghai", MON), ("Europe/Moscow", MON),
  ("Africa/Cairo", SAT), ("Asia/Tehran", SAT), ("Indian/Maldives", FRI),
])
def test_first_day_by_country(zone, first):
  assert tz.first_day(zone) == first and tz.first_day(ZoneInfo(zone)) == first


@pytest.mark.parametrize("zone", [None, "", "Etc/UTC", "Etc/GMT+5", "garbage"])
def test_unknown_zone_is_sunday(zone):
  assert tz.first_day(zone) == SUN


def test_missing_table_is_sunday(monkeypatch):
  def gone():
    raise OSError("no weekstart.json")
  monkeypatch.setattr(tz, "_week_table", gone)
  assert tz.first_day("Europe/Berlin") == SUN


def test_table_matches_the_grid():
  """Every zone weekstart.json names is one tzgrid.bin can return, and the file stays tiny."""
  t = json.loads(tz.WEEK.read_text())
  grid = set(json.loads(zlib.decompress(tz.GRID.read_bytes()).split(b"\n", 1)[0])["zones"])
  listed = [z for zs in t["zones"].values() for z in zs]
  assert set(t["zones"]) <= set(tz.DAYS) and t["default"] == "mon" and t["unknown"] == "sun"
  assert len(listed) == len(set(listed)) and set(listed) <= grid
  assert tz.WEEK.stat().st_size < 8000


def test_monday_week():
  d = fresh()
  for day, m in ((25, 100.0), (26, 200.0), (28, 400.0), (1, 800.0)):    # Sun 25, Mon 26, Wed 28, Sun Nov 1
    d = add(d, drv(m=m), wall(2026, 10 if day > 1 else 11, day, 12))
  v = store.view(d, at=at(2026, 11, 1, 20), first=MON)                 # Sunday night: the week's last day
  assert [w["id"] for w in v["week_days"]][::6] == ["2026-10-26", "2026-11-01"]
  assert v["week_m"] == 200 + 400 + 800 and v["today_i"] == 6
  v = store.view(d, at=at(2026, 10, 26, 0, 0, 1), first=MON)           # Monday just after midnight: new week
  assert v["week_days"][0]["id"] == "2026-10-26" and v["week_m"] == 1400 and v["today_i"] == 0   # whole week, as stored


def test_saturday_week():
  d = add(fresh(), drv(m=300.0), wall(2026, 10, 30, 12))               # Fri 30
  d = add(d, drv(m=500.0), wall(2026, 10, 31, 12))                     # Sat 31
  v = store.view(d, at=at(2026, 10, 31, 13), first=SAT)
  assert v["week_days"][0]["id"] == "2026-10-31" and v["week_m"] == 500 and v["today_i"] == 0


def test_rule_change_rebuckets_but_never_moves_days():
  """Cross from the US into Canada or Europe mid-week: days keep their dates, only the current week window moves."""
  d = fresh()
  for day in (24, 25, 26, 27, 28):                                     # Sat .. Wed, 100 m each
    d = add(d, drv(m=100.0), wall(2026, 10, day, 12))
  before = copy.deepcopy(d)
  sun, mon = store.view(d, at=at(2026, 10, 28, 18), first=SUN), store.view(d, at=at(2026, 10, 28, 18), first=MON)
  assert sun["week_m"] == 400 and mon["week_m"] == 300                  # Sun 25..Wed vs Mon 26..Wed
  assert sun["today_m"] == mon["today_m"] == 100 and sun["life_m"] == mon["life_m"] == 500
  assert d == before                                                    # the view never rewrites stored days


def test_ui_uses_the_gps_zone_rule(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path, start=wall(2026, 10, 28, 12))       # Wednesday
  assert ts.view(w.params)["week_days"][0]["id"] == "2026-10-25"       # no GPS zone yet: Sunday
  w.params.d[tz.PARAM] = "Europe/Berlin"
  w.restart(monkeypatch)
  assert ts.view(w.params)["week_days"][0]["id"] == "2026-10-26"       # Monday
  w.params.d[tz.PARAM] = "America/Toronto"
  w.restart(monkeypatch)
  assert ts.view(w.params)["week_days"][0]["id"] == "2026-10-25"


def test_statistics_rows_follow_the_week():
  pytest.importorskip("pyray")
  from openpilot.selfdrive.ui.mici.layouts.settings.stats import _week_labels
  assert _week_labels(store.view(fresh(), at=at(2026, 10, 28, 12), first=MON)["week_days"])[::6] == ["Mon", "Sun"]
  assert _week_labels(store.view(fresh(), at=at(2026, 10, 28, 12), first=SAT)["week_days"])[:2] == ["Sat", "Sun"]
  assert _week_labels([{"m": 0.0}] * 7)[0] == "Sun"                   # mock rows without dates
