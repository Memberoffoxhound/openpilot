"""Slide-in / slide-out motion for the trip-complete card, same feel as the onroad alerts.

The alerts (mici/onroad/alert_renderer.py) move their band with
BounceFilter(0, 0.1, 1 / gui_app.target_fps), targeting rect.y while shown and
rect.y - 50 when gone. The card is an opaque full-screen band, so it uses the
same filter over its own height: it enters from fully above the screen, drops
to rect.y with the alerts' bounce, and leaves the same way back up, revealing
the home screen underneath. Exit is done (nothing drawn) the first frame the
card is fully above the screen, so no sliver is ever left over the home screen.

Pure: no raylib, steppable in tests. step() returns the card's y offset from
rect.y for this frame, or None when nothing should be drawn.
"""
from __future__ import annotations

from openpilot.common.filter_simple import BounceFilter

RC = 0.1             # same as the alert band's BounceFilter
EXIT_PAST = 0.15     # exit target is this fraction of the height beyond fully-off, so it gets there quickly

HIDDEN, SHOWN, EXITING = "hidden", "shown", "exiting"


class CardSlide:
  def __init__(self, height: float, dt: float):
    self.height = float(height)
    self.dt = dt
    self.state = HIDDEN
    self._f = BounceFilter(-self.height, RC, dt)

  @property
  def drawn(self) -> bool:
    return self.state != HIDDEN

  @property
  def offset(self) -> float:
    return self._f.x

  def show(self) -> None:
    """Start entering from fully above the screen."""
    self._f = BounceFilter(-self.height, RC, self.dt)
    self.state = SHOWN

  def hide(self) -> None:
    """Start sliding back up (timeout, tap). No-op unless shown."""
    if self.state == SHOWN:
      self.state = EXITING

  def cut(self) -> None:
    """Gone this frame (onroad resumed)."""
    self.state = HIDDEN

  def step(self) -> float | None:
    if self.state == HIDDEN:
      return None
    if self.state == SHOWN:
      return self._f.update(0.0)
    y = self._f.update(-self.height * (1.0 + EXIT_PAST))
    if y <= -self.height:
      self.state = HIDDEN
      return None
    return y
