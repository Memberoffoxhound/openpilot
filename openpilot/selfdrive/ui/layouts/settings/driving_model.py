"""Settings → Driving Model. First C4 settings panel.

Openpilot Release is always available (bundled). Master models are the last
three comma.ai/openpilot bumps of driving_supercombo.onnx. Star a master to
keep it off the 3-deep cycle (5 regular + 5 eGPU). eGPU / Chestnut models
only appear when Chestnut is present.
"""
from __future__ import annotations

import threading

from openpilot.selfdrive.modeld.helpers import chestnut_present
from openpilot.selfdrive.modeld.model_manager import (
  MAX_FAVORITES,
  MAX_MASTER,
  favorites,
  find_model,
  get_install_status,
  is_favorite,
  is_installed,
  masters,
  refresh_catalog,
  select_model,
  selected_id,
  start_install,
  toggle_favorite,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import ListItem, button_item, dual_button_item, text_item
from openpilot.system.ui.widgets.scroller_tici import Scroller


def _badge_name(info) -> str:
  name = info.name
  if info.egpu:
    name = f"{name}  eGPU"
  return name


def _row_value(info) -> str:
  bits = [info.date] if info.date else []
  if info.source == "release":
    bits.append("release")
  elif is_favorite(info.id):
    bits.append("favorite")
  else:
    bits.append("master")
  if is_installed(info):
    bits.append("ready")
  else:
    st = get_install_status()
    if st.get("id") == info.id:
      stage = st.get("stage") or "installing"
      pct = st.get("percent")
      bits.append(f"{stage} {pct}%" if pct is not None else stage)
    else:
      bits.append("not installed")
  return "  ·  ".join(bits)


class DrivingModelLayout(Widget):
  def __init__(self):
    super().__init__()
    self._egpu = False
    self._refreshing = False
    self._last_status = None
    self._last_selected = None
    self._notice = ""
    self._scroller = Scroller([], line_separator=True, spacing=0)
    self._rebuild()

  def show_event(self):
    super().show_event()
    self._rebuild()
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)

  def _update_state(self):
    self._egpu = chestnut_present()
    status = get_install_status()
    sid = selected_id()
    if status != self._last_status or sid != self._last_selected:
      self._last_status = dict(status) if isinstance(status, dict) else status
      self._last_selected = sid
      self._rebuild()

  def _rebuild(self):
    self._egpu = chestnut_present()
    items: list[Widget] = []

    sid = selected_id()
    selected = find_model(sid)
    selected_title = _badge_name(selected) if selected else (sid or "Openpilot Release")
    selected_sub = _row_value(selected) if selected else "bundled"
    st = get_install_status()
    if st.get("stage") in ("downloading", "compiling") and st.get("id") == sid:
      selected_sub = f"{st.get('stage')}  {st.get('percent', 0)}%"
    elif st.get("stage") == "failed":
      selected_sub = f"failed: {st.get('error') or 'install error'}"

    items.append(text_item(lambda: tr("selected model"), selected_title, description=selected_sub))
    if self._notice:
      items.append(ListItem(title=self._notice))

    items.append(ListItem(title=lambda: tr("available models")))
    release = find_model("release")
    if release is not None:
      items.append(self._model_row(release, sid, star=False))
    items.extend(self._section(lambda: tr("favorite models"), favorites(False), star=True))
    items.extend(self._section(lambda: tr("master models"), masters(False), star=True))

    if self._egpu:
      items.append(ListItem(title=lambda: tr("eGPU models")))
      release_e = find_model("release-egpu")
      if release_e is not None:
        items.append(self._model_row(release_e, sid, star=False))
      items.extend(self._section(lambda: tr("favorite eGPU"), favorites(True), star=True))
      items.extend(self._section(lambda: tr("master eGPU"), masters(True), star=True))

    updater_label = tr("refreshing…") if self._refreshing else tr("CHECK")
    updater = button_item(
      lambda: tr("model updater"),
      updater_label,
      description=lambda: tr(
        "Fetches the last {} comma master models. Does not download ONNX until you select or star one. "
        "Release is always available. Up to {} favorites per pool."
      ).format(MAX_MASTER, MAX_FAVORITES),
      callback=self._on_update,
      enabled=lambda: not self._refreshing and ui_state.is_offroad(),
    )
    items.append(updater)

    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _section(self, title, models, star: bool) -> list[Widget]:
    rows: list[Widget] = [ListItem(title=title)]
    if not models:
      rows.append(ListItem(title=lambda: tr("none")))
      return rows

    sid = selected_id()
    seen = set()
    for info in models:
      if info.id in seen:
        continue
      seen.add(info.id)
      rows.append(self._model_row(info, sid, star))
    return rows

  def _model_row(self, info, sid: str, star: bool) -> ListItem:
    fav = is_favorite(info.id)
    installing = False
    st = get_install_status()
    if st.get("id") == info.id and st.get("stage") in ("downloading", "compiling"):
      installing = True

    left = tr("ON") if info.id == sid else (tr("WAIT") if installing else tr("SELECT"))
    right = "★" if fav else "☆"
    title = _badge_name(info)

    show_star = star and not info.id.startswith("release")
    item = dual_button_item(
      left,
      right if show_star else "★",
      left_callback=lambda i=info: self._on_select(i.id),
      right_callback=lambda i=info: self._on_star(i.id) if show_star else None,
      description=_row_value(info),
      enabled=lambda: ui_state.is_offroad() or info.id == selected_id(),
    )
    item._title = title
    # DualButtonAction defaults to full-width; shrink it so the model name stays visible.
    if item.action_item is not None:
      item.action_item._rect.width = 530
      if not show_star:
        item.action_item.right_button.set_visible(False)
    return item

  def _on_select(self, model_id: str):
    if ui_state.is_onroad() and ui_state.engaged:
      self._notice = tr("disengage before switching models")
      self._rebuild()
      return
    ok, msg = select_model(model_id)
    if not ok and msg == "installing":
      start_install(model_id, select_when_done=True)
      self._notice = tr("installing — select applies when ready")
    elif not ok:
      self._notice = msg
    else:
      self._notice = tr("selected — onroad cycle requested")
    self._rebuild()

  def _on_star(self, model_id: str):
    ok, msg = toggle_favorite(model_id)
    if not ok:
      self._notice = msg
    else:
      self._notice = tr("starred") if msg == "starred" else tr("unstarred")
    self._rebuild()

  def _on_update(self):
    if self._refreshing:
      return
    self._refreshing = True
    self._notice = tr("checking comma master…")
    self._rebuild()

    def run():
      try:
        refresh_catalog(include_egpu=chestnut_present())
        self._notice = tr("catalog updated")
      except Exception as e:
        self._notice = f"updater failed: {str(e)[:80]}"
      finally:
        self._refreshing = False
        self._last_status = None

    threading.Thread(target=run, daemon=True).start()
