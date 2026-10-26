"""The UI's view of parkd's ParkOffroadState (park_offroad.py). Pure; ui_state feeds it every frame.

parked: parkd is PARKING or PARKED, or let go (R/D) less than RETURN_S ago and onroad hasn't
started yet, so the onroad page never shows "can't start" on the way back.
returned: this onroad session came back from PARKED.
"""
from __future__ import annotations

from openpilot.selfdrive.car.park_offroad import NONE, PARKED
from openpilot.selfdrive.ui.lib.drive_summary import SHOW_S

RETURN_S = 2.0
HOLD, JUMP = "hold", "jump"


class ParkView:
  def __init__(self) -> None:
    self.parked = self.returned = False
    self._offroad = self._started = self._jumped = False
    self._since = self._let_go = 0.0

  def update(self, now: float, started: bool, ignition: bool, state: int) -> None:
    if ignition and state != NONE:
      if not self.parked:
        self._since = now
      self.parked, self._let_go = True, now
      self._offroad |= state == PARKED
    elif started or not ignition or now - self._let_go > RETURN_S:
      self.parked = False
    if started != self._started:
      self._started = started
      self.returned, self._jumped = started and self._offroad, False
    if started or not ignition:
      self._offroad = False

  def brightness(self, now: float, started: bool, have_camera: bool) -> str | None:
    """HOLD the onroad level for the first SHOW_S parked offroad, JUMP once to the camera on the way back."""
    if not started:
      return HOLD if self.parked and now - self._since < SHOW_S else None
    if self.returned and not self._jumped and have_camera:
      self._jumped = True
      return JUMP
    return None
