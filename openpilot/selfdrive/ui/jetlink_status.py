"""Jetlink as Highland's UI sees it: one snapshot for the status page, the
home footer and the onroad HUD. Pure logic over three inputs, so it is
tested without a UI:

  - jetlink's own Status (jetlink_adapter.status()): files and params only,
    asked at most once a second and only while the Jetlink setting is on
  - modeld's live file (jetlink_adapter.read_live()): the joining model's
    state, whether the big model drives and frame timing, once a second
  - modelV2.big from ui_state, when onroad

Nothing here raises: a missing jetlinkd, missing keys or no jetlink checkout
all read as the link being off / waiting.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from openpilot.selfdrive import jetlink_adapter as ja

MODE_TITLES = {'off': 'off', 'usb': 'USB (Jetson/Mac/Android)', 'ios': 'iPhone'}

# link states, as the page shows them
OFF = 'off'
UNAVAILABLE = 'unavailable'
WAITING = 'waiting for phone'
PREPARING = 'preparing model'
CONNECTED = 'connected'
READY = 'connected, ready'
JOINING = 'connecting big model'
WAITING_SWITCH = 'ready, switches when disengaged'
DRIVING = 'big model driving'
FELL_BACK = 'fell back to small model'

# icon states: None hides it
ICON_ACTIVE = 'active'    # bright: the phone's big model drives
ICON_DIM = 'dim'          # dim: connected and ready (offroad), or fell back / waiting onroad
ICON_PULSE = 'pulse'      # preparing / joining


@dataclass(frozen=True)
class Snapshot:
  mode: str = 'off'
  state: str = OFF
  icon: str | None = None
  transport: str = ''
  model: str | None = None
  progress: tuple[str, float, str] | None = None
  timing: str | None = None
  reason: str | None = None


def progress_of(status) -> tuple[str, float, str] | None:
  p = getattr(status, 'progress', None)
  if not isinstance(p, dict):
    return None
  stage = str(p.get('stage', ''))
  if stage in ('', 'ready'):
    return None
  try:
    frac = max(0.0, min(1.0, float(p.get('frac', 0.0))))
  except (TypeError, ValueError):
    frac = 0.0
  msg = str(p.get('msg', ''))
  if p.get('drops'):
    msg = f"{msg}, check cable/app ({p['drops']} drops)"
  return stage, frac, msg


def timing_of(live: dict | None) -> str | None:
  if not live or not live.get('frames'):
    return None
  try:
    head = f"{float(live['exec_ms_mean']):.0f} ms avg / {float(live['exec_ms_max']):.0f} ms max"
    return head + f" (budget {ja.BUDGET_MS:.0f} ms, {int(live.get('over_budget', 0))} over)"
  except (KeyError, TypeError, ValueError):
    return None


def evaluate(mode: str, status, live: dict | None, started: bool, model_big: bool) -> Snapshot:
  """The whole decision, pure. `status` is jetlink's Status or None,
  `live` modeld's live record or None, `model_big` modelV2.big."""
  if mode == 'off':
    return Snapshot()
  base = {'mode': mode, 'transport': str(getattr(status, 'transport', '') or ''),
          'model': getattr(status, 'active_model', None) or getattr(status, 'model', None),
          'progress': progress_of(status), 'timing': timing_of(live), 'reason': getattr(status, 'reason', None)}
  if status is None or not getattr(status, 'enabled', False):
    return Snapshot(**base, state=UNAVAILABLE)
  present = bool(getattr(status, 'present', False))
  live_state = (live or {}).get('state')
  if started:
    if live and live.get('big') and model_big:
      return Snapshot(**base, state=DRIVING, icon=ICON_ACTIVE)
    if live_state in ('joining', 'retrying') and present:
      return Snapshot(**base, state=JOINING, icon=ICON_PULSE)
    if live_state == 'ready':
      return Snapshot(**base, state=WAITING_SWITCH, icon=ICON_DIM)
    if live_state in ('unavailable', 'running') or (live and not live.get('big')):
      return Snapshot(**base, state=FELL_BACK if present or live_state == 'unavailable' else WAITING, icon=ICON_DIM)
    return Snapshot(**base, state=CONNECTED if present else WAITING, icon=ICON_DIM if present else None)
  if not present:
    return Snapshot(**base, state=WAITING)
  if base['progress'] is not None:
    return Snapshot(**base, state=PREPARING, icon=ICON_PULSE)
  runnable = bool(getattr(status, 'runnable', False))
  return Snapshot(**base, state=READY if runnable else CONNECTED, icon=ICON_DIM if runnable else None)


class JetlinkUI:
  """Cached snapshot; refresh() at most once per PERIOD. Never raises."""
  PERIOD = 1.0

  def __init__(self):
    self._at = 0.0
    self.snapshot = Snapshot()

  def refresh(self, started: bool = False, model_big: bool = False, now: float | None = None) -> Snapshot:
    now = time.monotonic() if now is None else now
    if now - self._at < self.PERIOD:
      return self.snapshot
    self._at = now
    try:
      index = ja.link_mode()
      mode = ja.MODES[index] if 0 <= index < len(ja.MODES) else 'off'
      if mode == 'off':
        self.snapshot = Snapshot()
      else:
        self.snapshot = evaluate(mode, ja.status(), ja.read_live(), started, model_big)
    except Exception:
      self.snapshot = Snapshot()
    return self.snapshot


jetlink_ui = JetlinkUI()
