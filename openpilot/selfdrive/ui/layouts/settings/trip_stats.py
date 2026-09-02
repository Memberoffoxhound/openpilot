"""One trip cache. Qlogs are source of truth.

/data/trip_stats.json is the only store Home and the statistics
widgets read. Completed miles come from qlogs (via the segment
cache). The current drive is a live overlay that is never written
into days[] while onroad. Fold rebuilds days[] from the segment
cache, so a segment cannot be counted twice.

Pending holds completed-route miles that days[] does not have yet
(new route, or a fold that ran before hot qlogs were readable).
Both live and pending are stamped with a Chicago day. Offroad fold
commits them into that day and clears the overlay so a short park
window cannot leave yesterday on Today's row.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from openpilot.common.params import Params
from openpilot.selfdrive.ui.layouts.settings.trip_seed import (
  CACHE_KEEP_SEC, TZ, _f, _iter_qlogs, _load_seg_cache, _save_seg_cache,
  _cache_hit, _read_qlog, _seg_tuple, chicago_now, day_id, sunday_id, HOT_SEC,
)

STATS_PATH = Path("/data/trip_stats.json")
STATS_VER = 5
DAY_KEEP = 400
STATS_LOCK = Path("/data/trip_stats.lock")

_cache: dict | None = None
_cache_mt = -1.0
_lock = threading.Lock()
_live_mem: dict | None = None
_live_dirty = False


def empty_live() -> dict:
  return {"route": "", "day": "", "m": 0.0, "e": 0.0, "streak_m": 0.0}


def empty_pending() -> dict:
  return {"day": "", "m": 0.0, "e": 0.0}


def empty_stats() -> dict:
  return {
    "v": STATS_VER,
    "days": {},
    "months": {},
    "folded": [],
    "life_m": 0.0,
    "life_e": 0.0,
    "max_streak_m": 0.0,
    "max_day_streak": 0,
    "live": empty_live(),
    "pending": empty_pending(),
  }


def _current_route() -> str:
  try:
    r = Params().get("CurrentRoute") or ""
    if isinstance(r, bytes):
      r = r.decode(errors="replace")
    return str(r)
  except Exception:
    return ""


def _is_offroad() -> bool:
  try:
    return bool(Params().get_bool("IsOffroad"))
  except Exception:
    return True


def _normalize_live(raw) -> dict:
  live = empty_live()
  if not isinstance(raw, dict):
    return live
  live["route"] = str(raw.get("route") or "")
  live["day"] = str(raw.get("day") or "")
  live["m"] = _f(raw, "m")
  live["e"] = _f(raw, "e")
  live["streak_m"] = _f(raw, "streak_m")
  return live


def _normalize_pending(raw) -> dict:
  pending = empty_pending()
  if not isinstance(raw, dict):
    return pending
  pending["day"] = str(raw.get("day") or "")
  pending["m"] = max(0.0, _f(raw, "m"))
  pending["e"] = max(0.0, _f(raw, "e"))
  return pending


def _yesterday_id(today: str | None = None) -> str:
  raw = today or day_id()
  try:
    d = datetime.strptime(raw, "%Y-%m-%d").date()
  except ValueError:
    d = chicago_now().date()
  return (d - timedelta(days=1)).isoformat()


def _overlay_day(stamp: str, today: str, allow_today_guess: bool) -> str:
  """Chicago day this overlay belongs to.

  A missing stamp on an old file must not attach to a new today.
  Onroad live with no stamp is still this drive -> today.
  """
  if stamp:
    return stamp
  return today if allow_today_guess else _yesterday_id(today)


def _add_pending(dst: dict, meters: float, eng: float, day: str = "") -> dict:
  pending = _normalize_pending(dst)
  meters = max(0.0, float(meters or 0))
  eng = max(0.0, float(eng or 0))
  if meters <= 0 and eng <= 0:
    return pending
  src_day = str(day or pending.get("day") or day_id())
  pending["m"] = _f(pending, "m") + meters
  pending["e"] = _f(pending, "e") + eng
  if not pending.get("day"):
    pending["day"] = src_day
  return pending


def _commit_overlay(days: dict, months: dict, prev_days: dict, key: str,
                    extra_m: float, extra_e: float) -> tuple[float, float]:
  """Keep at least prev[key] + overlay in days[key]. Returns meters added."""
  extra_m = max(0.0, float(extra_m or 0))
  extra_e = max(0.0, float(extra_e or 0))
  if not key or (extra_m <= 0 and extra_e <= 0):
    return 0.0, 0.0
  b = _day_bucket(days, key)
  prev_b = prev_days.get(key) if isinstance(prev_days.get(key), dict) else {}
  want_m = _f(prev_b, "m") + extra_m
  want_e = _f(prev_b, "e") + extra_e
  add_m = max(0.0, want_m - _f(b, "m"))
  add_e = max(0.0, want_e - _f(b, "e"))
  if add_m <= 0 and add_e <= 0:
    return 0.0, 0.0
  b["m"] = _f(b, "m") + add_m
  b["e"] = _f(b, "e") + add_e
  mb = _day_bucket(months, key[:7])
  mb["m"] = _f(mb, "m") + add_m
  mb["e"] = _f(mb, "e") + add_e
  return add_m, add_e
