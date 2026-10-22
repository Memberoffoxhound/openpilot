"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
Ported to Highland from zoompilot develop 632b0b0
(selfdrive/ui/sunnypilot/accelerator_link.py, and the models panel's
_model_info / model_info.big_model_state): what the models panel and the
status icons say of Jetlink. Highland: no sunnypilot model manager message, so
the names come from Highland's model picker (model_picker.py), and every
function takes the snapshot it reads (ui_state.jetlink, ui_state.chestnut_state)
so it is tested without a UI. Nothing here raises.

The user's say over the Jetlink setting: Off, USB (a Jetson, a Linux PC or a
Mac) or iOS (an iPhone), stored as an index into the adapter's MODES. Everything
else reads ui_state.jetlink, the snapshot the params pass takes
(jetlink.openpilot.Status), whose running/active fields come from modeld's
runtime record (/dev/shm/jetlink/modeld.json).
"""
from __future__ import annotations

from openpilot.selfdrive import jetlink_adapter

LINK_MODE_LABELS = {"off": "off", "usb": "usb", "ios": "iOS"}

# ChestnutState values (ui_state.ChestnutState), as plain strings
_FAILED = ('uncompiled', 'failed')


def link_mode() -> str:
  """The setting as stored, one of MODES: the panel shows it even when
  jetlink cannot run, so a link that will not start can be turned off."""
  index = jetlink_adapter.link_mode()
  return jetlink_adapter.MODES[index] if 0 <= index < len(jetlink_adapter.MODES) else "off"


def link_toggle_meaningful(chestnut_present: bool) -> bool:
  """Offered wherever there is no chestnut, which runs the big model itself;
  and while the setting is on, whatever else. Presence cannot be the gate:
  with the link off there is no gadget for a Jetson to enumerate."""
  return not chestnut_present or link_mode() != "off"


def link_status(jetlink) -> str:
  """One line: what is on the comma's USB-C port right now. jetlink knows a
  Jetson, or a phone, and the transport says which. Below that only the CC pin
  speaks. Empty where the kernel does not expose it."""
  port = getattr(jetlink, 'port_state', None) if jetlink is not None else None
  if port == "connected":
    return f"Jetlink connected: {jetlink.transport}."
  return {"empty": "Nothing on the USB port.", "device": "A device is on the USB port."}.get(port, "")


def big_model_progress(jetlink) -> tuple[str, float, str] | None:
  """(stage, 0..1, message) while jetlink is working, else None. The message
  names the cable (or the app, on iOS) once jetlink counts enough link drops."""
  progress = getattr(jetlink, 'progress', None) if jetlink is not None else None
  if not isinstance(progress, dict) or not progress:
    return None
  stage = str(progress.get('stage', ''))
  if stage in ('', 'ready'):
    return None
  msg = str(progress.get('msg', ''))
  if drops := progress.get('drops'):
    hint = "check cable or app" if getattr(jetlink, 'mode', '') == 'ios' else "check cable"
    msg = f"{msg}, {hint} ({drops} drops)"
  try:
    frac = float(progress.get('frac', 0.0))
  except (TypeError, ValueError):
    frac = 0.0
  return stage, frac, msg


def standin_model(jetlink, chestnut_present: bool) -> str | None:
  """The big model jetlink drives while the pick is still being downloaded or
  built: the last one the Jetson built."""
  return None if chestnut_present else getattr(jetlink, 'standin', None)


def big_model_state(chestnut_state: str) -> str | None:
  """'failed' | 'loading' | 'ready' | None, from the state the icons render."""
  return {'uncompiled': 'failed', 'failed': 'failed', 'loading': 'loading', 'waiting': 'ready'}.get(chestnut_state)


def model_info(jetlink, chestnut_state: str, chestnut_present: bool, small_name: str, big_name: str) -> tuple[str, str, str]:
  """(active model, info header, info text) for the models panel, as
  zoompilot's _model_info: the active line names what actually drives (the
  link's big model while it is active, else the small model), and a notable
  big-model state takes the info pair."""
  try:
    carry = None
    if not chestnut_present and chestnut_state == 'active' and jetlink is not None:
      carry = jetlink.active_model
    active_text = (carry or small_name).lower()
    provisioning = big_model_progress(jetlink)
    if provisioning is not None:
      stage, frac, msg = provisioning
      if stage == 'failed':
        return active_text, "big model", msg or "unavailable"
      detail = msg or stage
      return active_text, "big model", f"{detail} {frac * 100:.0f}%" if frac > 0 else detail
    if standin := standin_model(jetlink, chestnut_present):
      return active_text, "big model", f"{standin.lower()} for now"
    state = big_model_state(chestnut_state)
    if state == 'failed':
      return active_text, "big model", "unavailable"
    if state == 'loading':
      return active_text, "big model", "getting ready"
    return active_text, "big model", big_name.lower()
  except Exception:
    return small_name.lower(), "big model", big_name.lower()
