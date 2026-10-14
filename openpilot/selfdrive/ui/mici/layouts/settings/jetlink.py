"""Settings -> jetlink: the phone link's status, the mode and charging.
Every value comes from selfdrive/ui/jetlink_status.py, which never raises."""
from openpilot.selfdrive import jetlink_adapter
from openpilot.selfdrive.ui.jetlink_status import MODE_TITLES, jetlink_ui
from openpilot.selfdrive.ui.mici.layouts.settings.toggles import JetlinkCycle
from openpilot.selfdrive.ui.mici.widgets.button import BigToggle, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets.scroller import NavScroller


def model_big() -> bool:
  try:
    return bool(ui_state.started and ui_state.sm.alive['modelV2'] and ui_state.sm['modelV2'].big)
  except Exception:
    return False


class JetlinkLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._mode_btn = JetlinkCycle()
    self._mode_btn.set_enabled(lambda: not ui_state.started)
    self._state = GreyBigButton("link", "off")
    self._mode = GreyBigButton("mode", "off")
    self._phone = GreyBigButton("phone", "-")
    self._model = GreyBigButton("model", "-")
    self._progress = GreyBigButton("progress", "-")
    self._timing = GreyBigButton("frame time", "-")
    self._charge = BigToggle("charge phone", initial_state=jetlink_adapter.charge_phone(), toggle_callback=self._on_charge)
    self._charge.set_enabled(lambda: not ui_state.started)
    note = GreyBigButton("", "Charging from the comma made the iPhone link unstable (Jetlink v0.8.4).\n" +
                             "Leave this off; use a powered USB 3 hub to charge the phone.")
    self._scroller.add_widgets([self._mode_btn, self._state, self._mode, self._phone, self._model,
                                self._progress, self._timing, self._charge, note])

  @staticmethod
  def _set(btn, value):
    value = value or "-"
    if btn.get_value() != value:
      btn.set_value(value)

  def show_event(self):
    super().show_event()
    jetlink_ui._at = 0.0
    self._mode_btn.refresh()
    self._charge.set_checked(jetlink_adapter.charge_phone())

  def _update_state(self):
    super()._update_state()
    try:
      s = jetlink_ui.refresh(ui_state.started, model_big())
      self._mode_btn.refresh()
      self._set(self._state, s.reason if s.state == 'unavailable' and s.reason else s.state)
      self._set(self._mode, MODE_TITLES.get(s.mode, s.mode))
      self._set(self._phone, s.transport)
      self._set(self._model, s.model)
      self._set(self._progress, f"{s.progress[0]} {s.progress[1] * 100:.0f}% {s.progress[2]}".strip() if s.progress else None)
      self._set(self._timing, s.timing)
    except Exception:
      pass

  def _on_charge(self, state: bool):
    try:
      jetlink_adapter.set_charge_phone(state)
    except Exception:
      pass
