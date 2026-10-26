"""Trip summary card on a car with an ignition switch: at the offroad edge, SHOW_S on the onroad page,
then the stock scroll to home; swipe back to see it until the next drive. Real card, fake ui_state/clock."""
import importlib
import sys
import types
from pathlib import Path

import pytest

from openpilot.selfdrive.ui.lib import drive_summary as ds

UI = Path(__file__).resolve().parents[1]
FPS = 60


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


class Clock:
  def __init__(self):
    self.t = 1000.0

  def monotonic(self):
    return self.t


class World:
  """MiciMainLayout._handle_transitions + AugmentedRoadView._render's offroad branch and label, on the
  real card. page: "onroad" or "home" (the stock scroller, instant here)."""

  def __init__(self, dsc, monkeypatch, due=True):
    self.clock = Clock()
    self.ui = types.SimpleNamespace(started=True, ignition=True, params=None, is_metric=False)
    monkeypatch.setattr(dsc, "ui_state", self.ui)
    monkeypatch.setattr(dsc, "time", self.clock)
    monkeypatch.setattr(dsc.DriveSummaryCard, "draw", lambda self, *a: setattr(self, "drawn_y", a[1]))
    monkeypatch.setattr(ds, "enabled", lambda params: True)
    rec = ds.DriveRecorder()
    rec.active, rec.m, rec.e, rec.dur, rec.last_v = True, 5000.0 if due else 50.0, 4000.0, 600.0, 0.0
    monkeypatch.setattr(ds, "recorder", rec)
    self.card = dsc.DriveSummaryCard()
    self.page = "onroad"
    self.prev_onroad = True
    self.home_scrolls = 0
    self.shown: list = []

  def scroll_home(self):
    self.page = "home"
    self.home_scrolls += 1

  def frame(self):
    ui = self.ui
    if ui.ignition:                                           # main._handle_transitions
      self.card.clear()
    if ui.started != self.prev_onroad:
      self.prev_onroad = ui.started
      if not ui.started and (ui.ignition or not self.card.begin()):
        self.scroll_home()
    if self.card.update(self.page == "onroad"):
      self.scroll_home()
    rect = types.SimpleNamespace(x=0.0, y=0.0, width=536.0, height=240.0)
    if self.page == "onroad":                                  # AugmentedRoadView._render
      if not ui.started:
        if self.card.render(rect):
          shown = "card"
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
      setattr(self.ui, k, v)
    return [self.frame() for _ in range(max(1, int(seconds * FPS)))]


def test_ignition_off_card_then_home_then_slide_back(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  w.run(1)
  out = w.run(ds.SHOW_S - 0.1, started=False, ignition=False)
  assert set(out) == {"card"} and w.home_scrolls == 0
  w.run(0.2)
  assert w.page == "home" and w.home_scrolls == 1
  w.page = "onroad"                                 # swipe back
  assert set(w.run(30)) == {"card"} and w.home_scrolls == 1
  w.page = "home"
  w.page = "onroad"
  assert set(w.run(1)) == {"card"}
  w.run(1, ignition=True)                           # next drive: key on
  assert w.card.drive is None
  assert w.run(1, started=True)[-1] == "camera"


def test_tap_releases_the_hold(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  w.run(1)
  w.run(1, started=False, ignition=False)
  w.page = "home"
  w.run(ds.SHOW_S)
  assert w.home_scrolls == 0 and w.page == "home"


def test_short_trip_is_stock(dsc, monkeypatch):
  w = World(dsc, monkeypatch, due=False)
  w.run(1)
  out = w.run(1, started=False, ignition=False)
  assert w.home_scrolls == 1 and set(out) == {"home"}
  w.page = "onroad"
  assert set(w.run(1)) == {"start the car"}


def test_offroad_with_ignition_on_is_stock(dsc, monkeypatch):
  w = World(dsc, monkeypatch)
  w.run(1)
  out = w.run(1, started=False)                     # key still on: thermal, update, can't start
  assert w.home_scrolls == 1 and set(out) == {"home"} and w.card.drive is None


def test_hooks():
  main = (UI / "mici/layouts/main.py").read_text()
  trans = main.split("def _handle_transitions(self)")[1].split("\n  def ")[0]
  assert "if ui_state.ignition:   # trip summary" in trans and "elif ui_state.ignition or not self._summary.begin():" in trans
  assert "if self._summary.update(abs(self._onroad_layout.rect.x - self._rect.x) < 1):" in trans
  road = (UI / "mici/onroad/augmented_road_view.py").read_text()
  assert "if not (self._summary and self._summary.render(self._rect)):" in road
