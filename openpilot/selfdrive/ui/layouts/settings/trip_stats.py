"""One trip cache. Qlogs are source of truth.

/data/trip_stats.json is the only store Home and the statistics
widgets read. Completed miles come from qlogs (via the segment
cache). The current drive is a live overlay that is never written
into days[]. Fold rebuilds days[] from the segment cache, so a
segment cannot be counted twice.
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
STATS_VER = 4
DAY_KEEP = 400
STATS_LOCK = Path("/data/trip_stats.lock")

_cache: dict | None = None
_cache_mt = -1.0
_lock = threading.Lock()
_live_mem: dict | None = None
_live_dirty = False


def empty_live() -> dict:
  return {"route": "", "m": 0.0, "e": 0.0, "streak_m": 0.0}


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
  live["m"] = _f(raw, "m")
  live["e"] = _f(raw, "e")
  live["streak_m"] = _f(raw, "streak_m")
  return live


def _migrate_poison(st: dict) -> dict:
  """Stamp current schema version. Never drop days or lifetime totals."""
  st["v"] = STATS_VER
  if not isinstance(st.get("days"), dict):
    st["days"] = {}
  if not isinstance(st.get("months"), dict):
    st["months"] = {}
  if not isinstance(st.get("folded"), list):
    st["folded"] = []
  st["live"] = _normalize_live(st.get("live"))
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
      if not isinstance(st.get("folded"), list):
        st["folded"] = []
      if not isinstance(st.get("days"), dict):
        st["days"] = {}
      if not isinstance(st.get("months"), dict):
        st["months"] = {}
      st["max_day_streak"] = int(st.get("max_day_streak") or 0)
      st["live"] = _normalize_live(st.get("live"))
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
    disk_live = _normalize_live(st.get("live"))
    if _live_mem is not None:
      st = dict(st)
      # Fold subprocess zeros disk live when parked. Drop the UI overlay
      # so this drive is not added on top of days[] that now include it.
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
  st["live"] = _normalize_live(st.get("live"))
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


def _day_bucket(days: dict, key: str) -> dict:
  b = days.get(key)
  if not isinstance(b, dict):
    b = {"m": 0.0, "e": 0.0}
    days[key] = b
  return b


def _merge_buckets(dst: dict, src) -> None:
  """Union day/month buckets. Max per key so a partial fold cannot shrink a day."""
  if not isinstance(src, dict):
    return
  for k, v in src.items():
    if not isinstance(v, dict):
      continue
    b = _day_bucket(dst, str(k))
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
  longest = 0
  run = 0
  prev = None
  for d in engaged:
    if prev is not None and (d - prev).days == 1:
      run += 1
    else:
      run = 1
    if run > longest:
      longest = run
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


def _remember_streak(st: dict, days: dict) -> int:
  current, window = _streaks(days)
  st["max_day_streak"] = max(int(st.get("max_day_streak") or 0), current, window)
  return st["max_day_streak"]


def add_live(meters: float, eng: float, route: str, dt_streak: float) -> None:
  """Current-drive overlay only. Never touches days[]. Memory first, disk on flush."""
  global _live_mem, _live_dirty
  if _cache is None:
    load_stats()
  with _lock:
    live = dict(_live_mem) if _live_mem is not None else empty_live()
    route = str(route or "")
    if route and route != live.get("route"):
      live = empty_live()
      live["route"] = route
    elif not live.get("route"):
      live["route"] = route
    live["m"] = _f(live, "m") + float(meters or 0)
    live["e"] = _f(live, "e") + float(eng or 0)
    if eng > 0:
      live["streak_m"] = _f(live, "streak_m") + float(dt_streak or 0)
    else:
      live["streak_m"] = 0.0
    _live_mem = live
    _live_dirty = True
    if _cache is not None:
      _cache["live"] = live
      _cache["max_streak_m"] = max(_f(_cache, "max_streak_m"), _f(live, "streak_m"))


def flush_live() -> None:
  """Persist this-drive overlay. Skip while parked so a fold cannot be overwritten."""
  global _live_dirty
  if _is_offroad():
    return
  with _lock:
    dirty = _live_dirty
    live = dict(_live_mem) if _live_mem is not None else None
    _live_dirty = False
  if not dirty or live is None:
    return
  st = load_stats()
  st["live"] = live
  st["max_streak_m"] = max(_f(st, "max_streak_m"), _f(live, "streak_m"))
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
  """Rebuild days[] from the qlog segment cache. Idempotent."""
  st = load_stats()
  prev_life_m = _f(st, "life_m")
  prev_life_e = _f(st, "life_e")
  prev_days = st.get("days") or {}
  prev_months = st.get("months") or {}
  offroad = _is_offroad()
  route = _current_route()
  min_mt = chicago_now().timestamp() - CACHE_KEEP_SEC
  lookback = (chicago_now().date() - timedelta(days=int(CACHE_KEEP_SEC / 86400) + 2)).isoformat()
  keep_after = (chicago_now().date() - timedelta(days=DAY_KEEP)).isoformat()
  old_days = {str(k): {"m": _f(v, "m"), "e": _f(v, "e")}
              for k, v in prev_days.items()
              if isinstance(v, dict) and keep_after <= str(k) < lookback}

  cache = _load_seg_cache()
  dirty_cache = False
  n_new = 0
  for name, q, sz, mt in _iter_qlogs(min_mt):
    if _skip_name(name, route, offroad, mt):
      continue
    if _cache_hit(cache, name, sz, mt) is not None:
      continue
    got = _read_qlog(q)
    if got is None:
      continue
    t0, meters, eng, streak = got
    cache[name] = {
      "sz": int(sz), "mt": float(mt), "t0": float(t0),
      "m": float(meters), "e": float(eng), "s": float(streak),
    }
    dirty_cache = True
    n_new += 1
  if dirty_cache:
    try:
      _save_seg_cache(cache)
    except Exception:
      pass

  days: dict = {}
  months: dict = {}
  folded: list[str] = []
  life_m = life_e = 0.0
  max_s = _f(st, "max_streak_m")
  for name, hit in cache.items():
    if not isinstance(hit, dict):
      continue
    mt = float(hit.get("mt") or 0)
    if _skip_name(name, route, offroad, mt):
      continue
    t0, meters, eng, streak = _seg_tuple(hit)
    if t0 < 1e9 or meters <= 0:
      continue
    key = datetime.fromtimestamp(t0, TZ).date().isoformat()
    if key < keep_after:
      continue
    b = _day_bucket(days, key)
    b["m"] = _f(b, "m") + meters
    b["e"] = _f(b, "e") + eng
    mb = _day_bucket(months, key[:7])
    mb["m"] = _f(mb, "m") + meters
    mb["e"] = _f(mb, "e") + eng
    life_m += meters
    life_e += eng
    if streak > max_s:
      max_s = streak
    folded.append(name)

  # Days older than the segment cache, not already rebuilt above.
  for k, v in old_days.items():
    if k in days:
      continue
    days[k] = v
    life_m += _f(v, "m")
    life_e += _f(v, "e")

  # Partial cache after an update must not shrink existing buckets or lifetime.
  _merge_buckets(days, prev_days)
  _merge_buckets(months, prev_months)
  life_m = max(life_m, prev_life_m, sum(_f(v, "m") for v in days.values()))
  life_e = max(life_e, prev_life_e, sum(_f(v, "e") for v in days.values()))

  live = _normalize_live(st.get("live"))
  if offroad:
    live = empty_live()

  st = {
    "v": STATS_VER,
    "days": days,
    "months": months,
    "folded": folded[-8000:],
    "life_m": life_m,
    "life_e": life_e,
    "max_streak_m": max_s,
    "max_day_streak": int(st.get("max_day_streak") or 0),
    "live": live,
  }
  _remember_streak(st, days)
  save_stats(st)
  from openpilot.common.swaglog import cloudlog
  cloudlog.info(f"trip_stats rebuilt segs={len(folded)} new={n_new} days={len(days)} life_m={life_m:.1f}")


def _pct(eng: float, meters: float) -> int:
  return int(round(100.0 * eng / meters)) if meters > 1 else 0


def _week_dates() -> list[str]:
  sun = datetime.strptime(sunday_id(), "%Y-%m-%d").date()
  return [(sun + timedelta(days=i)).isoformat() for i in range(7)]


def _month_keys(n: int = 6) -> list[str]:
  now = chicago_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
  out = []
  for i in range(n - 1, -1, -1):
    y = now.year
    m = now.month - i
    while m <= 0:
      m += 12
      y -= 1
    out.append(f"{y:04d}-{m:02d}")
  return out


def stats_view(trip: dict | None = None) -> dict:
  """Home + stats widgets. Qlog days plus this-drive live overlay.

  `trip` is ignored. Kept so old call sites still compile.
  """
  st = load_stats()
  days = {str(k): {"m": _f(v, "m"), "e": _f(v, "e")}
          for k, v in (st.get("days") or {}).items() if isinstance(v, dict)}
  live = _normalize_live(st.get("live"))
  lm, le = _f(live, "m"), _f(live, "e")
  today = day_id()
  b = _day_bucket(days, today)
  today_m = _f(b, "m") + lm
  today_e = _f(b, "e") + le
  b["m"], b["e"] = today_m, today_e

  week_ids = _week_dates()
  week_days = []
  week_m = week_e = 0.0
  for key in week_ids:
    d = days.get(key) or {}
    m, e = _f(d, "m"), _f(d, "e")
    week_days.append({"id": key, "m": m, "e": e})
    week_m += m
    week_e += e

  life_m = max(_f(st, "life_m") + lm, sum(_f(d, "m") for d in days.values()))
  life_e = max(_f(st, "life_e") + le, sum(_f(d, "e") for d in days.values()))

  current, window = _streaks(days)
  streak_days = max(int(st.get("max_day_streak") or 0), current, window)

  months = []
  cur_month = chicago_now().strftime("%Y-%m")
  stored_months = st.get("months") or {}
  for mk in _month_keys(6):
    sm = stored_months.get(mk) if isinstance(stored_months.get(mk), dict) else {}
    from_days_m = sum(_f(d, "m") for k, d in days.items() if str(k).startswith(mk))
    from_days_e = sum(_f(d, "e") for k, d in days.items() if str(k).startswith(mk))
    if mk == cur_month:
      mm, ee = from_days_m, from_days_e
    else:
      mm, ee = max(_f(sm, "m"), from_days_m), max(_f(sm, "e"), from_days_e)
    months.append({"id": mk, "m": mm, "e": ee, "current": mk == cur_month})

  return {
    "pct": _pct(life_e, life_m),
    "week_pct": _pct(week_e, week_m),
    "today_pct": _pct(today_e, today_m),
    "streak_days": streak_days,
    "week_days": week_days,
    "months": months,
    "longest_m": max(_f(st, "max_streak_m"), _f(live, "streak_m")),
    "life_m": life_m,
    "life_e": life_e,
    "week_m": week_m,
    "week_e": week_e,
    "today_m": today_m,
    "today_e": today_e,
  }
