"""The models panel's Jetlink widgets, from zoompilot develop 632b0b0
(selfdrive/ui/sunnypilot/mici/layouts/models.py): CurrentModelInfo, the
"active model" / "big model" block at the top of the panel, and the jetlink
link toggle (off / usb / iOS pills), on Highland's widgets. The toggle writes
through jetlink_adapter.set_link_mode, which falls back to the raw params file
for a stale params library and turns ADB off with the link on."""
import pyray as rl

from openpilot.selfdrive import jetlink_adapter
from openpilot.selfdrive.ui.accelerator_link import LINK_MODE_LABELS, link_mode
from openpilot.selfdrive.ui.mici.widgets.button import BigMultiToggle
from openpilot.system.ui.lib.application import FontWeight
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel


class CurrentModelInfo(Widget):
  def __init__(self, active_text: str = "", info_header: str = "big model", info_text: str = ""):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 360, 180))
    header_color = rl.Color(255, 255, 255, int(255 * 0.9))
    subheader_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    self.current_model_header = UnifiedLabel("active model", 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.current_model_text = UnifiedLabel(active_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)
    self.info_header = UnifiedLabel(info_header, 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.info_text = UnifiedLabel(info_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)

  def set_info(self, active_text: str, info_header: str, info_text: str) -> None:
    self.current_model_text.set_text(active_text)
    self.info_header.set_text(info_header)
    self.info_text.set_text(info_text)

  def _render(self, _):
    self.current_model_header.set_position(self._rect.x + 20, self._rect.y - 10)
    self.current_model_header.render()
    self.current_model_text.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self.current_model_text.render()
    self.info_header.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self.info_header.render()
    self.info_text.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self.info_text.render()


class JetlinkLinkToggle(BigMultiToggle):
  """zoompilot's link toggle: one pill per mode, a tap moves to the next."""

  def __init__(self):
    super().__init__("jetlink", [LINK_MODE_LABELS[m] for m in jetlink_adapter.MODES], select_callback=self._select,
                     description="Runs big models on a computer or phone plugged into the comma.\n" +
                                 "USB for a Mac, Jetson, Linux PC or Android. iOS for an iPhone or iPad.\n" +
                                 "Turns off ADB. The small model drives until the big model is ready.")
    self.refresh()

  def refresh(self) -> None:
    try:
      value = LINK_MODE_LABELS[link_mode()]
    except Exception:
      value = LINK_MODE_LABELS["off"]
    if value != self.value:
      self.set_value(value)

  def _select(self, value: str) -> None:
    try:
      jetlink_adapter.set_link_mode(self._options.index(value))
    except Exception:
      pass
    self.refresh()
