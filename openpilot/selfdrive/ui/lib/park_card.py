"""Park-offroad glue for the trip card (TeslaPilot): show the "trip complete" card the moment
the car is shifted into Park, instead of when park-offroad takes the device offroad 3 s later
(parkd's PARK_HOLD_S).

The card stays portable: it takes an optional early_fn (like stats_fn) that returns SHOW / CUT /
None once per tick. early_event() here is that function.

ParkEarly mirrors parkd's arming so the card only shows when park-offroad will act: R or D seen
during this onroad session, then Park, stopped, not engaged, ParkOffroad and DriveSummary on.
The early card is cut again if the car leaves Park while still onroad (a quick P -> R), or if
Park lasts GIVEUP_S and the device is still onroad (park-offroad unavailable, e.g. gear frames
lost). Going offroad hands it to the normal card flow (the main layout's hold_home), so the card
keeps its 10 s from the moment of Park and then rides the stock scroll to home.
"""
from __future__ import annotations

import time

SHOW, CUT = "show", "cut"
GIVEUP_S = 5.0          # Park held this long and still onroad: park-offroad isn't coming, cut the card
MOVING_V = 0.15         # m/s, same as drive_summary.MOVING_V
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
    if self.armed and not engaged and v_ego <= MOVING_V:
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
      from openpilot.selfdrive.car import park_offroad
      from openpilot.selfdrive.ui.lib import drive_summary
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


# -- back onroad from park-offroad: no ONROAD_DELAY, no slow brightness ramp --------------------
HOLD, JUMP = "hold", "jump"


class ParkReturn:
  """Pure. ui_state feeds it every frame.

  returned: this onroad session began from park-offroad (R/D in Park, a new route). Latched from
  ParkOffroadActive while offroad, so it survives parkd clearing the param a moment before
  hardwared starts onroad; a real ignition off (latch cleared, param False) drops it.

  brightness(): the Device's park-offroad hold and jump.
    HOLD (offroad, parked offroad, trip card on screen): keep the last onroad brightness, don't
      fade toward the offroad level, so the card is readable. Afterwards: stock fade.
    JUMP (once, onroad after a park return, first camera reading): set the filter straight to the
      camera-based target instead of the 10 s ramp.
    None: stock. With ParkOffroad off, ParkOffroadActive is never set, so always None."""

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
