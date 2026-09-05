from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.vslam.store import (
  is_enabled, set_enabled, is_filter_enabled, set_filter_enabled, op_long_active,
)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import toggle_item
from openpilot.system.ui.widgets.scroller import Scroller

LOGGER_DESC = tr_noop(
  "Observe-only. When Tesla drops cruise set speed by ≥6 mph, the logger records the slam "
  "(pre/slam mph, path class, recover timing) for the C4 list, 60s trace, and LAN deviceweb. "
  "It never changes gas, brake, or openpilot's longitudinal target. Leave it on for a paper "
  "trail of phantom brakes; turn it off to stop writing /data/vslam events."
)

FILTER_DESC = tr_noop(
  "Active counter for stock Tesla phantom braking when openpilot long owns the policy. "
  "On a straight-road slam (≥6 mph set-speed dump with no curve/ramp/blinker path), Tesla's ACC "
  "can chase the slammed cruise target and yank the car down even though openpilot's planner "
  "didn't ask for it. After a short window, if set speed starts rising again the filter treats "
  "it as a glitch and ignores the dump; if it stays slammed, openpilot honors the new set speed. "
  "Locked off while TACC is the long policy. Does not invent slowdowns in corners or on ramps."
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
    self._filter = toggle_item(
      lambda: tr("vSlam Filter"),
      description=lambda: tr(FILTER_DESC),
      initial_state=is_filter_enabled(self._params),
      callback=self._on_filter,
    )
    self._scroller = Scroller([self._logger, self._filter], line_separator=True, spacing=0)

  def show_event(self):
    super().show_event()
    self._refresh()

  def _refresh(self):
    self._logger.action_item.set_state(is_enabled(self._params))
    op_long = op_long_active(self._params)
    self._filter.action_item.set_enabled(op_long)
    self._filter.action_item.set_state(is_filter_enabled(self._params) if op_long else False)

  def _on_logger(self, state: bool):
    set_enabled(bool(state), self._params)
    self._logger.action_item.set_state(is_enabled(self._params))

  def _on_filter(self, state: bool):
    set_filter_enabled(bool(state), self._params)
    self._refresh()

  def _render(self, rect):
    self._scroller.render(rect)
