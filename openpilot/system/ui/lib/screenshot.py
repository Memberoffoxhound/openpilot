"""3s display hold → PNG in /data/media/0/screenshots."""
import os
import time

import pyray as rl

SHOT_DIR = "/data/media/0/screenshots"
SHOT_PLAY = "/data/screenshot_play"
HOLD_S = 3.0
MOVE_PX = 28


class ScreenShotter:
  def __init__(self):
    self._t: float | None = None
    self._pos: tuple[float, float] | None = None
    self._fired = False
    self.pending = False
    self.flash = 0.0

  def held(self, events) -> bool:
    for e in events:
      if e.left_pressed:
        self._t = time.monotonic()
        self._pos = (e.pos.x, e.pos.y)
        self._fired = False
      if e.left_down and self._pos is not None:
        if abs(e.pos.x - self._pos[0]) > MOVE_PX or abs(e.pos.y - self._pos[1]) > MOVE_PX:
          self._t = None
      if e.left_released:
        self._t = None
    # Clock, not lift. Still finger + no events still fires at 3s.
    if self._t is not None and not self._fired and (time.monotonic() - self._t) >= HOLD_S:
      self._fired = True
      self._t = None
      self.pending = True
      try:
        open(SHOT_PLAY, "w").write("1")
      except OSError:
        pass
      return True
    return False

  def capture(self, render_texture=None) -> str | None:
    try:
      os.makedirs(SHOT_DIR, exist_ok=True)
      if render_texture is not None and getattr(render_texture, "texture", None):
        img = rl.load_image_from_texture(render_texture.texture)
        rl.image_flip_vertical(img)
      else:
        img = rl.load_image_from_screen()
      name = time.strftime("%Y-%m-%d--%H-%M-%S.png")
      path = os.path.join(SHOT_DIR, name)
      rl.export_image(img, path)
      rl.unload_image(img)
      self.flash = 1.0
      self.pending = False
      return path
    except Exception:
      self.pending = False
      return None

  def draw_flash(self, width: int, height: int, dt: float) -> None:
    if self.flash <= 0:
      return
    a = int(255 * self.flash)
    rl.draw_rectangle(0, 0, width, height, rl.Color(255, 255, 255, a))
    self.flash = max(0.0, self.flash - dt / 0.22)
