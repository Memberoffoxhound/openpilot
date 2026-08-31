"""Today/Week meters. Live vEgo only. Never merge qlogs into the meter."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openpilot.selfdrive.ui.ui_state import ui_state

TZ = ZoneInfo("America/Chicago")
TRIP_PATH = "/data/trip_meter.json"
TRIP_VER = 5
RESET_KEYS = ("today_m", "today_eng_m", "week_m", "week_eng_m")

_trip: dict | None = None
_trip_t = 0.0
_trip_flush = 0.0


def _day_id() -> str:
  now = datetime.now(TZ)
  return f"{now.year:04d}-{now.month:02d}-{now.day:02d}"


def _sunday_id() -> str:
  now = datetime.now(TZ)
  sun = now - timedelta(days=(now.weekday() + 1) % 7)
  return f"{sun.year:04d}-{sun.month:02d}-{sun.day:02d}"


def day_id() -> str:
  return _day_id()


def sunday_id() -> str:
  return _sunday_id()


def chicago_now() -> datetime:
  return datetime.now(TZ)


def _f(d: dict, k: str) -> float:
  try:
    return float(d.get(k) or 0)
  except (TypeError, ValueError):
    return 0.0


def _load_trip() -> dict:
  t = {"week_m": 0.0, "week_eng_m": 0.0, "week_id": "",
       "today_m": 0.0, "today_eng_m": 0.0, "day_id": "", "v": TRIP_VER}
  try:
    t.update(json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  try:
    ver = int(t.get("v") or 0)
  except (TypeError, ValueError):
    ver = 0
  if ver != TRIP_VER:
    for k in RESET_KEYS:
      t[k] = 0.0
    t["v"] = TRIP_VER
  if t.get("day_id") != _day_id():
    t["today_m"] = t["today_eng_m"] = 0.0
    t["day_id"] = _day_id()
  if t.get("week_id") != _sunday_id():
    t["week_m"] = t["week_eng_m"] = 0.0
    t["week_id"] = _sunday_id()
  return t


def _save_trip(t: dict) -> None:
  tmp = TRIP_PATH + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(t, f)
  os.replace(tmp, TRIP_PATH)


def trip_snapshot() -> dict:
  if _trip is not None:
    return dict(_trip)
  return _load_trip()


def tick_trip() -> None:
  global _trip, _trip_t, _trip_flush
  now = time.monotonic()
  if _trip is None:
    _trip = _load_trip()
    _trip_t = now
    _save_trip(_trip)
    return
  dt = min(1.0, max(0.0, now - _trip_t))
  _trip_t = now
  day, week = _day_id(), _sunday_id()
  if _trip.get("day_id") != day:
    _trip["today_m"] = _trip["today_eng_m"] = 0.0
    _trip["day_id"] = day
  if _trip.get("week_id") != week:
    _trip["week_m"] = _trip["week_eng_m"] = 0.0
    _trip["week_id"] = week
  try:
    offroad = ui_state.params.get_bool("IsOffroad")
    cs_ok = ui_state.sm.recv_frame["carState"] > 0
  except Exception:
    offroad, cs_ok = True, False
  if (not offroad) and cs_ok:
    v = max(0.0, float(ui_state.sm["carState"].vEgo))
    if v > 0.15:
      _trip["week_m"] += v * dt
      _trip["today_m"] += v * dt
      try:
        if ui_state.sm.recv_frame["selfdriveState"] > 0 and ui_state.sm["selfdriveState"].enabled:
          _trip["week_eng_m"] += v * dt
          _trip["today_eng_m"] += v * dt
      except Exception:
        pass
  if now - _trip_flush > 1.0:
    _save_trip(_trip)
    _trip_flush = now
