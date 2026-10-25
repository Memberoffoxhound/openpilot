"""Slide-in / slide-out motion for the trip-complete card: smooth, no bounce.

The card is an opaque full-screen band. It enters from fully above the screen
and eases out to rect.y over ENTER_S (cubic ease-out: fast start, gentle
stop, never past rect.y). After SHOW_S or a tap, it eases back up over EXIT_S
(quadratic ease-in) to reveal the home screen underneath. Drawing stops on
the first frame the card is fully above the screen, so no sliver is ever left
over the home screen. A tap while still entering reverses from the current
position without a jump.

Pure: no raylib, steppable in tests. Time advances dt per drawn frame
(1 / target_fps), like the UI's filters. step() returns the card's y offset
from rect.y for this frame, or None when nothing should be drawn.
"""
from __future__ import annotations

ENTER_S = 0.28       # slide in from the top
EXIT_S = 0.22        # slide back up to the home screen

HIDDEN, SHOWN, EXITING = "hidden", "shown", "exiting"


def ease_out(p: float) -> float:
  p = min(1.0, max(0.0, p))
  return 1.0 - (1.0 - p) ** 3


def ease_in(p: float) -> float:
  p = min(1.0, max(0.0, p))
  return p * p


class CardSlide:
  def __init__(self, height: float, dt: float):
    self.height = float(height)
    self.dt = dt
    self.state = HIDDEN
    self._t = 0.0
    self._y = -self.height

  @property
  def drawn(self) -> bool:
    return self.state != HIDDEN

  @property
  def offset(self) -> float:
    return self._y

  def show(self) -> None:
    """Start entering from fully above the screen."""
    self.state, self._t, self._y = SHOWN, 0.0, -self.height

  def hide(self) -> None:
    """Start sliding back up (timeout, tap). No-op unless shown."""
    if self.state == SHOWN:
      # continue from where the card is: ease_in(p0) * height == -y
      frac = min(1.0, max(0.0, -self._y / self.height)) if self.height > 0 else 1.0
      self.state, self._t = EXITING, EXIT_S * frac ** 0.5

  def cut(self) -> None:
    """Gone this frame (onroad resumed)."""
    self.state = HIDDEN

  def step(self) -> float | None:
    if self.state == HIDDEN:
      return None
    self._t += self.dt
    if self.state == SHOWN:
      self._y = -self.height * (1.0 - ease_out(self._t / ENTER_S))
      return self._y
    self._y = -self.height * ease_in(self._t / EXIT_S)
    if self._y <= -self.height:
      self.state = HIDDEN
      return None
    return self._y
