"""Settings -> models: the small model, the Jetlink big-model picker, refresh
and reset. A port of sunnypilot's mici models panel onto Highland's widgets
(no icons); the logic is selfdrive/ui/model_picker.py and never raises."""
from openpilot.selfdrive.ui import model_picker as mp
from openpilot.selfdrive.ui.jetlink_status import jetlink_ui
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


def _offroad() -> bool:
  return not ui_state.started


class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._small = GreyBigButton("small model", mp.SMALL_MODEL)
    self._small_note = GreyBigButton("", mp.SMALL_NOTE)
    self._big = BigButton("jetlink big model", mp.big_model_label(),
                          description="Picks the big model Jetlink runs on the phone or computer.\n" +
                                      "The phone downloads and builds it; the small model drives until it is ready.")
    self._big.set_click_callback(self._show_folders)
    self._big.set_enabled(_offroad)
    self._progress = GreyBigButton("progress", "-")
    self._refresh = BigButton("refresh models", mp.list_label(), description="Fetches the latest list of big models.")
    self._refresh.set_click_callback(mp.refresh)
    self._refresh.set_enabled(_offroad)
    self._reset = BigButton("reset to default", "", description="Goes back to Jetlink's default big model.")
    self._reset.set_click_callback(mp.reset_to_default)
    self._reset.set_enabled(lambda: _offroad() and mp.picked() is not None)
    self._scroller.add_widgets([self._big, self._progress, self._refresh, self._reset, self._small, self._small_note])
    self._tick = 0

  @staticmethod
  def _set(btn, value):
    value = value or "-"
    if btn.get_value() != value:
      btn.set_value(value)

  def _push(self, items):
    scroller = NavScroller()
    scroller._scroller.add_widgets(items)
    gui_app.push_widget(scroller)

  def _pop_to_main(self):
    gui_app.pop_widgets_to(self)

  def _show_folders(self):
    try:
      folders = mp.folders()
      default = BigButton(f"{mp.default_name()} ({mp.DEFAULT_LABEL})".lower())
      default.set_click_callback(self._pick_default)
      items = [default]
      if not folders:
        items.append(GreyBigButton("no models yet", "connect to the internet and refresh models"))
      for folder, bundles in folders:
        btn = BigButton(folder.lower(), f"{len(bundles)} models")
        btn.set_click_callback(lambda b=bundles: self._show_models(b))
        items.append(btn)
      self._push(items)
    except Exception:
      pass

  def _show_models(self, bundles):
    try:
      items = []
      for b in bundles:
        btn = BigButton(mp.short_name(b["display_name"]).lower(), mp.model_note(b["ref"]))
        btn.set_click_callback(lambda ref=b["ref"]: self._pick(ref))
        items.append(btn)
      self._push(items)
    except Exception:
      pass

  def _pick(self, ref):
    try:
      mp.select(ref)
    finally:
      self._pop_to_main()

  def _pick_default(self):
    try:
      mp.reset_to_default()
    finally:
      self._pop_to_main()

  def show_event(self):
    super().show_event()
    jetlink_ui._at = 0.0
    self._tick = 0

  def _update_state(self):
    super()._update_state()
    self._tick += 1
    if self._tick % 15 != 1:  # params reads a few times a second, not every frame
      return
    try:
      self._set(self._big, mp.big_model_label() + (" (queued)" if mp.queued() else ""))
      self._set(self._refresh, mp.list_label())
      s = jetlink_ui.refresh(ui_state.started, False)
      p = s.progress
      self._set(self._progress, f"{p[0]} {p[1] * 100:.0f}% {p[2]}".strip() if p else s.state)
    except Exception:
      pass
