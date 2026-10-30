"""Settings -> models: zoompilot develop's mici models panel
(selfdrive/ui/sunnypilot/mici/layouts/models.py) on Highland's widgets. At the
top the active model and what the big model is doing (CurrentModelInfo), then
the big-model picker, the jetlink link toggle, refresh and reset; Highland adds
the phone-charging toggle and the small-model note. The picker's logic is
selfdrive/ui/model_picker.py, the link's selfdrive/ui/accelerator_link.py, both
over ui_state.jetlink (jetlink's Status, with modeld's runtime record); none of
it raises."""
from openpilot.selfdrive import jetlink_adapter
from openpilot.selfdrive.ui import accelerator_link as al
from openpilot.selfdrive.ui import model_picker as mp
from openpilot.selfdrive.ui.mici.layouts.settings.model_widgets import CurrentModelInfo, JetlinkLinkToggle
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigToggle, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


def _offroad() -> bool:
  return not ui_state.started


class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._info = CurrentModelInfo(*self._model_info())
    self._small = GreyBigButton("small model", mp.SMALL_MODEL)
    self._small_note = GreyBigButton("", mp.SMALL_NOTE)
    self._big = BigButton("jetlink big model", mp.big_model_label(),
                          description="Picks the big model Jetlink runs on the phone or computer.\n" +
                                      "The phone downloads and builds it; the small model drives until it is ready.")
    self._big.set_click_callback(self._show_folders)
    self._big.set_enabled(_offroad)
    # the pills follow the param; locked onroad like the model buttons beside it: jetlink switches the link only parked
    self._link = JetlinkLinkToggle()
    self._link.set_enabled(_offroad)
    self._charge = BigToggle("charge phone", initial_state=jetlink_adapter.charge_phone(), toggle_callback=self._on_charge,
                             description="Charging from the comma made the iPhone link unstable (Jetlink v0.8.4).\n" +
                                         "Leave this off; use a powered USB 3 hub to charge the phone.")
    self._charge.set_enabled(_offroad)
    self._refresh = BigButton("refresh models", mp.list_label(), description="Fetches the latest list of big models.")
    self._refresh.set_click_callback(mp.refresh)
    self._refresh.set_enabled(_offroad)
    self._reset = BigButton("reset to default", "", description="Goes back to Jetlink's default big model.")
    self._reset.set_click_callback(mp.reset_to_default)
    self._reset.set_enabled(lambda: _offroad() and mp.picked() is not None)
    self._scroller.add_widgets([self._info, self._big, self._link, self._charge, self._refresh, self._reset, self._small, self._small_note])
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

  @staticmethod
  def _model_info() -> tuple[str, str, str]:
    try:
      return al.model_info(ui_state.jetlink, ui_state.chestnut_state.value, ui_state.chestnut_present,
                           mp.SMALL_MODEL, mp.big_model_label())
    except Exception:
      return mp.SMALL_MODEL, "big model", "-"

  def _on_charge(self, state: bool):
    try:
      jetlink_adapter.set_charge_phone(state)
    except Exception:
      pass

  def show_event(self):
    super().show_event()
    self._tick = 0
    self._link.refresh()
    self._charge.set_checked(jetlink_adapter.charge_phone())

  def _update_state(self):
    super()._update_state()
    self._tick += 1
    if self._tick % 15 != 1:  # params reads a few times a second, not every frame
      return
    try:
      self._set(self._big, mp.big_model_label() + (" (queued)" if mp.queued() else ""))
      self._set(self._refresh, mp.list_label())
      self._info.set_info(*self._model_info())
      self._link.refresh()
      self._link.set_visible(al.link_toggle_meaningful(ui_state.chestnut_present))
      self._charge.set_visible(al.link_mode() != "off")
    except Exception:
      pass
