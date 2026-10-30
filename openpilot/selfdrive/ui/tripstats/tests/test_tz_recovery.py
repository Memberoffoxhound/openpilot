"""Time zone (offline GPS lookup, then the system zone), stamped drives that don't move when the zone does,
power-loss recovery at the last stamp, and the last trip summary card's shown flag."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import recorder as rc, store, tz
from openpilot.selfdrive.ui.tripstats.tests.test_store import Params, World, drv, fresh



def utc(s: str) -> float:
  return datetime.fromisoformat(s + "+00:00").timestamp()


def fix(lat: float, lon: float) -> bytes:
  from openpilot.cereal import log
  m = log.Event.new_message()
  g = m.init("gpsLocationExternal")
  g.latitude, g.longitude, g.hasFix = lat, lon, True
  return m.to_bytes()


# -- the zone -------------------------------------------------------------------------------

@pytest.mark.parametrize("lat,lon,zone", [
  (41.88, -87.63, "America/Chicago"), (35.68, 139.69, "Asia/Tokyo"), (51.50, -0.12, "Europe/London"),
  (-33.87, 151.21, "Australia/Sydney"), (28.61, 77.21, "Asia/Kolkata"), (39.74, -104.99, "America/Denver"),
  (33.45, -112.07, "America/Phoenix"), (-23.55, -46.63, "America/Sao_Paulo"), (-36.85, 174.76, "Pacific/Auckland"),
  (52.52, 13.40, "Europe/Berlin"), (37.77, -122.42, "America/Los_Angeles"), (1.35, 103.82, "Asia/Singapore"),
])
def test_offline_lookup(lat, lon, zone):
  assert tz.zone_at(lat, lon) == zone


def test_grid_is_small_and_complete():
  assert tz.GRID.stat().st_size < 256 * 1024
  assert tz.zone_at(90, 0) and tz.zone_at(-90, 0) and tz.zone_at(0, -180) == tz.zone_at(0, 180)


def test_gps_zone_else_system_zone(tmp_path):
  p = Params(tmp_path)
  assert tz.current(p)[2] == "system" and tz.zone(p) is None                       # no fix yet: system zone
  p.d[tz.PARAM] = "Asia/Tokyo"
  assert tz.current(p)[1:] == ("Asia/Tokyo", "gps") and tz.zone(p) == ZoneInfo("Asia/Tokyo")
  p.d["TimezoneOverride"] = "Europe/London"                                         # left over from an old build: ignored
  assert tz.current(p)[1:] == ("Asia/Tokyo", "gps")
  assert not hasattr(tz, "set_override") and not hasattr(tz, "PARAM_OVERRIDE")
  p.d[tz.PARAM] = "Not/AZone"
  assert tz.zone(p) is None and tz.current(p)[2] == "system"                        # unknown here: system zone


def test_update_from_last_gps_position(tmp_path):
  p = Params(tmp_path)
  assert tz.update(p) is None                                  # no fix yet
  p.d["LastGPSPosition"] = fix(35.68, 139.69)
  assert tz.update(p) == "Asia/Tokyo" and p.d[tz.PARAM] == "Asia/Tokyo"
  assert tz.update(p) is None                                  # unchanged: no write


def test_lookup_runs_off_the_ui_thread_after_the_ui_is_up(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path)
  w.params.d["LastGPSPosition"] = fix(35.68, 139.69)
  ran = []
  monkeypatch.setattr(ts.threading, "Thread", lambda target, args, **kw: type("T", (), {"start": lambda s: ran.append(target(*args))})())
  w.run(ts.LOOKUP_S[0] - 1)
  assert ran == [] and tz.PARAM not in w.params.d              # not at boot
  w.run(2)
  assert len(ran) == 1 and w.params.d[tz.PARAM] == "Asia/Tokyo"


# -- stamped drives: a zone change never moves them -----------------------------------------

def test_drive_keeps_its_day_when_the_zone_changes():
  w = utc("2026-10-30T03:30:00")                               # 22:30 Oct 29 Chicago, 12:30 Oct 30 Tokyo
  d = store.add_drive(fresh(), store.stamp(drv(m=1000.0), w, ZoneInfo("America/Chicago")))
  assert d["last"]["off"] == -5 * 3600 and list(d["days"]) == ["2026-10-29"]
  tokyo = ZoneInfo("Asia/Tokyo")
  d = store.add_drive(d, store.stamp(drv(m=500.0), w + 3600, tokyo))     # flew to Tokyo, drove
  assert d["days"] == {"2026-10-29": [1000.0, 800.0], "2026-10-30": [500.0, 800.0]}
  v = store.view(d, at=datetime.fromtimestamp(w + 7200, UTC), tz=tokyo)
  assert v["today_m"] == 500 and v["week_m"] == 1500           # Thu + Fri, same Tokyo week


def test_dst_offset_is_stored_per_drive():
  z = ZoneInfo("America/Chicago")
  before, after = utc("2026-11-01T06:30:00"), utc("2026-11-01T07:30:00")    # 01:30 CDT, then 01:30 CST
  assert store.stamp(drv(), before, z)["off"] == -5 * 3600 and store.stamp(drv(), after, z)["off"] == -6 * 3600


def test_tick_dates_by_the_zone_param(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path, start=utc("2026-10-30T03:00:00"))     # 22:00 Chicago (system), 12:00 Tokyo
  w.params.d[tz.PARAM] = "Asia/Tokyo"
  w.run(1, started=True)
  w.run(20, v=10.0)
  w.run(rc.MERGE_S + 0.2, v=0.0, started=False)
  d = w.stored()
  assert list(d["days"]) == ["2026-10-30"] and d["last"]["off"] == 9 * 3600
  assert ts.view(w.params)["today_m"] == pytest.approx(200, rel=0.02)


# -- power loss -----------------------------------------------------------------------------

def test_power_cut_mid_drive_closes_at_the_last_stamp_on_a_stale_clock(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path, start=utc("2026-10-30T04:59:00"))     # 23:59 Oct 29 Chicago
  w.run(1, started=True)
  w.run(ts.SAVE_S + 1, v=20.0, engaged=True)                             # saved at 23:59:31
  saved = w.stored()["open"][0]
  assert saved["ok"] and saved["off"] == -5 * 3600 and saved["end"] == pytest.approx(utc("2026-10-30T04:59:31"), abs=1)
  w.run(25)                                                              # past midnight, then the power went
  w.restart(monkeypatch)
  w.ui.started, w.wall, w.valid = False, utc("2026-07-04T12:00:00"), False   # boots offroad on a stale clock
  w.run(0.05)
  d = w.stored()
  assert d["days"] == {"2026-10-29": [pytest.approx(saved["m"]), pytest.approx(saved["e"])]} and d["open"] == []
  assert d["last"]["end"] == saved["end"] and not d["last"]["shown"]   # dated at its stamp, before the clock is valid


def test_open_stamped_on_a_stale_clock_waits(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path, start=utc("2026-07-04T12:00:00"), valid=False)
  w.run(1, started=True)
  w.run(ts.SAVE_S + 1, v=20.0)
  assert not w.stored()["open"][0]["ok"]
  w.restart(monkeypatch)
  w.ui.started = False
  w.run(0.05)
  assert w.stored()["days"] == {} and len(w.stored()["open"]) == 1       # still held, never on July 4
  w.wall, w.valid = utc("2026-10-30T15:00:00"), True
  w.run(0.05)
  assert list(w.stored()["days"]) == ["2026-10-30"]


# -- the last trip summary card ---------------------------------------------------------------------

def test_last_trip_once_when_its_card_never_came_up(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path)
  w.run(1, started=True)
  w.run(ts.SAVE_S + 1, v=20.0, engaged=True)
  saved = w.stored()["open"][0]
  w.restart(monkeypatch)                                       # power cut at ignition off: no card, no offroad edge
  w.ui.started = False
  w.wall += 3600
  w.run(0.05)
  last = ts.missed_trip(w.params)
  assert last is not None and last["m"] == saved["m"] and last["end"] == saved["end"]
  v = ts.view(w.params, last)
  assert v["today_m"] == pytest.approx(last["m"])               # the card's Day / Week as of that trip
  ts.mark_shown(w.params, last)
  assert ts.missed_trip(w.params) is None and w.stored()["last"]["shown"]
  w.restart(monkeypatch)
  w.run(0.05)
  assert ts.missed_trip(w.params) is None                      # once, across restarts too


def test_no_last_trip_after_a_normal_card_or_with_the_toggle_off(monkeypatch, tmp_path):
  w = World(monkeypatch, tmp_path)
  w.run(1, started=True)
  w.run(40, v=20.0)
  w.run(1, v=0.0)
  w.run(0.05, started=False)
  assert ts.due_summary(w.params) is not None
  ts.mark_shown(w.params)                                      # the card is up (ignition or Park path)
  assert w.stored()["open"][0]["shown"]                        # stored at once: a power cut now won't repeat it
  w.run(rc.MERGE_S + 0.2)
  assert w.stored()["last"]["shown"] and ts.missed_trip(w.params) is None
  w.run(1, started=True)
  w.run(ts.SAVE_S + 1, v=20.0)
  w.restart(monkeypatch)
  w.ui.started = False
  w.params.d["DriveSummary"] = False
  w.run(0.05)
  assert ts.missed_trip(w.params) is None                      # toggle off: no card


def test_web_gui_shows_the_zone_but_cannot_set_it(monkeypatch, tmp_path):
  import json
  stats = pytest.importorskip("openpilot.system.webgui.stats")   # a fork without the web GUI skips this
  webgui = pytest.importorskip("openpilot.system.webgui.webgui")
  p = Params(tmp_path)
  monkeypatch.setattr("openpilot.common.params.Params", lambda: p)
  assert not hasattr(webgui.App, "set_timezone")
  p.d[tz.PARAM] = "Asia/Tokyo"
  assert stats._collect(str(tmp_path))["timezone"] == {"name": "Asia/Tokyo", "source": "gps"}
  assert json.dumps(stats.mock()["timezone"])
  html = webgui.STATIC.read_text()
  assert "/api/timezone" not in html and "tzSet" not in html
