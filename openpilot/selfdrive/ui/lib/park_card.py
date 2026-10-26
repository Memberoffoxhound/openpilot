"""Park-offroad glue for the trip card (TeslaPilot).

ParkEarly: the card's early_fn. Puts the card up the moment the car is shifted into Park, not
3 s later when parkd takes the device offroad. It mirrors parkd's arming (R/D seen this session,
then Park, stopped, not engaged, both toggles on) and cuts the card if the car leaves Park
while still onroad, or if Park lasts GIVEUP_S and the device never goes offroad.

ParkReturn: back onroad from park-offroad skips ONROAD_DELAY and the slow brightness ramp.
"""
from __future__ import annotations

import time

from openpilot.selfdrive.car import park_offroad
from openpilot.selfdrive.ui.lib import drive_summary

SHOW, CUT = "show", "cut"
GIVEUP_S = 5.0          # Park held this long and still onroad: park-offroad isn't coming, cut the card
RETURN_GEARS = ("drive", "reverse")


class ParkEarly:
  def __init__(self) -> None:
    self._reset()

  def _reset(self) -> None:
    self.armed = False
    self.fired = False
    self._p_since: float | None = None

  def update(self, on: bool, started: bool, now: float, gear: str, v_ego: float, engaged: bool) -> str | None:
    """One tick. SHOW: put the card up now. CUT: take the early card down (still onroad)."""
    if not started:
      self._reset()               # offroad edge: the card's own offroad hand-off takes over
      return None
    if not on:
      ev = self._cut()            # toggle turned off with the early card up: take it down
      self._reset()
      return ev
    if gear in RETURN_GEARS:
      self.armed = True
      self._p_since = None
      return self._cut()
    if gear != "park":
      self._p_since = None
      return self._cut()
    if self._p_since is None:
      self._p_since = now
    if self.fired:
      if now - self._p_since > GIVEUP_S:
        self.armed = False          # no second try until the car leaves Park in R/D again
        return self._cut()
      return None
    if self.armed and not engaged and v_ego <= drive_summary.MOVING_V:
      self.fired = True
      return SHOW
    return None

  def _cut(self) -> str | None:
    if self.fired:
      self.fired = False
      return CUT
    return None


_early = ParkEarly()
_on_cache = (0.0, False)


def _on(params) -> bool:
  global _on_cache
  now = time.monotonic()
  if now - _on_cache[0] > 1.0:
    try:
      on = park_offroad.enabled(params) and drive_summary.get_bool(params, drive_summary.PARAM_ENABLED, False)
    except Exception:
      on = False
    _on_cache = (now, bool(on))
  return _on_cache[1]


def early_event() -> str | None:
  """The card's early_fn: reads ui_state once per tick."""
  try:
    from openpilot.selfdrive.ui.ui_state import ui_state
    started = bool(ui_state.started)
    gear, v, engaged = "", 0.0, False
    if started:
      sm = ui_state.sm
      cs = sm["carState"]
      if sm.recv_frame["carState"] >= ui_state.started_frame:
        gear, v = str(cs.gearShifter), max(0.0, float(cs.vEgo))
      engaged = bool(ui_state.engaged)
    return _early.update(_on(ui_state.params), started, time.monotonic(), gear, v, engaged)
  except Exception:
    return None


HOLD, JUMP = "hold", "jump"


class ParkReturn:
  """Pure; ui_state feeds it every frame.

  returned: this onroad session began from park-offroad. Latched while offroad, so it survives parkd
  clearing ParkOffroadActive a moment before hardwared starts onroad; a real ignition off drops it.

  brightness(): HOLD the onroad level while the card is up parked offroad, JUMP once to the camera
  target on the way back, else None (stock). ParkOffroadActive is never set with the toggle off."""

  def __init__(self) -> None:
    self.returned = False
    self._from_park = False
    self._started_prev = False
    self._jumped = False

  def update(self, started: bool, ignition: bool, park_active: bool) -> None:
    if not started:
      if park_active:
        self._from_park = True
      elif not ignition:
        self._from_park = False
      self.returned = False
      self._jumped = False
    elif not self._started_prev:
      self.returned = self._from_park
      self._from_park = False
    self._started_prev = started

  def brightness(self, started: bool, park_active: bool, card_on_screen: bool, have_camera: bool) -> str | None:
    if not started:
      return HOLD if park_active and card_on_screen else None
    if self.returned and not self._jumped and have_camera:
      self._jumped = True
      return JUMP
    return None
