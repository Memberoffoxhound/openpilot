"""Trip card motion. Pure (no raylib), steppable in tests: dt per drawn frame, like the UI's filters.

Entry: from fully above the screen, cubic ease-out to rect.y over ENTER_S, never past it.
Exit: none of its own. Once hidden the card rides the onroad page (page_dx = attached_dx())
through the stock scroll to home, and stops drawing when the page is out of view or after LEAVE_MAX_S.
"""
from __future__ import annotations

ENTER_S = 0.28
LEAVE_MAX_S = 2.0    # failsafe: stop drawing if the page never scrolls away

HIDDEN, SHOWN, LEAVING = "hidden", "shown", "leaving"


def ease_out(p: float) -> float:
  p = min(1.0, max(0.0, p))
  return 1.0 - (1.0 - p) ** 3


def attached_dx(page_x: float, viewport_x: float) -> float:
  return float(page_x) - float(viewport_x)


class CardSlide:
  def __init__(self, height: float, dt: float, width: float = 0.0):
    self.height = float(height)
    self.width = float(width)
    self.dt = dt
    self.state = HIDDEN
    self._t = 0.0
    self._leave_t = 0.0

  @property
  def drawn(self) -> bool:
    return self.state != HIDDEN

  def show(self) -> None:
    self.state, self._t = SHOWN, 0.0

  def hide(self) -> None:
    if self.state == SHOWN:
      self.state, self._leave_t = LEAVING, 0.0

  def cut(self) -> None:
    self.state = HIDDEN

  def step(self, page_dx: float = 0.0) -> tuple[float, float] | None:
    """The card's (x, y) offset from rect this frame, or None when nothing is drawn."""
    if self.state == HIDDEN:
      return None
    self._t += self.dt
    y = -self.height * (1.0 - ease_out(self._t / ENTER_S))   # a tap mid-entry still finishes the drop
    if self.state == SHOWN:
      return 0.0, y
    self._leave_t += self.dt
    if (self.width > 0 and abs(page_dx) >= self.width - 0.5) or self._leave_t > LEAVE_MAX_S:
      self.state = HIDDEN
      return None
    return page_dx, y
