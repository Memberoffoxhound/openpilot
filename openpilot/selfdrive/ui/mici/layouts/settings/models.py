"""Settings → driving model. First widget on the C4 settings list."""
from __future__ import annotations

import threading

import pyray as rl

from openpilot.selfdrive.modeld.helpers import chestnut_present
from openpilot.selfdrive.modeld.model_manager import (
  MAX_FAVORITES,
  ModelInfo,
  catalog_all,
  favorites,
  find_model,
  get_install_status,
  is_favorite,
  is_installed,
  load_catalog,
  masters,
  refresh_catalog,
  select_model,
  selected_id,
  toggle_favorite,
)
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller


STAR_HIT = 72
LABEL_WHITE = rl.Color(255, 255, 255, int(255 * 0.9))
STAR_GOLD = rl.Color(255, 200, 70, 255)
STAR_DIM = rl.Color(170, 170, 170, 200)
EGPU_BG = rl.Color(40, 90, 55, 255)


class ModelRow(BigButton):
  """Select on the left, star on the right. eGPU badge when needed."""

  def __init__(self, info: ModelInfo):
    super().__init__(info.name, info.subtitle, scroll=True)
    self.info = info
    self._starred = is_favorite(info.id)
    self._selected = selected_id() == info.id
    self._refresh_value()

  def _refresh_value(self):
    bits = [self.info.date]
    if self.info.source == "release":
      bits.append("always available")
    elif is_installed(self.info):
      bits.append("installed")
    else:
      bits.append("not installed")
    if self._selected:
      bits.append("selected")
    self.set_value("  ·  ".join(bits))

  def show_event(self):
    super().show_event()
    self._starred = is_favorite(self.info.id)
    self._selected = selected_id() == self.info.id
    self._refresh_value()

  def _star_rect(self) -> rl.Rectangle:
    return rl.Rectangle(self._rect.x + self._rect.width - STAR_HIT, self._rect.y, STAR_HIT, self._rect.height)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self.info.source != "release" and rl.check_collision_point_rec(mouse_pos, self._star_rect()):
      ok, msg = toggle_favorite(self.info.id)
      self._starred = is_favorite(self.info.id)
      if not ok:
        gui_app.push_widget(BigDialog("favorites", msg))
      return

    if not ui_state.is_offroad():
      gui_app.push_widget(BigDialog("driving model", "Park first. Models can only change offroad."))
      return

    if self.info.egpu and not chestnut_present():
      gui_app.push_widget(BigDialog("eGPU", "Connect Chestnut to use eGPU models."))
      return

    ok, msg = select_model(self.info.id)
    self._selected = selected_id() == self.info.id
    self._refresh_value()
    if not ok and msg == "installing":
      return
    if not ok:
      gui_app.push_widget(BigDialog("driving model", msg))

  def _draw_content(self, btn_y: float):
    super()._draw_content(btn_y)
    font = gui_app.font(FontWeight.BOLD)
    if self.info.egpu:
      badge = "eGPU"
      bsz = 18
      tw = measure_text_cached(font, badge, bsz)
      bx = self._rect.x + 40
      by = btn_y + 8
      rec = rl.Rectangle(bx, by, tw.x + 16, tw.y + 8)
      rl.draw_rectangle_rounded(rec, 0.4, 6, EGPU_BG)
      rl.draw_text_ex(font, badge, rl.Vector2(bx + 8, by + 3), bsz, 0, LABEL_WHITE)
    if self.info.source == "release":
      return
    star = "★" if self._starred else "☆"
    color = STAR_GOLD if self._starred else STAR_DIM
    sz = 42
    text_size = measure_text_cached(font, star, sz)
    x = self._rect.x + self._rect.width - 28 - text_size.x
    y = btn_y + 18
    rl.draw_text_ex(font, star, rl.Vector2(x, y), sz, 0, color)


class SectionLabel(GreyBigButton):
  def __init__(self, title: str, subtitle: str = ""):
    super().__init__(title, subtitle)


class SelectedModelCard(GreyBigButton):
  def __init__(self):
    super().__init__("selected model", "")
    self.refresh()

  def refresh(self):
    sid = selected_id()
    info = find_model(sid)
    if info is None:
      self.set_value("Openpilot Release")
      return
    extra = "  ·  eGPU" if info.egpu else ""
    self.set_value(f"{info.name}{extra}\n{info.date}")

  def show_event(self):
    super().show_event()
    self.refresh()


class ModelUpdaterButton(BigButton):
  def __init__(self, on_done=None):
    super().__init__("model updater", "fetch last 3 master models")
    self._on_done = on_done
    self._busy = False

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if self._busy:
      return
    self._busy = True
    self.set_value("updating…")
    self.set_rotate_icon(True)

    def run():
      try:
        refresh_catalog(include_egpu=chestnut_present())
        self.set_value("catalog updated")
      except Exception as e:
        self.set_value("update failed")
        gui_app.push_widget(BigDialog("model updater", str(e)[:180]))
      finally:
        self._busy = False
        self.set_rotate_icon(False)
        if self._on_done:
          self._on_done()

    threading.Thread(target=run, daemon=True).start()


class InstallProgress(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 402, 90))

  def _render(self, _):
    st = get_install_status()
    if not st or st.get("stage") in ("", "ready", None):
      return
    stage = st.get("stage") or ""
    pct = int(st.get("percent") or 0)
    err = st.get("error") or ""
    mid = st.get("id") or ""
    info = find_model(mid)
    name = info.name if info else mid
    rl.draw_rectangle_rounded(self._rect, 0.3, 8, rl.Color(30, 30, 30, 255))
    font = gui_app.font(FontWeight.ROMAN)
    label = f"{name}: {stage} {pct}%" if not err else f"{name}: {err}"
    rl.draw_text_ex(font, label[:48], rl.Vector2(self._rect.x + 16, self._rect.y + 12), 28, 0, LABEL_WHITE)
    bar = rl.Rectangle(self._rect.x + 16, self._rect.y + 52, self._rect.width - 32, 16)
    rl.draw_rectangle_rec(bar, rl.Color(60, 60, 60, 255))
    fill = rl.Rectangle(bar.x, bar.y, bar.width * max(0, min(pct, 100)) / 100.0, bar.height)
    rl.draw_rectangle_rec(fill, rl.Color(80, 180, 110, 255))


class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._egpu = chestnut_present()
    self._selected_card = SelectedModelCard()
    self._progress = InstallProgress()
    self._updater = ModelUpdaterButton(on_done=self.rebuild)
    self._last_stage = None
    self.rebuild()

  def show_event(self):
    super().show_event()
    self._egpu = chestnut_present()
    self.rebuild()

  def _update_state(self):
    st = get_install_status()
    stage = st.get("stage") if st else None
    if stage != self._last_stage:
      self._last_stage = stage
      if stage in ("ready", "failed"):
        self._selected_card.refresh()
        self.rebuild()

  def rebuild(self):
    catalog = load_catalog()
    widgets: list[Widget] = [
      self._selected_card,
      self._progress,
    ]

    fav_reg = favorites(False, catalog)
    fav_egpu = favorites(True, catalog) if self._egpu else []
    widgets.append(SectionLabel("favorite models", f"up to {MAX_FAVORITES} each pool"))
    if not fav_reg and not fav_egpu:
      widgets.append(GreyBigButton("", "star a master model to keep it"))
    for info in fav_reg + fav_egpu:
      widgets.append(ModelRow(info))

    widgets.append(SectionLabel("master models", "last 3 from comma master"))
    master_reg = masters(False, catalog)
    master_egpu = masters(True, catalog) if self._egpu else []
    if not master_reg and not master_egpu:
      widgets.append(GreyBigButton("", "tap model updater to fetch the list"))
    shown = {m.id for m in fav_reg + fav_egpu}
    for info in master_reg + master_egpu:
      if info.id in shown:
        continue
      widgets.append(ModelRow(info))

    widgets.append(SectionLabel("release", "always available"))
    widgets.append(ModelRow(find_model("release", catalog) or catalog_all(catalog)[0]))
    if self._egpu:
      egpu_rel = find_model("release-egpu", catalog)
      if egpu_rel:
        widgets.append(ModelRow(egpu_rel))

    widgets.append(self._updater)
    self._scroller._items.clear()
    self._scroller.add_widgets(widgets)


class DrivingModelButton(BigButton):
  """Top-level settings entry."""

  def __init__(self):
    super().__init__("driving model", "")
    self._panel = ModelsLayoutMici()
    self.set_click_callback(lambda: gui_app.push_widget(self._panel))
    self.refresh()

  def refresh(self):
    sid = selected_id()
    info = find_model(sid)
    self.set_value(info.label if info else "Openpilot Release")

  def show_event(self):
    super().show_event()
    self.refresh()
    st = get_install_status()
    if st.get("stage") in ("downloading", "compiling"):
      self.set_value(f"{st.get('stage')} {int(st.get('percent') or 0)}%")
