"""Motion for the trip-complete card: slide in from the top, leave with the stock scroll to home.

Entry: the card is an opaque full-screen band. It enters from fully above
the screen and eases out to rect.y over ENTER_S (cubic ease-out: fast start,
gentle stop, never past rect.y).

Exit: there is no animation of its own. On dismiss (SHOW_S or a tap), the
card attaches to the onroad page's position in the main layout's scroller.
The main layout then runs its stock scroll to home, and the card travels
sideways with that page: same direction, easing and timing as home sliding
in today. It stops drawing once the page is fully out of view, so the home
screen is left clean. If the page doesn't move off within LEAVE_MAX_S (no
scroll happened), it stops drawing anyway.

Pure: no raylib, steppable in tests. Time advances dt per drawn frame
(1 / target_fps), like the UI's filters. step(page_dx) returns the card's
(x, y) offset from rect for this frame, or None when nothing should be drawn.
page_dx is attached_dx(): where the onroad page is now, relative to the
viewport.
"""
from __future__ import annotations

ENTER_S = 0.28       # slide in from the top
LEAVE_MAX_S = 2.0    # failsafe: stop drawing if the page never scrolls away

HIDDEN, SHOWN, LEAVING = "hidden", "shown", "leaving"


def ease_out(p: float) -> float:
  p = min(1.0, max(0.0, p))
  return 1.0 - (1.0 - p) ** 3


def attached_dx(page_x: float, viewport_x: float) -> float:
  """The card's x offset while leaving: wherever the scroller has the onroad page right now."""
  return float(page_x) - float(viewport_x)


class CardSlide:
  def __init__(self, height: float, dt: float, width: float = 0.0):
    self.height = float(height)
    self.width = float(width)
    self.dt = dt
    self.state = HIDDEN
    self._t = 0.0
    self._leave_t = 0.0
    self._y = -self.height
    self._x = 0.0

  @property
  def drawn(self) -> bool:
    return self.state != HIDDEN

  @property
  def offset(self) -> float:
    return self._y

  @property
  def x_offset(self) -> float:
    return self._x

  def show(self) -> None:
    """Start entering from fully above the screen."""
    self.state, self._t, self._y, self._x = SHOWN, 0.0, -self.height, 0.0

  def hide(self) -> None:
    """Dismissed (timeout, tap): from now on the card rides the onroad page. No-op unless shown."""
    if self.state == SHOWN:
      self.state, self._leave_t = LEAVING, 0.0

  def cut(self) -> None:
    """Gone this frame (onroad resumed)."""
    self.state = HIDDEN

  def step(self, page_dx: float = 0.0) -> tuple[float, float] | None:
    if self.state == HIDDEN:
      return None
    self._t += self.dt
    self._y = -self.height * (1.0 - ease_out(self._t / ENTER_S))   # a tap mid-entry still finishes the drop
    if self.state == SHOWN:
      self._x = 0.0
      return self._x, self._y
    self._leave_t += self.dt
    self._x = page_dx
    if (self.width > 0 and abs(page_dx) >= self.width - 0.5) or self._leave_t > LEAVE_MAX_S:
      self.state = HIDDEN
      return None
    return self._x, self._y
