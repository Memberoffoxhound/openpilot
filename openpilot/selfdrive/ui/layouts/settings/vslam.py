from openpilot.common.params import Params
from openpilot.selfdrive.vslam.store import is_enabled, set_enabled
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import toggle_item
from openpilot.system.ui.widgets.scroller import Scroller

LOGGER_DESC = tr_noop(
  "Records 6+ mph cruise dumps for review (observe-only). "
  "WebUI: http://<comma-ip>:8088"
)

# Kept for shared copy / future planner wiring. Filter UI is hidden until a consumer exists.
FILTER_DESC = tr_noop(
  "Observe-only for now: would block phantom brakes on OP long when a planner reader exists. "
  "Locked off on TACC."
)

FILTER_FAQ = (
  "Observe-only until a planner consumer exists.",
  "Would apply on openpilot long only; locked on TACC.",
)

LOGGER_FAQ = (
  "Records Tesla cruise dumps of 6+ mph for review.",
  "Doesn't touch gas or brake — observe only.",
  "View events in S3XYPilot WebUI:",
  "http://<comma-ip>:8088",
)


class VSlamLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._logger = toggle_item(
      lambda: tr("vSlam Logger"),
      description=lambda: tr(LOGGER_DESC),
      initial_state=is_enabled(self._params),
      callback=self._on_logger,
    )
    # Filter toggle hidden: no planner reader yet (param helpers remain in store.py).
    self._scroller = Scroller([self._logger], line_separator=True, spacing=0)

  def show_event(self):
    super().show_event()
    self._logger.action_item.set_state(is_enabled(self._params))

  def _on_logger(self, state: bool):
    set_enabled(bool(state), self._params)
    self._logger.action_item.set_state(is_enabled(self._params))

  def _render(self, rect):
    self._scroller.render(rect)
