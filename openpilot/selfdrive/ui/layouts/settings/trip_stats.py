"""Lifetime engagement history. Fold parked. Live trip owns today."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from openpilot.selfdrive.ui.layouts.settings.trip_seed import (
  CACHE_KEEP_SEC, TZ, _f, _iter_qlogs, _load_seg_cache, _save_seg_cache,
  _cache_hit, _read_qlog, _seg_tuple, chicago_now, day_id, sunday_id, HOT_SEC,
)

STATS_PATH = Path("/data/trip_stats.json")
STATS_VER = 1
DAY_KEEP = 400
STATS_LOCK = Path("/data/trip_stats.lock")

_cache: dict | None = None
_cache_mt = -1.0


def empty_stats() -> dict:
  return {
    "v": STATS_VER, "days": {}, "months": {}, "folded": [],
    "life_m": 0.0, "life_e": 0.0, "max_streak_m": 0.0, "max_day_streak": 0,
  }


def load_stats() -> dict:
  global _cache, _cache_mt
  try:
    mt = STATS_PATH.stat().st_mtime
  except OSError:
    mt = 0.0
  if _cache is not None and mt == _cache_mt:
    return _cache
  st = empty_stats()
  try:
    raw = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    if int(raw.get("v", 0)) == STATS_VER and isinstance(raw.get("days"), dict):
      st.update(raw)
      if not isinstance(st.get("folded"), list):
        st["folded"] = []
      if not isinstance(st.get("days"), dict):
        st["days"] = {}
      if not isinstance(st.get("months"), dict):
        st["months"] = {}
      st["max_day_streak"] = int(st.get("max_day_streak") or 0)
  except Exception:
    pass
  _cache, _cache_mt = st, mt
  return st


def save_stats(st: dict) -> None:
  global _cache, _cache_mt
  tmp = str(STATS_PATH) + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(st, f)
  os.replace(tmp, STATS_PATH)
  try:
    _cache_mt = STATS_PATH.stat().st_mtime
  except OSError:
    _cache_mt = 0.0
  _cache = st


def _day_bucket(days: dict, key: str) -> dict:
  b = days.get(key)
  if not isinstance(b, dict):
    b = {"m": 0.0, "e": 0.0}
    days[key] = b
  return b


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


def _remember_streak(st: dict, days: dict) -> int:
  current, window = _streaks(days)
  st["max_day_streak"] = max(int(st.get("max_day_streak") or 0), current, window)
  return st["max_day_streak"]


def touch_live_stats(today_m: float, today_e: float, live_streak: float) -> None:
  try:
    st = load_stats()
    st["max_streak_m"] = max(_f(st, "max_streak_m"), float(live_streak or 0))
    save_stats(st)
  except Exception:
    pass


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


def _fold_stats_history() -> None:
  st = load_stats()
  folded = set(str(x) for x in (st.get("folded") or []))
  days: dict = dict(st.get("days") or {})
  months: dict = dict(st.get("months") or {})
  life_m, life_e = _f(st, "life_m"), _f(st, "life_e")
  max_s = _f(st, "max_streak_m")
  min_mt = chicago_now().timestamp() - CACHE_KEEP_SEC
  cache = _load_seg_cache()
  dirty_cache = False
  n_new = 0
  for name, q, sz, mt in _iter_qlogs(min_mt):
    if name in folded:
      continue
    if (time.time() - mt) < HOT_SEC:
      continue
    hit = _cache_hit(cache, name, sz, mt)
    if hit is None:
      got = _read_qlog(q)
      if got is None:
        continue
      t0, meters, eng, streak = got
      cache[name] = {"sz": int(sz), "mt": float(mt), "t0": float(t0), "m": float(meters), "e": float(eng), "s": float(streak)}
      dirty_cache = True
    else:
      t0, meters, eng, streak = _seg_tuple(hit)
    if t0 < 1e9 or meters <= 0:
      folded.add(name)
      continue
    key = datetime.fromtimestamp(t0, TZ).date().isoformat()
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
    folded.add(name)
    n_new += 1
  if dirty_cache:
    try:
      _save_seg_cache(cache)
    except Exception:
      pass
  keep_after = (chicago_now().date() - timedelta(days=DAY_KEEP)).isoformat()
  days = {k: v for k, v in days.items() if str(k) >= keep_after}
  keep_month = (chicago_now().replace(day=1) - timedelta(days=36 * 31)).strftime("%Y-%m")
  months = {k: v for k, v in months.items() if str(k) >= keep_month}
  st = {"v": STATS_VER, "days": days, "months": months, "folded": list(folded)[-8000:],
        "life_m": life_m, "life_e": life_e, "max_streak_m": max_s,
        "max_day_streak": int(st.get("max_day_streak") or 0)}
  _remember_streak(st, days)
  save_stats(st)
  try:
    from openpilot.selfdrive.ui.layouts.settings.trip_seed import write_seed_out
    view = stats_view()
    write_seed_out({"week_m": view["week_m"], "week_eng_m": view["week_e"],
                    "today_m": view["today_m"], "today_eng_m": view["today_e"],
                    "life_m": view["life_m"], "life_e": view["life_e"],
                    "max_streak_m": view["longest_m"], "week_id": sunday_id(),
                    "day_id": day_id(), "seed": "qlog"})
  except Exception:
    pass


def _pct(eng: float, meters: float) -> int:
  return int(round(100.0 * eng / meters)) if meters > 1 else 0


def _week_dates() -> list[str]:
  sun = datetime.strptime(sunday_id(), "%Y-%m-%d").date()
  return [(sun + timedelta(days=i)).isoformat() for i in range(7)]


def _month_keys(n: int = 6) -> list[str]:
  now = chicago_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
  out = []
  for i in range(n - 1, -1, -1):
    y, m = now.year, now.month - i
    while m <= 0:
      m += 12; y -= 1
    out.append(f"{y:04d}-{m:02d}")
  return out


def stats_view(trip: dict | None = None) -> dict:
  st = load_stats()
  trip = trip or {}
  days = {str(k): {"m": _f(v, "m"), "e": _f(v, "e")}
          for k, v in (st.get("days") or {}).items() if isinstance(v, dict)}
  today = day_id()
  tm, te = _f(trip, "today_m"), _f(trip, "today_eng_m")
  b = _day_bucket(days, today)
  folded_m, folded_e = _f(b, "m"), _f(b, "e")
  if tm > 1 and folded_m > tm * 1.2:
    folded_m = tm
  if te > 1 and folded_e > te * 1.2:
    folded_e = te
  b["m"] = max(folded_m, tm)
  b["e"] = max(folded_e, te)
  today_m, today_e = _f(b, "m"), _f(b, "e")
  week_ids = _week_dates()
  week_days = []
  week_m = week_e = 0.0
  for key in week_ids:
    d = days.get(key) or {}
    m, e = _f(d, "m"), _f(d, "e")
    week_days.append({"id": key, "m": m, "e": e})
    week_m += m
    week_e += e
  week_m = max(week_m, _f(trip, "week_m"))
  week_e = max(week_e, _f(trip, "week_eng_m"))
  life_m = max(_f(st, "life_m"), sum(_f(d, "m") for d in days.values()), week_m, _f(trip, "life_m"))
  life_e = max(_f(st, "life_e"), sum(_f(d, "e") for d in days.values()), week_e, _f(trip, "life_e"))
  current, window = _streaks(days)
  streak_days = max(int(st.get("max_day_streak") or 0), current, window, int(trip.get("max_day_streak") or 0))
  months = []
  cur_month = chicago_now().strftime("%Y-%m")
  stored_months = st.get("months") or {}
  for mk in _month_keys(6):
    sm = stored_months.get(mk) if isinstance(stored_months.get(mk), dict) else {}
    from_days_m = sum(_f(d, "m") for k, d in days.items() if str(k).startswith(mk))
    from_days_e = sum(_f(d, "e") for k, d in days.items() if str(k).startswith(mk))
    months.append({"id": mk, "m": max(_f(sm, "m"), from_days_m), "e": max(_f(sm, "e"), from_days_e), "current": mk == cur_month})
  return {"pct": _pct(life_e, life_m), "week_pct": _pct(week_e, week_m), "today_pct": _pct(today_e, today_m),
          "streak_days": streak_days, "week_days": week_days, "months": months,
          "longest_m": max(_f(st, "max_streak_m"), _f(trip, "max_streak_m")),
          "life_m": life_m, "life_e": life_e, "week_m": week_m, "week_e": week_e,
          "today_m": today_m, "today_e": today_e}


def apply_stats_to_trip(trip: dict) -> dict:
  v = stats_view(trip)
  trip["today_m"] = max(_f(trip, "today_m"), float(v["today_m"]))
  trip["today_eng_m"] = max(_f(trip, "today_eng_m"), float(v["today_e"]))
  trip["week_m"] = max(_f(trip, "week_m"), float(v["week_m"]))
  trip["week_eng_m"] = max(_f(trip, "week_eng_m"), float(v["week_e"]))
  trip["life_m"] = max(_f(trip, "life_m"), float(v["life_m"]))
  trip["life_e"] = max(_f(trip, "life_e"), float(v["life_e"]))
  trip["max_streak_m"] = max(_f(trip, "max_streak_m"), float(v["longest_m"]))
  trip["max_day_streak"] = max(int(trip.get("max_day_streak") or 0), int(v["streak_days"] or 0))
  if float(v["week_m"]) > 0:
    trip["week_id"] = sunday_id()
  if float(v["today_m"]) > 0:
    trip["day_id"] = day_id()
  return trip
