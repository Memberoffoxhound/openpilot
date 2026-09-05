from __future__ import annotations

from collections.abc import Callable

from openpilot.common.params import Params
from openpilot.selfdrive.ui.layouts.settings.common import theme_color
from openpilot.selfdrive.ui.mici.widgets.button import BigToggle, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton
from openpilot.selfdrive.vslam.store import (
  is_enabled, set_enabled, is_filter_enabled, set_filter_enabled, op_long_active,
  load_events, load_trace,
)
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller
import pyray as rl

WHITE = rl.Color(255, 255, 255, int(255 * 0.92))
LABEL = rl.Color(142, 142, 147, 255)
DIM = rl.Color(100, 100, 100, 255)
TRACK = rl.Color(42, 42, 48, 255)
YELLOW = rl.Color(255, 204, 0, 255)
RED = rl.Color(255, 59, 48, 255)
GREEN = rl.Color(80, 230, 150, 255)
PLAN = rl.Color(180, 180, 200, 200)


def _lerp_c(a: rl.Color, b: rl.Color, t: float) -> rl.Color:
  t = max(0.0, min(1.0, t))
  return rl.Color(
    int(a.r + (b.r - a.r) * t),
    int(a.g + (b.g - a.g) * t),
    int(a.b + (b.b - a.b) * t),
    255,
  )


def _wire_vslam_confirm(page: NavScroller, title: str, bodies: list[str],
                       on_confirm: Callable[[], None]) -> None:
  warn = gui_app.texture("icons_mici/setup/warning.png", 64, 64)
  check = gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64)
  accept = BigConfirmationCircleButton("slide to\nenable", check,
                                       lambda: page.dismiss(on_confirm))
  page._scroller.add_widgets([
    GreyBigButton(title, "scroll to continue", warn),
    *[GreyBigButton("", body) for body in bodies],
    accept,
  ])


class VSlamLoggerConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    _wire_vslam_confirm(self, "enabling\nvSlam logger", [
      "Records Tesla cruise dumps of 6+ mph for review.",
      "Doesn't touch gas or brake — observe only.",
      "View events in S3XYPilot WebUI:",
      "http://<comma-ip>:8088",
    ], on_confirm)


class VSlamFilterConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    _wire_vslam_confirm(self, "enabling\nvSlam filter", [
      "On openpilot long, stops Tesla phantom brakes from",
      "yanking set speed down on straight roads.",
      "Off/Locked whenever stock Tesla TACC is the",
      "longitudinal policy.",
      "Allows Tesla curvature assisted slowdowns",
      "in curves such as exit off-ramps.",
    ], on_confirm)


class _Page(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 536, 240))

  def _update_state(self):
    self.set_rect(rl.Rectangle(self.rect.x, self.rect.y, 536, 240))


class VSlamListWidget(_Page):
  def __init__(self):
    super().__init__()
    self._events: list[dict] = []

  def show_event(self):
    super().show_event()
    self._events = list(reversed(load_events(8)))

  def _render(self, _):
    r = self.rect
    font_b = gui_app.font(FontWeight.BOLD)
    font = gui_app.font(FontWeight.MEDIUM)
    rl.draw_text_ex(font_b, "vSlam", rl.Vector2(r.x + 12, r.y + 6), 32, 0, WHITE)
    n = len(self._events)
    rl.draw_text_ex(font, f"{n} logged", rl.Vector2(r.x + 430, r.y + 14), 22, 0, LABEL)
    if not self._events:
      rl.draw_text_ex(font, "No slams >= 6 mph yet", rl.Vector2(r.x + 12, r.y + 110), 26, 0, DIM)
      return
    y = r.y + 44
    for ev in self._events[:4]:
      pre = ev.get("pre_mph") or 0
      slam = ev.get("slam_mph") or 0
      dur = ev.get("duration_s") or 0
      when = (ev.get("local_time") or "")[-11:]
      place = ev.get("place") or ev.get("road") or ev.get("city") or "—"
      line1 = f"{pre:.0f}->{slam:.0f}  {dur:.1f}s  {when}"
      rl.draw_text_ex(font_b, line1, rl.Vector2(r.x + 12, y), 22, 0, WHITE)
      rl.draw_text_ex(font, place[:42], rl.Vector2(r.x + 12, y + 22), 18, 0, LABEL)
      y += 48


class VSlamTraceWidget(_Page):
  def __init__(self):
    super().__init__()
    self._ev: dict = {}
    self._samples: list[dict] = []

  def show_event(self):
    super().show_event()
    events = load_events(1)
    self._ev = events[-1] if events else {}
    self._samples = (load_trace(self._ev["id"]).get("samples") or []) if self._ev else []

  def _render(self, _):
    r = self.rect
    font_b = gui_app.font(FontWeight.BOLD)
    font = gui_app.font(FontWeight.MEDIUM)
    ev = self._ev
    if not ev:
      rl.draw_text_ex(font, "No event", rl.Vector2(r.x + 12, r.y + 100), 26, 0, DIM)
      return
    pre, slam = ev.get("pre_mph") or 0, ev.get("slam_mph") or 0
    rec = ev.get("recover_mph")
    rec_s = f"{rec:.0f}" if rec is not None else "—"
    title = f"{pre:.0f} → {slam:.0f}  rec {rec_s}"
    rl.draw_text_ex(font_b, title, rl.Vector2(r.x + 12, r.y + 4), 26, 0, WHITE)
    place = ev.get("place") or ev.get("city") or ""
    rl.draw_text_ex(font, place[:36], rl.Vector2(r.x + 280, r.y + 8), 18, 0, LABEL)

    chart = rl.Rectangle(r.x + 12, r.y + 36, r.width - 24, r.height - 48)
    rl.draw_rectangle_rec(chart, TRACK)
    if len(self._samples) < 2:
      return
    vs = [float(s.get("v_cruise_mph") or 0) for s in self._samples]
    plans = [float(s.get("v_plan_mph") or s.get("v_ego_mph") or 0) for s in self._samples]
    lo = min(min(vs), min(plans)) - 2
    hi = max(max(vs), max(plans), pre) + 2
    span = max(1.0, hi - lo)
    t0, t1 = self._samples[0]["t"], self._samples[-1]["t"]
    dt = max(0.001, t1 - t0)
    slam_t0, slam_t1 = ev.get("t0") or 0, ev.get("t_end") or 0

    def xy(i: int, val: float) -> rl.Vector2:
      x = chart.x + chart.width * (self._samples[i]["t"] - t0) / dt
      y = chart.y + chart.height * (1.0 - (val - lo) / span)
      return rl.Vector2(x, y)

    for i in range(1, len(self._samples)):
      rl.draw_line_ex(xy(i - 1, plans[i - 1]), xy(i, plans[i]), 2.0, PLAN)

    for i in range(1, len(self._samples)):
      t = self._samples[i]["t"]
      in_slam = slam_t0 <= t <= slam_t1 or bool(self._samples[i].get("in_slam"))
      if not in_slam:
        col = GREEN
      else:
        den = max(0.1, pre - slam)
        frac = (vs[i] - slam) / den
        col = _lerp_c(RED, YELLOW, frac)
      rl.draw_line_ex(xy(i - 1, vs[i - 1]), xy(i, vs[i]), 3.0, col)

    rl.draw_text_ex(font, "vCruise", rl.Vector2(r.x + 16, r.y + r.height - 16), 14, 0, theme_color())
    rl.draw_text_ex(font, "planner", rl.Vector2(r.x + 90, r.y + r.height - 16), 14, 0, PLAN)


class VSlamLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._scroller._snap_items = True
    self._scroller._spacing = 0
    self._scroller._pad = 0
    self._params = Params()
    self._logger = BigToggle("vSlam logger", initial_state=is_enabled(self._params),
                             toggle_callback=self._on_logger)
    self._filter = BigToggle("vSlam filter", initial_state=is_filter_enabled(self._params),
                             toggle_callback=self._on_filter)
    self._list = VSlamListWidget()
    self._trace = VSlamTraceWidget()
    self._items = (self._logger, self._filter, self._list, self._trace)
    self._scroller.add_widgets(list(self._items))

  def show_event(self):
    super().show_event()
    self._refresh_toggles()
    for w in self._items:
      w.show_event()

  def _refresh_toggles(self):
    self._logger.set_checked(is_enabled(self._params))
    op_long = op_long_active(self._params)
    self._filter.set_enabled(op_long)
    self._filter.set_checked(is_filter_enabled(self._params) if op_long else False)

  def _on_logger(self, state: bool):
    if state:
      self._logger.set_checked(False)

      def on_confirm():
        set_enabled(True, self._params)
        self._logger.set_checked(True)

      gui_app.push_widget(VSlamLoggerConfirmPage(on_confirm))
    else:
      set_enabled(False, self._params)

  def _on_filter(self, state: bool):
    if not op_long_active(self._params):
      self._filter.set_checked(False)
      set_filter_enabled(False, self._params)
      return
    if state:
      self._filter.set_checked(False)

      def on_confirm():
        armed = set_filter_enabled(True, self._params)
        self._filter.set_checked(armed)

      gui_app.push_widget(VSlamFilterConfirmPage(on_confirm))
    else:
      set_filter_enabled(False, self._params)
