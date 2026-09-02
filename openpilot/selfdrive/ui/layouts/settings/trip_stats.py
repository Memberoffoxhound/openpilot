"""One trip cache. Qlogs are source of truth.

/data/trip_stats.json is the only store Home and the statistics
widgets read. Offroad fold commits live/pending into days[] immediately
so a short park window cannot leave yesterday on Today's row.
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
from openpilot.selfdrive.ui.layouts.settings.trip_overlay import (
  empty_live, empty_pending, normalize_live, normalize_pending,
  overlay_day, add_pending, day_bucket, commit_overlay,
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


def empty_stats() -> dict:
  return {
    "v": STATS_VER, "days": {}, "months": {}, "folded": [],
    "life_m": 0.0, "life_e": 0.0, "max_streak_m": 0.0, "max_day_streak": 0,
    "live": empty_live(), "pending": empty_pending(),
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


def _migrate_poison(st: dict) -> dict:
  st["v"] = STATS_VER
  if not isinstance(st.get("days"), dict):
    st["days"] = {}
  if not isinstance(st.get("months"), dict):
    st["months"] = {}
  if not isinstance(st.get("folded"), list):
    st["folded"] = []
  st["live"] = normalize_live(st.get("live"))
  st["pending"] = normalize_pending(st.get("pending"))
  st["life_m"] = _f(st, "life_m")
  st["life_e"] = _f(st, "life_e")
  st["max_streak_m"] = _f(st, "max_streak_m")
  st["max_day_streak"] = int(st.get("max_day_streak") or 0)
  return st


def load_stats() -> dict:
  global _cache, _cache_mt, _live_mem
  try:
    mt = STATS_PATH.stat().st_mtime
  except OSError:
    mt = 0.0
  with _lock:
    if _cache is not None and mt == _cache_mt:
      return _cache
  st = empty_stats()
  migrated = False
  try:
    raw = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    if isinstance(raw.get("days"), dict):
      st.update(raw)
      st["folded"] = st["folded"] if isinstance(st.get("folded"), list) else []
      st["days"] = st["days"] if isinstance(st.get("days"), dict) else {}
      st["months"] = st["months"] if isinstance(st.get("months"), dict) else {}
      st["max_day_streak"] = int(st.get("max_day_streak") or 0)
      st["live"] = normalize_live(st.get("live"))
      st["pending"] = normalize_pending(st.get("pending"))
      try:
        ver = int(st.get("v") or 0)
      except (TypeError, ValueError):
        ver = 0
      if ver != STATS_VER:
        st = _migrate_poison(st)
        migrated = True
  except Exception:
    pass
  with _lock:
    disk_live = normalize_live(st.get("live"))
    st["pending"] = normalize_pending(st.get("pending"))
    if _live_mem is not None:
      st = dict(st)
      if _is_offroad() and _f(disk_live, "m") <= 0 and _f(disk_live, "e") <= 0:
        _live_mem = empty_live()
        st["live"] = empty_live()
      else:
        st["live"] = dict(_live_mem)
    _cache, _cache_mt = st, mt
  if migrated:
    try:
      save_stats(st)
    except Exception:
      pass
  return st


def save_stats(st: dict) -> None:
  global _cache, _cache_mt, _live_mem
  st = dict(st)
  st["v"] = STATS_VER
  st["live"] = normalize_live(st.get("live"))
  st["pending"] = normalize_pending(st.get("pending"))
  tmp = str(STATS_PATH) + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(st, f)
  os.replace(tmp, STATS_PATH)
  try:
    mt = STATS_PATH.stat().st_mtime
  except OSError:
    mt = 0.0
  with _lock:
    _cache, _cache_mt = st, mt
    _live_mem = dict(st["live"])


def _merge_buckets(dst: dict, src) -> None:
  if not isinstance(src, dict):
    return
  for k, v in src.items():
    if not isinstance(v, dict):
      continue
    b = day_bucket(dst, str(k))
    b["m"] = max(_f(b, "m"), _f(v, "m"))
    b["e"] = max(_f(b, "e"), _f(v, "e"))


def _streaks(days: dict) -> tuple[int, int]:
  engaged = []
  for k, v in days.items():
    if _f(v, "e") > 1:
      try:
        engaged.append(datetime.strptime(str(k), "%Y-%m-%d").date())
      except ValueError:
        pass
  engaged.sort()
  longest = run = 0
  prev = None
  for d in engaged:
    run = run + 1 if prev is not None and (d - prev).days == 1 else 1
    longest = max(longest, run)
    prev = d
  today = chicago_now().date()
  cursor = today
  if _f(days.get(cursor.isoformat()) or {}, "e") <= 1:
    cursor = cursor - timedelta(days=1)
  current = 0
  while _f(days.get(cursor.isoformat()) or {}, "e") > 1:
    current += 1
    cursor = cursor - timedelta(days=1)
    if current > 4000:
      break
  return current, longest


def add_live(meters: float, eng: float, route: str, dt_streak: float) -> None:
  global _live_mem, _live_dirty
  if _cache is None:
    load_stats()
  with _lock:
    live = dict(_live_mem) if _live_mem is not None else empty_live()
    pending = normalize_pending((_cache or {}).get("pending"))
    route = str(route or "")
    today = day_id()
    live_day = str(live.get("day") or "")
    if route and route != live.get("route"):
      pending = add_pending(pending, _f(live, "m"), _f(live, "e"), live_day or today)
      live = empty_live()
      live["route"] = route
      live["day"] = today
    elif live_day and live_day != today and (_f(live, "m") > 0 or _f(live, "e") > 0):
      pending = add_pending(pending, _f(live, "m"), _f(live, "e"), live_day)
      keep = str(live.get("route") or route)
      live = empty_live()
      live["route"] = keep
      live["day"] = today
    elif not live.get("route"):
      live["route"] = route
      live["day"] = today
    elif not live_day:
      live["day"] = today
    live["m"] = _f(live, "m") + float(meters or 0)
    live["e"] = _f(live, "e") + float(eng or 0)
    live["streak_m"] = _f(live, "streak_m") + float(dt_streak or 0) if eng > 0 else 0.0
    _live_mem = live
    _live_dirty = True
    if _cache is not None:
      _cache["live"] = live
      _cache["pending"] = pending
      _cache["max_streak_m"] = max(_f(_cache, "max_streak_m"), _f(live, "streak_m"))


def flush_live() -> None:
  global _live_dirty
  with _lock:
    dirty = _live_dirty
    live = dict(_live_mem) if _live_mem is not None else None
    pending = normalize_pending((_cache or {}).get("pending"))
    _live_dirty = False
  if not dirty:
    return
  st = load_stats()
  if not _is_offroad() and live is not None:
    st["live"] = live
    st["max_streak_m"] = max(_f(st, "max_streak_m"), _f(live, "streak_m"))
  st["pending"] = pending
  save_stats(st)


def fold_stats_history() -> None:
  try:
    fd = os.open(STATS_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
  except FileExistsError:
    return
  try:
    _fold_stats_history()
  except Exception:
    from openpilot.common.swaglog import cloudlog
    cloudlog.exception("trip stats fold")
  finally:
    try:
      STATS_LOCK.unlink()
    except FileNotFoundError:
      pass


def _skip_name(name: str, route: str, offroad: bool, mt: float) -> bool:
  if (time.time() - mt) < HOT_SEC:
    return True
  if (not offroad) and route and route in str(name):
    return True
  return False


def _fold_stats_history() -> None:
  from openpilot.selfdrive.ui.layouts.settings.trip_fold import run_fold
  run_fold(load_stats, save_stats, _is_offroad, _current_route, _skip_name,
           _merge_buckets, _streaks, STATS_VER, DAY_KEEP)


def stats_view(trip: dict | None = None) -> dict:
  from openpilot.selfdrive.ui.layouts.settings.trip_fold import run_view
  return run_view(load_stats(), _is_offroad, _streaks)
