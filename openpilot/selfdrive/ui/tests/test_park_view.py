"""Parked as a UI state: ParkView (lib/park_view.py) from parkd's ParkOffroadState, the trip summary card
as the onroad page's content while parked or off, slide back from home, brightness. No raylib window,
no msgq: the real DriveSummaryCard and ParkView run against a fake ui_state and a fake clock."""
import importlib
import sys
import types
from pathlib import Path

import pytest

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.car.park_offroad import NONE, PARKED, PARKING
from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import store
from openpilot.selfdrive.ui.lib.park_view import HOLD, JUMP, RETURN_S, ParkView

UI = Path(__file__).resolve().parents[1]
FPS = 60


# -- ParkView ------------------------------------------------------------------------------------

def feed(pv, t, seconds, started, ignition, state):
  for _ in range(int(seconds * FPS)):
    pv.update(t[0], started, ignition, state)
    t[0] += 1 / FPS


def test_parked_from_the_first_park_sample():
  pv, t = ParkView(), [0.0]
  feed(pv, t, 1, True, True, NONE)
  assert not pv.parked
  feed(pv, t, 1 / FPS, True, True, PARKING)
  assert pv.parked                                   # still onroad: the card can go up now
  feed(pv, t, 1, True, True, NONE)
  assert not pv.parked and not pv.returned           # shifted out within the hold: the trip goes on


def test_parked_bridges_the_gap_back_onroad():
  pv, t = ParkView(), [0.0]
  feed(pv, t, 3, True, True, PARKING)
  feed(pv, t, 5, False, True, PARKED)
  feed(pv, t, RETURN_S - 0.2, False, True, NONE)     # R/D: parkd let go, hardwared not started yet
  assert pv.parked                                   # no "can't start" in between
  feed(pv, t, 1 / FPS, True, True, NONE)
  assert not pv.parked and pv.returned


def test_parked_ends_if_onroad_never_comes():
  pv, t = ParkView(), [0.0]
  feed(pv, t, 3, False, True, PARKED)
  feed(pv, t, RETURN_S + 0.1, False, True, NONE)
  assert not pv.parked                               # a real failure: the stock label again


def test_ignition_off_ends_parked_and_return():
  pv, t = ParkView(), [0.0]
  feed(pv, t, 3, False, True, PARKED)
  feed(pv, t, 1, False, False, PARKED)
  assert not pv.parked
  feed(pv, t, 1, False, True, NONE)
  feed(pv, t, 1 / FPS, True, True, NONE)
  assert not pv.returned                             # a real ignition cycle: stock start


def test_toggle_off_is_stock():
  pv, t = ParkView(), [0.0]
  for started in (True, False, True, False):
    feed(pv, t, 1, started, True, NONE)
    assert not pv.parked and not pv.returned
    assert pv.brightness(t[0], started, True) is None


def test_brightness_hold_then_fade_then_jump():
  pv, t = ParkView(), [0.0]
  feed(pv, t, 1, True, True, PARKING)
  feed(pv, t, 2, False, True, PARKED)
  assert pv.brightness(t[0], False, False) == HOLD             # under the card
  feed(pv, t, ts.SHOW_S, False, True, PARKED)
  assert pv.brightness(t[0], False, False) is None             # after SHOW_S: the normal offroad fade
  feed(pv, t, 1 / FPS, True, True, NONE)
  assert pv.brightness(t[0], True, False) is None              # no camera reading yet
  assert pv.brightness(t[0], True, True) == JUMP
  assert pv.brightness(t[0], True, True) is None               # once


def test_brightness_sim():
  """Device._update_brightness: offroad 65, camera target 99, 10 s filter, 60 fps."""
  pv, t = ParkView(), [0.0]
  f = FirstOrderFilter(99, 10.0, 1 / FPS)
  out = []

  def step(started, state, cam, target):
    pv.update(t[0], started, True, state)
    act = pv.brightness(t[0], started, cam)
    if act == HOLD:
      b = f.x
    elif act == JUMP:
      f.x = b = target
    else:
      b = f.update(target)
    out.append(round(b))
    t[0] += 1 / FPS
  for _ in range(3 * FPS):
    step(True, PARKING, True, 99)
  for _ in range(30 * FPS):
    step(False, PARKED, False, 65)
  back = len(out)
  for i in range(2 * FPS):
    step(True, NONE, i >= int(0.8 * FPS), 99)
  assert min(out[:3 * FPS + int((ts.SHOW_S - 3.1) * FPS)]) >= 98     # readable while the card holds
  assert out[back - 1] < 80                                          # then the normal fade
  assert out[back + int(0.8 * FPS)] == 99                            # first camera reading: straight there


# -- the card + main layout + onroad page, simulated --------------------------------------------

class Clock:
  def __init__(self):
    self.t = 1000.0

  def monotonic(self):
    return self.t


@pytest.fixture
def dsc(monkeypatch):
  if "openpilot.selfdrive.ui.ui_state" not in sys.modules:
    mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
    mod.ui_state = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.ui_state", mod)
  return importlib.import_module("openpilot.selfdrive.ui.mici.widgets.drive_summary_card")


def test_slide_in_smooth_no_overshoot(dsc):
  ys = [dsc.slide_y(i / FPS, 240) for i in range(FPS)]
  assert ys[0] == -240 and ys[1] < -0.8 * 240                     # starts fully above the screen
  assert all(b >= a for a, b in zip(ys, ys[1:], strict=False))   # only ever moves down
  assert max(ys) == 0.0                                           # no overshoot
  n = next(i for i, y in enumerate(ys) if y == 0.0)
  assert 0.25 <= dsc.ENTER_S <= 0.3 and abs(n / FPS - dsc.ENTER_S) <= 1.5 / FPS


class World:
  """MiciMainLayout._handle_transitions + AugmentedRoadView._render's offroad branch and label, on the
  real card and ParkView. page: "onroad" or "home" (the stock scroller, instant here)."""

  def __init__(self, dsc, monkeypatch, due=True):
    self.clock = Clock()
    self.ui = types.SimpleNamespace(started=True, ignition=True, params=None, is_metric=False, park=ParkView())
    monkeypatch.setattr(dsc, "ui_state", self.ui)
    monkeypatch.setattr(dsc, "time", self.clock)
    monkeypatch.setattr(dsc.DriveSummaryCard, "draw", lambda self, *a: setattr(self, "drawn_y", a[1]))
    monkeypatch.setattr(ts, "enabled", lambda params: True)
    rec = ts.DriveRecorder()
    rec.active, rec.m, rec.e, rec.dur, rec.last_v = True, 5000.0 if due else 50.0, 4000.0, 600.0, 0.0
    monkeypatch.setattr(ts, "live", rec)
    monkeypatch.setattr(ts, "_data", store.load(None))
    monkeypatch.setattr(ts, "_held", [])
    self.card = dsc.DriveSummaryCard()
    self.page, self.state = "onroad", NONE
    self.prev_onroad, self.prev_parked = True, False
    self.home_scrolls = 0
    self.shown: list = []

  def scroll_home(self):
    self.page = "home"
    self.home_scrolls += 1

  def frame(self):
    ui = self.ui
    ui.park.update(self.clock.t, ui.started, ui.ignition, self.state)
    parked = ui.park.parked                                   # main._handle_transitions
    if ui.ignition and not parked and (ui.started or not self.card.last):
      self.card.clear()
    elif parked and not self.prev_parked:
      self.card.begin()
    self.prev_parked = parked
    if ui.started != self.prev_onroad:
      self.prev_onroad = ui.started
      if not ui.started and self.card.drive is None and not self.card.begin():
        self.scroll_home()
    if self.card.update(self.page == "onroad"):
      self.scroll_home()
    rect = types.SimpleNamespace(x=0.0, y=0.0, width=536.0, height=240.0)
    if self.page == "onroad":                                  # AugmentedRoadView._render
      if not ui.started:
        if self.card.render(rect):
          shown = "card"
        elif ui.park.parked:
          shown = "shift to D or R"
        elif ui.ignition:
          shown = "openpilot can't start"
        else:
          shown = "start the car"
      else:
        shown = "card" if self.card.render(rect) else "camera"
    else:
      shown = "home"
    self.shown.append(shown)
    self.clock.t += 1 / FPS
    return shown

  def run(self, seconds, **kw):
    for k, v in kw.items():
      setattr(self.ui, k, v) if k != "state" else setattr(self, "state", v)
    return [self.frame() for _ in range(max(1, int(seconds * FPS)))]


def park_offroad(w):
  w.run(1, state=NONE)                              # driving
  w.run(3, state=PARKING)                           # first Park sample: card slides in over the camera
  return w.run(0.5, state=PARKED, started=False)    # offroad the normal way


def test_card_at_park_then_home_then_slide_back(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  w.run(1)
  parking = w.run(3, state=PARKING)
  assert parking[0] == "card" and set(parking) == {"card"}
  offroad = w.run(0.5, state=PARKED, started=False)
  assert set(offroad) == {"card"}                   # never the "can't start" label behind it
  w.run(ts.SHOW_S - 3.6)
  assert w.page == "onroad" and w.home_scrolls == 0
  w.run(0.2)
  assert w.page == "home" and w.home_scrolls == 1   # SHOW_S from Park: the stock scroll to home
  w.page = "onroad"                                 # swipe back
  assert set(w.run(5)) == {"card"} and w.home_scrolls == 1
  w.page = "home"                                   # and home again
  w.page = "onroad"
  assert set(w.run(1)) == {"card"}
  back = w.run(1, state=NONE)                       # D: parkd lets go ...
  assert "can't start" not in " ".join(back)
  assert w.run(1, started=True)[-1] == "camera"     # ... onroad: card gone, a new drive
  assert w.ui.park.returned and w.card.drive is None


def test_tap_or_swipe_releases_the_hold(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  park_offroad(w)
  w.page = "home"                                   # tap: the stock click callback scrolls home
  w.run(ts.SHOW_S)
  assert w.home_scrolls == 0 and w.page == "home"   # no second scroll later


def test_shift_out_within_the_hold_cuts_the_card(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  w.run(1)
  w.run(1, state=PARKING)
  assert w.run(0.1, state=NONE)[-1] == "camera" and w.card.drive is None


def test_short_trip_parked_shows_the_parked_label(dsc, monkeypatch):
  w = World(dsc, monkeypatch, due=False)
  park_offroad(w)
  assert w.page == "home" and w.home_scrolls == 1   # stock: straight to home
  w.page = "onroad"
  assert set(w.run(1)) == {"shift to D or R"}


def test_ignition_off_keeps_the_card_until_the_next_drive(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  park_offroad(w)
  w.run(5.5, ignition=False)
  w.run(5, state=NONE)                              # parkd: a real ignition cycle clears the latch
  w.page = "onroad"
  assert set(w.run(1)) == {"card"}
  w.run(0.5, ignition=True)                         # next drive: key on
  assert w.card.drive is None


def test_stock_ignition_off_card_then_home_then_slide_back(dsc, monkeypatch):
  """No park-offroad (toggle off, or a car with an ignition switch): the card at the offroad edge."""
  w = World(dsc, monkeypatch)
  w.run(1)
  out = w.run(ts.SHOW_S - 0.1, started=False, ignition=False)
  assert set(out) == {"card"} and w.home_scrolls == 0
  w.run(0.2)
  assert w.page == "home" and w.home_scrolls == 1
  w.page = "onroad"
  assert set(w.run(30)) == {"card"}
  w.run(1, ignition=True)
  assert w.card.drive is None
  assert w.run(1, started=True)[-1] == "camera" and not w.ui.park.returned


def test_toggle_off_short_trip_is_stock(dsc, monkeypatch):
  w = World(dsc, monkeypatch, due=False)
  w.run(1)
  out = w.run(1, started=False, ignition=False)
  assert w.home_scrolls == 1 and set(out) == {"home"}


def test_last_trip_card_at_start_holds_until_onroad(dsc, monkeypatch):
  """Powered only with ignition: the drive's card never came up. At the next start (key on, not started
  yet) the last trip summary card holds the onroad page, then goes for the camera; the Tesla Park path never gets here."""
  w = World(dsc, monkeypatch)
  last = {**store.stamp({"id": "r", "m": 5000.0, "e": 4000.0, "best_m": 900.0, "dur": 600.0, "tl": "ee"}, 1.79e9), "shown": False}
  monkeypatch.setattr(ts, "live", ts.DriveRecorder())
  monkeypatch.setattr(ts, "_data", {**store.load(None), "last": last})
  w.ui.started, w.prev_onroad = False, False
  assert w.card.begin(last=True) and w.card.last and w.card._head == dsc.LAST_HEADLINE == "last trip summary"
  assert ts.missed_trip(None) is None                       # shown once (marked in memory; params=None here)
  assert set(w.run(2)) == {"card"}                           # ignition on, not started: holds
  assert w.run(0.1, started=True)[-1] == "camera" and w.card.drive is None


# -- hooks -------------------------------------------------------------------------------------

def test_hooks():
  ui = (UI / "ui_state.py").read_text()
  assert "self.park.update(time.monotonic(), self.started, self.ignition, self._park_state)" in ui
  assert "park_offroad.get_state(self.params) if park_offroad.enabled(self.params)" in ui
  assert "ui_state.park.brightness(time.monotonic(), ui_state.started, ui_state.light_sensor >= 0)" in ui
  assert "self._brightness_filter = FirstOrderFilter(BACKLIGHT_OFFROAD, 10.00" in ui          # stock filter kept
  main = (UI / "mici/layouts/main.py").read_text()
  trans = main.split("def _handle_transitions(self)")[1].split("\n  def ")[0]
  assert "if ui_state.ignition and not parked and (ui_state.started or not self._summary.last):\n      self._summary.clear()" in trans
  assert "self._summary.begin(last=True)" in trans and "self._last_trip_at = rl.get_time() + LAST_TRIP_DELAY" in main
  assert "elif parked and not self._prev_parked:\n      self._summary.begin()" in trans
  assert "elif self._summary.drive is None and not self._summary.begin():" in trans
  assert "if self._summary.update(abs(self._onroad_layout.rect.x - self._rect.x) < 1):" in trans
  assert "if ui_state.park.returned:" in trans and "ONROAD_DELAY = 2.5" in main
  road = (UI / "mici/onroad/augmented_road_view.py").read_text()
  assert "if not (self._summary and self._summary.render(self._rect)):" in road
  label = road.split("class AugmentedRoadView")[1].split("def _update_state(self)")[1].split("\n  def ")[0]
  assert label.index("ui_state.park.parked") < label.index("openpilot can't start")
  card = (UI / "mici/widgets/drive_summary_card.py").read_text()
  for word in ("tesla", "jetlink", "park_offroad", "parkd"):
    assert word not in card.lower(), word                                                    # the card stays portable
