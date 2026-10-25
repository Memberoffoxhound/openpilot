"""Park-offroad glue for the trip card (selfdrive/ui/lib/park_card.py): the card the moment the car
is shifted into Park, and the fast way back onroad (no ONROAD_DELAY, no 10 s brightness ramp).
No raylib window, no msgq: the real DriveSummaryCard runs against a fake ui_state."""
import importlib
import sys
import types
from pathlib import Path

import pytest

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.lib import drive_summary as ds
from openpilot.selfdrive.ui.lib import park_card as pc
from openpilot.selfdrive.ui.lib.park_card import CUT, HOLD, JUMP, SHOW, ParkEarly, ParkReturn

UI = Path(__file__).resolve().parents[1]
FPS = 60


def run(pe, seconds, gear, t, on=True, started=True, v=0.0, engaged=False, hz=20):
  evs = []
  for _ in range(int(seconds * hz)):
    ev = pe.update(on, started, t[0], gear, v, engaged)
    if ev:
      evs.append((round(t[0], 2), ev))
    t[0] += 1 / hz
  return evs


# -- ParkEarly ------------------------------------------------------------------------------------

def test_early_card_at_park_after_drive():
  pe, t = ParkEarly(), [0.0]
  assert run(pe, 5, "drive", t, v=10.0) == []
  run(pe, 1, "drive", t, v=0.0)
  start = t[0]
  evs = run(pe, 3, "park", t)
  assert evs == [(round(start, 2), SHOW)]            # the first Park frame, not after the 3 s hold
  assert run(pe, 1, "park", t, started=False) == []   # offroad edge: the card's hand-off takes over


def test_early_card_needs_r_or_d_first_like_parkd():
  pe, t = ParkEarly(), [0.0]
  assert run(pe, 10, "park", t) == []                 # ignition in Park, never left it: parkd isn't armed
  run(pe, 1, "reverse", t)
  assert [e for _, e in run(pe, 1, "park", t)] == [SHOW]


def test_early_card_not_while_moving_or_engaged():
  pe, t = ParkEarly(), [0.0]
  run(pe, 1, "drive", t)
  assert run(pe, 1, "park", t, engaged=True) == []    # parkd never parks while engaged
  pe, t = ParkEarly(), [0.0]
  run(pe, 1, "drive", t)
  assert run(pe, 0.5, "park", t, v=2.0) == []          # still rolling
  assert [e for _, e in run(pe, 0.5, "park", t)] == [SHOW]


def test_early_card_cut_on_quick_shift_out_of_park():
  pe, t = ParkEarly(), [0.0]
  run(pe, 1, "drive", t)
  assert [e for _, e in run(pe, 1.0, "park", t)] == [SHOW]
  assert [e for _, e in run(pe, 1.0, "reverse", t)] == [CUT]     # 3-point turn: P -> R inside the hold
  assert [e for _, e in run(pe, 1.0, "park", t)] == [SHOW]       # and again on the next Park
  assert [e for _, e in run(pe, 1.0, "neutral", t)] == [CUT]


def test_early_card_gives_up_if_park_offroad_never_comes():
  pe, t = ParkEarly(), [0.0]
  run(pe, 1, "drive", t)
  evs = run(pe, 10, "park", t)
  assert [e for _, e in evs] == [SHOW, CUT]
  assert evs[1][0] - evs[0][0] == pytest.approx(pc.GIVEUP_S, abs=0.1)
  assert run(pe, 10, "park", t) == []                  # no second try until R/D again


def test_early_card_toggle_off_is_stock():
  pe, t = ParkEarly(), [0.0]
  run(pe, 1, "drive", t, on=False)
  assert run(pe, 10, "park", t, on=False) == []
  pe, t = ParkEarly(), [0.0]
  run(pe, 1, "drive", t)
  run(pe, 0.5, "park", t)
  assert [e for _, e in run(pe, 0.5, "park", t, on=False)] == [CUT]   # turned off with the card up


def test_early_event_reads_ui_state(monkeypatch):
  cs = types.SimpleNamespace(gearShifter="drive", vEgo=0.0)

  class SM(dict):
    recv_frame = {"carState": 5}
  fake = types.SimpleNamespace(started=True, started_frame=0, engaged=False, params=None, sm=SM(carState=cs))
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state = fake
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.ui_state", mod)
  monkeypatch.setattr(pc, "_early", ParkEarly())
  monkeypatch.setattr(pc, "_on", lambda params: True)
  assert pc.early_event() is None
  cs.gearShifter = "park"
  assert pc.early_event() == SHOW
  monkeypatch.setattr(pc, "_on", lambda params: False)
  assert pc.early_event() == CUT


def test_on_needs_both_toggles(monkeypatch):
  from openpilot.selfdrive.car import park_offroad
  vals = {}
  monkeypatch.setattr(park_offroad, "enabled", lambda params: vals.get("ParkOffroad", False))
  monkeypatch.setattr(ds, "get_bool", lambda params, key, default=False: vals.get(key, default))
  for po, dsum, want in ((True, True, True), (True, False, False), (False, True, False)):
    vals.update(ParkOffroad=po, DriveSummary=dsum)
    monkeypatch.setattr(pc, "_on_cache", (-1e9, False))
    assert pc._on(None) is want


# -- the real card with early_fn -------------------------------------------------------------------

class Clock:
  def __init__(self):
    self.t = 1000.0

  def monotonic(self):
    return self.t


@pytest.fixture
def card_env(monkeypatch):
  if "openpilot.selfdrive.ui.ui_state" not in sys.modules:
    mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
    mod.ui_state = types.SimpleNamespace(started=False)
    monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.ui_state", mod)
  dsc = importlib.import_module("openpilot.selfdrive.ui.mici.widgets.drive_summary_card")
  ui = types.SimpleNamespace(started=True, params=None, is_metric=False)
  clock = Clock()
  monkeypatch.setattr(dsc, "ui_state", ui)
  monkeypatch.setattr(dsc, "time", clock)
  monkeypatch.setattr(ds, "enabled", lambda params: True)
  rec = ds.DriveRecorder()
  rec.active, rec.m, rec.e, rec.dur, rec.last_v, rec.drive_id = True, 5000.0, 4000.0, 600.0, 0.0, "route1"
  monkeypatch.setattr(ds, "recorder", rec)
  monkeypatch.setattr(dsc.DriveSummaryCard, "draw", lambda self, *a, **k: None)
  events = []
  card = dsc.DriveSummaryCard(early_fn=lambda: events.pop(0) if events else None)
  rect = types.SimpleNamespace(x=0.0, y=0.0, width=536.0, height=240.0)

  def frame(page_x=0.0):
    rel = card.release_home()
    card.render(rect, page_x)
    clock.t += 1 / FPS
    return rel
  return types.SimpleNamespace(card=card, ui=ui, clock=clock, events=events, frame=frame, rec=rec, dsc=dsc)


def test_card_shows_at_park_while_still_onroad(card_env):
  e = card_env
  e.frame()
  assert not e.card.visible
  e.events.append(SHOW)
  e.frame()
  assert e.card.visible and e.ui.started and e.rec.shown and ds.card_on_screen is False   # onroad: camera brightness
  shown_at = e.card._shown_at
  for _ in range(3 * FPS):                                   # parkd's 3 s hold, still onroad
    assert e.frame() is False
  e.ui.started = False                                       # park-offroad: the offroad edge
  assert e.card.hold_home() is True                          # keeps holding the stock scroll
  assert e.card._shown_at == shown_at                        # no restart, no second slide-in
  e.frame()
  assert ds.card_on_screen is True
  while not e.frame():
    pass
  assert e.clock.t - shown_at == pytest.approx(ds.SHOW_S, abs=3 / FPS)   # SHOW_S counted from Park


def test_card_cut_when_the_trip_goes_on(card_env):
  e = card_env
  e.events.append(SHOW)
  e.frame()
  assert e.card.visible
  e.events.append(CUT)
  e.frame()
  assert not e.card.visible and not e.card._slide.drawn and not e.rec.shown
  e.ui.started = False                                       # a later real end shows it normally
  assert e.card.hold_home() is True and e.card.visible


def test_tap_while_early_leaves_at_the_offroad_edge(card_env):
  e = card_env
  e.events.append(SHOW)
  e.frame()
  assert e.card.dismiss_on_tap() is True                     # the tap is eaten
  e.frame()
  assert e.card.visible                                      # still onroad: nothing to scroll to yet
  e.ui.started = False
  assert e.card.hold_home() is False                         # stock scroll to home right away
  assert e.card._slide.state == "leaving"                    # and the card rides the onroad page off


def test_no_early_fn_is_unchanged(card_env):
  e = card_env
  card = e.dsc.DriveSummaryCard()
  e.card = card
  rect = types.SimpleNamespace(x=0.0, y=0.0, width=536.0, height=240.0)
  for _ in range(10):
    card.release_home()
    card.render(rect, 0.0)
  assert not card.visible
  e.ui.started = False
  assert card.hold_home() is True and card.visible


def test_onroad_edge_cuts_early_state(card_env):
  e = card_env
  e.events.append(SHOW)
  e.frame()
  e.card.cancel()
  assert not e.card._early and not e.card.visible


# -- back onroad: ParkReturn ---------------------------------------------------------------------

def test_park_return_latched_through_param_clear():
  pr = ParkReturn()
  pr.update(True, True, False)
  assert not pr.returned
  pr.update(False, True, True)                 # parked offroad
  pr.update(False, True, False)                # parkd clears the param on R/D a moment before onroad
  pr.update(True, True, False)
  assert pr.returned
  pr.update(True, True, False)
  assert pr.returned                           # the whole session
  pr.update(False, True, False)
  assert not pr.returned


def test_park_return_cleared_by_real_ignition_cycle():
  pr = ParkReturn()
  pr.update(False, True, True)
  pr.update(False, False, False)               # ignition off >= 5 s: parkd's latch (and param) cleared
  pr.update(False, True, False)
  pr.update(True, True, False)                 # ignition on in Park: stock onroad
  assert not pr.returned


def test_park_return_blip_keeps_latch():
  pr = ParkReturn()
  pr.update(False, True, True)
  pr.update(False, False, True)                # short ignitionCan blip, parkd keeps the latch
  pr.update(False, True, True)
  pr.update(False, True, False)
  pr.update(True, True, False)
  assert pr.returned


def test_toggle_off_never_park_return():
  pr = ParkReturn()
  for started in (True, False, True, False, True):
    pr.update(started, True, False)            # ParkOffroadActive is never set with the toggle off
    assert not pr.returned
    assert pr.brightness(started, False, True, True) is None


def test_brightness_hold_and_jump():
  pr = ParkReturn()
  pr.update(False, True, True)
  assert pr.brightness(False, True, True, False) == HOLD      # parked offroad, card up
  assert pr.brightness(False, True, False, False) is None     # card gone: stock fade
  assert pr.brightness(False, False, True, False) is None     # not park-offroad: stock
  pr.update(True, True, False)
  assert pr.brightness(True, False, False, False) is None     # no camera reading yet
  assert pr.brightness(True, False, False, True) == JUMP      # first camera reading
  assert pr.brightness(True, False, False, True) is None      # once
  pr2 = ParkReturn()
  pr2.update(True, True, False)
  assert pr2.brightness(True, False, False, True) is None     # stock onroad: the 10 s filter


def _device_sim(seconds_onroad, park_offroad: bool, card_s=10.0):
  """Mirrors Device._update_brightness: offroad 65, onroad camera target 99, 10 s filter, 60 fps.
  Drive, Park -> offroad with the card up card_s, sit 30 s, then R/D."""
  pr = ParkReturn()
  f = FirstOrderFilter(65, 10.0, 1 / FPS)
  out = []

  def step(started, park_active, card, cam, target):
    pr.update(started, True, park_active)
    act = pr.brightness(started, park_active, card, cam)
    if act == HOLD:
      b = round(f.x)
    elif act == JUMP:
      f.x = target
      b = round(target)
    else:
      b = round(f.update(target))
    out.append(b)
  for _ in range(60 * FPS):
    step(True, False, False, True, 99)
  card_end = len(out) + int(card_s * FPS)
  for _ in range(30 * FPS):
    step(False, park_offroad, len(out) < card_end, False, 65)
  back = len(out)
  for i in range(int(seconds_onroad * FPS)):
    step(True, False, False, i >= int(0.8 * FPS), 99)       # first camera frame ~0.8 s after start
  return out, back, card_end


def test_brightness_sim_park_offroad():
  out, back, card_end = _device_sim(5, park_offroad=True)
  assert min(out[60 * FPS:card_end]) >= 98                   # card readable: no fade toward 65
  assert out[back - 1] < 80                                  # afterwards the normal offroad fade
  assert out[back + int(0.8 * FPS)] == 99                    # first camera reading: straight to target


def test_brightness_sim_toggle_off_is_stock():
  out, back, card_end = _device_sim(5, park_offroad=False)
  assert out[card_end - 1] < 80                              # stock fade under the card
  assert out[back + int(0.8 * FPS)] < 90                     # stock 10 s ramp


# -- hooks -------------------------------------------------------------------------------------

def test_hooks_in_ui_state_and_main():
  ui = (UI / "ui_state.py").read_text()
  assert "self._park_return.update(self.started, self.ignition, self.park_offroad_active)" in ui
  assert "self.park_offroad_active = not park_offroad.not_parked(self.params)" in ui
  bright = ui.split("def _update_brightness(self)")[1].split("\n  def ")[0]
  assert "ui_state._park_return.brightness(" in bright and "drive_summary.card_on_screen" in bright
  assert "self._brightness_filter = FirstOrderFilter(BACKLIGHT_OFFROAD, 10.00" in ui          # stock filter kept
  main = (UI / "mici/layouts/main.py").read_text()
  assert "DriveSummaryCard(stats_fn=stats_view, early_fn=early_event)" in main
  trans = main.split("def _handle_transitions(self)")[1].split("\n  def ")[0]
  onroad = trans.split("if ui_state.started:")[1].split("elif")[0]
  assert "if ui_state.park_return:" in onroad and "self._onroad_time_delay -= ONROAD_DELAY" in onroad
  assert "ONROAD_DELAY = 2.5" in main                                                         # stock value kept
  card = (UI / "mici/widgets/drive_summary_card.py").read_text()
  assert "ds.card_on_screen = self.visible and not ui_state.started" in card
  for word in ("tesla", "jetlink", "park"):
    assert word not in card.split('"""', 2)[2].lower().replace("lib/park_card.py", ""), word   # card stays portable
