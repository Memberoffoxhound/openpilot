import math
import pyray as rl
from openpilot.selfdrive.ui.mici.onroad import SIDE_PANEL_WIDTH
from openpilot.selfdrive.ui.layouts.settings.common import custom_onroad_ui
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.common.filter_simple import FirstOrderFilter

BALL_RADIUS = 24
CARDINALS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
PARKED_MS = 1.0
GPS_ACC_OK_DEG = 90.0
YAW_STD_OK_RAD = math.radians(25.0)


def draw_circle_gradient(center_x: float, center_y: float, radius: int,
                         top: rl.Color, bottom: rl.Color) -> None:
  # Draw a square with the gradient
  rl.draw_rectangle_gradient_v(int(center_x - radius), int(center_y - radius),
                               radius * 2, radius * 2,
                               top, bottom)

  # Paint over square with a ring
  outer_radius = math.ceil(radius * math.sqrt(2)) + 1
  rl.draw_ring(rl.Vector2(int(center_x), int(center_y)), radius, outer_radius,
               0.0, 360.0,
               20, rl.BLACK)


def _angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def _cardinal(bearing_deg: float) -> str:
  return CARDINALS[int((bearing_deg + 22.5) % 360.0) // 45]


def _gps_bearing() -> tuple[float | None, float]:
  sm = ui_state.sm
  try:
    if sm.recv_frame["gpsLocationExternal"] < 1:
      return None, 180.0
    gps = sm["gpsLocationExternal"]
    if hasattr(gps, "hasFix") and not gps.hasFix:
      return None, 180.0
    acc = float(getattr(gps, "bearingAccuracyDeg", 180.0) or 180.0)
    return float(gps.bearingDeg) % 360.0, acc
  except Exception:
    return None, 180.0


def _localizer_yaw() -> tuple[float | None, float, bool]:
  sm = ui_state.sm
  try:
    if sm.recv_frame["deviceMotion"] < 1:
      return None, 180.0, False
    dm = sm["deviceMotion"]
    ori = dm.orientationNED
    if not ori.valid:
      return None, 180.0, False
    yaw_deg = math.degrees(float(ori.z)) % 360.0
    std_deg = math.degrees(float(ori.zStd))
    ok = bool(dm.sensorsOK and dm.inputsOK and std_deg < math.degrees(YAW_STD_OK_RAD))
    return yaw_deg, std_deg, ok
  except Exception:
    return None, 180.0, False


def _parked() -> bool:
  try:
    cs = ui_state.sm["carState"]
    if getattr(cs, "standstill", False):
      return True
    return float(cs.vEgo) < PARKED_MS
  except Exception:
    return True


class ConfidenceBall(Widget):
  def __init__(self, demo: bool = False):
    super().__init__()
    self._demo = demo
    self._confidence_filter = FirstOrderFilter(-0.5, 0.5, 1 / gui_app.target_fps)
    # Same tau as HUD wheel / set-speed fade on engage.
    self._heading_alpha = FirstOrderFilter(0.0, 0.05, 1 / gui_app.target_fps)
    self._font = gui_app.font(FontWeight.DISPLAY)
    self._font_size = 32
    self._letter_h = measure_text_cached(self._font, "N", self._font_size).y
    self._q_size = 24
    self._last_heading_deg: float | None = None

  def update_filter(self, value: float):
    self._confidence_filter.update(value)

  def _update_state(self):
    if self._demo:
      return

    # animate status dot in from bottom
    if ui_state.status == UIStatus.DISENGAGED:
      self._confidence_filter.update(-0.5)
    else:
      self._confidence_filter.update((1 - max(ui_state.sm['modelV2'].meta.disengagePredictions.brakeDisengageProbs or [1])) *
                                                        (1 - max(ui_state.sm['modelV2'].meta.disengagePredictions.steerOverrideProbs or [1])))
    want = 1.0 if custom_onroad_ui() and ui_state.status == UIStatus.ENGAGED else 0.0
    self._heading_alpha.update(want)

  def _heading_state(self) -> tuple[str | None, bool, bool]:
    """GPS when it has a fix; IMU if GPS is junk. Last heading when parked. ? only if none."""
    parked = _parked()
    gps_brg, gps_acc = _gps_bearing()
    yaw, yaw_std, yaw_ok = _localizer_yaw()
    heading = None
    confident = False
    if gps_brg is not None and gps_acc < GPS_ACC_OK_DEG:
      heading = gps_brg
      confident = gps_acc < 45.0
      if yaw_ok and yaw is not None and gps_acc > 35.0 and _angle_diff_deg(gps_brg, yaw) > 50.0:
        heading = yaw
        confident = yaw_std < 15.0
    elif yaw_ok and yaw is not None:
      heading = yaw
      confident = yaw_std < 15.0
    if heading is not None and not parked:
      self._last_heading_deg = heading
      return _cardinal(heading), confident, False
    if self._last_heading_deg is not None:
      return _cardinal(self._last_heading_deg), False, False
    if heading is not None:
      return _cardinal(heading), False, False
    return None, False, True

  def _draw_placeholder(self, cx: float, cy: float, a: float = 1.0) -> None:
    r = BALL_RADIUS * 0.78
    col = rl.Color(255, 255, 255, int(170 * a))
    rl.draw_circle_lines(int(cx), int(cy), r, col)
    rl.draw_line_ex(rl.Vector2(cx, cy - r), rl.Vector2(cx, cy - r + 7), 2.5, col)
    q = "?"
    sz = measure_text_cached(self._font, q, self._q_size)
    rl.draw_text_ex(
      self._font, q,
      rl.Vector2(cx - sz.x / 2, cy - sz.y / 2),
      self._q_size, 0, col,
    )

  def _render(self, _):
    content_rect = rl.Rectangle(
      self.rect.x + self.rect.width - SIDE_PANEL_WIDTH,
      self.rect.y,
      SIDE_PANEL_WIDTH,
      self.rect.height,
    )

    status_dot_radius = BALL_RADIUS
    ball_cx = content_rect.x + content_rect.width - status_dot_radius
    top_pad = 0.0
    a = self._heading_alpha.x
    if custom_onroad_ui() and a > 0.01:
      top_pad = (4.0 + self._letter_h + 6.0) * a
      letter, confident, placeholder = self._heading_state()
      if placeholder:
        self._draw_placeholder(ball_cx, content_rect.y + 2 + self._letter_h / 2, a)
      elif letter:
        sz = measure_text_cached(self._font, letter, self._font_size)
        alpha = int((230 if confident else 160) * a)
        rl.draw_text_ex(
          self._font,
          letter,
          rl.Vector2(ball_cx - sz.x / 2, content_rect.y + 2),
          self._font_size,
          0,
          rl.Color(255, 255, 255, alpha),
        )

    usable = max(1.0, content_rect.height - 2 * status_dot_radius - top_pad)
    dot_height = top_pad + (1 - self._confidence_filter.x) * usable + status_dot_radius
    dot_height = self._rect.y + dot_height

    # confidence zones
    if ui_state.status == UIStatus.ENGAGED or self._demo:
      if self._confidence_filter.x > 0.5:
        top_dot_color = rl.Color(0, 255, 204, 255)
        bottom_dot_color = rl.Color(0, 255, 38, 255)
      elif self._confidence_filter.x > 0.2:
        top_dot_color = rl.Color(255, 200, 0, 255)
        bottom_dot_color = rl.Color(255, 115, 0, 255)
      else:
        top_dot_color = rl.Color(255, 0, 21, 255)
        bottom_dot_color = rl.Color(255, 0, 89, 255)

    elif ui_state.status == UIStatus.OVERRIDE:
      top_dot_color = rl.Color(255, 255, 255, 255)
      bottom_dot_color = rl.Color(82, 82, 82, 255)

    else:
      top_dot_color = rl.Color(50, 50, 50, 255)
      bottom_dot_color = rl.Color(13, 13, 13, 255)

    draw_circle_gradient(ball_cx, dot_height, status_dot_radius,
                         top_dot_color, bottom_dot_color)
