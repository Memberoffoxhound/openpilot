"""Trip stats: the drive summary card, Home's Day / Week row and the Statistics page, for any car.

One recorder in the UI process, one store (store.py). See README.md for the hooks.
  tick(ui_state)       every UI frame: records the drive, stores it when it ends
  view(params)         every number the UI shows, the drive in progress included
  due_summary(params)  the trip that just ended, if the card is due
  missed_trip(params)  a trip whose card never came up (power cut at ignition off), for the last trip summary card
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta, timezone

from openpilot.common.params_compat import get_bool, put_bool
from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.tripstats import store, tz
from openpilot.selfdrive.ui.tripstats.card import eligible
from openpilot.selfdrive.ui.tripstats.recorder import MOVING_V, DriveRecorder

PARAM_ENABLED = "DriveSummary"
PARAM_LAST = store.PARAM
SHOW_S = 20.0                # seconds the card holds the onroad page before the scroll to home
SAVE_S = 30.0                # the drive in progress is stored this often, for a UI restart and the web GUI
ZONE_S = 10.0                # the zone params are read again this often
LOOKUP_S = (10.0, 300.0)     # the GPS zone lookup: this long after the first tick (the UI is up), then this often

live = DriveRecorder()                 # the drive in progress
_data: dict | None = None
_held: list[dict] = []       # ended or saved on a stale clock, not in days yet
_saved_t = 0.0
_zone = (-1e9, None)
_lookup_t: float | None = None
_enabled_cache = (0.0, False)
_route_t = 0.0
_logged = False


def wall_now() -> float:
  return datetime.now().timestamp()


def _store(params) -> dict:
  """Loaded once. Drives left open by the last run (power cut, UI restart) close at their last stamp,
  dated with its offset, even before the clock is valid; ones stamped on a stale clock wait for a valid one."""
  global _data, _held
  if _data is None:
    data = store.load(params)
    opens = data.pop("open")
    _held = [d for d in opens if not d["ok"]]
    for d in opens:
      if d["ok"]:
        data = store.add_drive(data, d)
    _data = data
    if len(_held) < len(opens):
      _save(params)
  return _data


def zone(params):
  """The zone for Day / Week (tz.zone), read again every ZONE_S."""
  global _zone
  now = time.monotonic()
  if now - _zone[0] > ZONE_S:
    _zone = (now, tz.zone(params))
  return _zone[1]


def _open() -> list[dict]:
  return _held + ([live.summary(wall_now())] if live.active else [])


def view(params, drive: dict | None = None) -> dict:
  """Now, in the device zone; or as of a stored drive's end, in its offset."""
  z = zone(params)
  first = tz.first_day(z)                    # the week rule where the car is now, also for a stored drive
  if drive is None:
    return store.view(_store(params), _open(), datetime.fromtimestamp(wall_now(), UTC), z, first)
  return store.view(_store(params), (), datetime.fromtimestamp(drive["end"], UTC), timezone(timedelta(seconds=drive["off"])), first)


def enabled(params) -> bool:
  global _enabled_cache
  now = time.monotonic()
  if now - _enabled_cache[0] > 2.0:
    _enabled_cache = (now, get_bool(params, PARAM_ENABLED, False))
  return _enabled_cache[1]


def set_enabled(params, on: bool) -> None:
  put_bool(params, PARAM_ENABLED, on)


def due_summary(params, rec: DriveRecorder | None = None) -> dict | None:
  """The trip that just ended, if the card is due (toggle on, recorded, stopped, long enough)."""
  rec = live if rec is None else rec
  if not enabled(params) or not rec.active or rec.last_v > MOVING_V:
    return None
  drive = rec.summary(wall_now())
  return drive if eligible(drive) else None


def missed_trip(params) -> dict | None:
  """The last trip, if its card never came up and would have (toggle on, long enough)."""
  last = _store(params).get("last")
  return last if last and not last.get("shown") and enabled(params) and eligible(last) else None


def mark_shown(params, drive: dict | None = None) -> None:
  """The card is up for drive (the live one, or the stored last trip); stored now, so a power cut doesn't
  bring it back as a last trip summary."""
  global _data
  try:
    if drive is None:
      live.shown = True
    elif drive is _store(params).get("last"):
      _data = {**_data, "last": {**drive, "shown": True}}
    _save(params)
  except Exception:
    pass                     # never keeps the card down


def _save(params) -> None:
  global _saved_t
  _saved_t = time.monotonic()
  w, ok = wall_now(), system_time_valid()
  store.save(params, {**_store(params), "open": [store.stamp(d, w, zone(params), ok) for d in _open()]})


def _lookup(params) -> None:
  global _zone
  try:
    if tz.update(params):
      _zone = (-1e9, None)
  except Exception:
    pass


def tick(ui_state) -> None:
  global _data, _held, _route_t, _logged, _lookup_t
  params = ui_state.params
  try:
    data = _store(params)
    sm = ui_state.sm
    started = bool(ui_state.started)
    v = engaged = False
    state, alert, alert_type = "", "normal", ""
    if started:
      cs = sm["carState"]
      v = max(0.0, float(cs.vEgo))
      if sm.recv_frame["selfdriveState"] >= ui_state.started_frame:
        ss = sm["selfdriveState"]
        engaged = bool(ss.enabled)
        state, alert, alert_type = str(ss.state), str(ss.alertStatus), str(ss.alertType)
    route = ""
    now = time.monotonic()
    if started and (not live.active or live.drive_id.startswith("t")) and now - _route_t > 1.0:
      _route_t = now
      route = params.get("CurrentRoute") or ""
      if isinstance(route, bytes):
        route = route.decode(errors="replace")
    done = live.update(started, now, wall_now(), float(v), engaged, state, alert, alert_type, str(route))
    if done is not None:
      _held.append(done)
    if _held and system_time_valid():     # a stale clock would date it on the wrong day: wait for a valid one
      for d in _held:
        data = store.add_drive(data, store.stamp(d, wall_now(), zone(params)))
      _data, _held = data, []
      _save(params)
    elif done is not None or (live.active and now - _saved_t > SAVE_S):
      _save(params)
    if _lookup_t is None:
      _lookup_t = now + LOOKUP_S[0]
    elif now >= _lookup_t:
      _lookup_t = now + LOOKUP_S[1]
      threading.Thread(target=_lookup, args=(params,), daemon=True, name="tripstats-tz").start()
  except Exception:
    if not _logged:
      _logged = True
      from openpilot.common.swaglog import cloudlog
      cloudlog.exception("tripstats tick")
