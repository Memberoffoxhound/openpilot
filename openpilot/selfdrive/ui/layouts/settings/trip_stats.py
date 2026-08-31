"""Lifetime engagement history.

Live trip owns today and this week. Folded days[] is history. Never add
live miles into a day bucket that fold also fills from qlogs.
"""
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
STATS_VER = 2
DAY_KEEP = 400
STATS_LOCK = Path("/data/trip_stats.lock")

_cache: dict | None = None
_cache_mt = -1.0


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
  }


def _undouble(a: float, b: float) -> float:
  a = float(a or 0)
  b = float(b or 0)
  if a <= 0:
    return b
  if b <= 0:
    return a
  hi, lo = (a, b) if a >= b else (b, a)
  if lo > 50 and hi > lo * 1.55 and hi < lo * 2.55:
    return lo
  return hi


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
    if isinstance(raw.get("days"), dict):
      st.update(raw)
      if not isinstance(st.get("folded"), list):
        st["folded"] = []
      if not isinstance(st.get("days"), dict):
        st["days"] = {}
      if not isinstance(st.get("months"), dict):
        st["months"] = {}
      st["max_day_streak"] = int(st.get("max_day_streak") or 0)
      st["v"] = STATS_VER
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
  days: dict = {}
  months: dict = {}
  today = day_id()
  cur_month = chicago_now().strftime("%Y-%m")
  for k, v in (st.get("days") or {}).items():
    if isinstance(v, dict) and str(k) != today:
      days[str(k)] = {"m": _f(v, "m"), "e": _f(v, "e")}
  for k, v in (st.get("months") or {}).items():
    if isinstance(v, dict) and str(k) != cur_month:
      months[str(k)] = {"m": _f(v, "m"), "e": _f(v, "e")}
  life_m = sum(_f(v, "m") for v in days.values())
  life_e = sum(_f(v, "e") for v in days.values())
  max_s = _f(st, "max_streak_m")
  min_mt = chicago_now().timestamp() - CACHE_KEEP_SEC
  cache = _load_seg_cache()
  dirty_cache = False
  n_new = 0
  for name, q, sz, mt in _iter_qlogs(min_mt):
    if (time.time() - mt) < HOT_SEC:
      continue
    hit = _cache_hit(cache, name, sz, mt)
    if hit is None:
      got = _read_qlog(q)
      if got is None:
        continue
      t0, meters, eng, streak = got
      cache[name] = {
        "sz": int(sz), "mt": float(mt), "t0": float(t0),
        "m": float(meters), "e": float(eng), "s": float(streak),
      }
      dirty_cache = True
    else:
      t0, meters, eng, streak = _seg_tuple(hit)
    if t0 < 1e9 or meters <= 0:
      folded.add(name)
      continue
    key = datetime.fromtimestamp(t0, TZ).date().isoformat()
    b = _day_bucket(days, key)
    if name not in folded:
      b["m"] = _f(b, "m") + meters
      b["e"] = _f(b, "e") + eng
      mb = _day_bucket(months, key[:7])
      mb["m"] = _f(mb, "m") + meters
      mb["e"] = _f(mb, "e") + eng
      life_m += meters
      life_e += eng
      n_new += 1
    if streak > max_s:
      max_s = streak
    folded.add(name)
  if dirty_cache:
    try:
      _save_seg_cache(cache)
    except Exception:
      pass
  keep_after = (chicago_now().date() - timedelta(days=DAY_KEEP)).isoformat()
  days = {k: v for k, v in days.items() if str(k) >= keep_after}
  keep_month = (chicago_now().replace(day=1) - timedelta(days=36 * 31)).strftime("%Y-%m")
  months = {k: v for k, v in months.items() if str(k) >= keep_month}
  st = {
    "v": STATS_VER,
    "days": days,
    "months": months,
    "folded": list(folded)[-8000:],
    "life_m": life_m,
    "life_e": life_e,
    "max_streak_m": max_s,
    "max_day_streak": int(st.get("max_day_streak") or 0),
  }
  _remember_streak(st, days)
  save_stats(st)
  from openpilot.common.swaglog import cloudlog
  cloudlog.info(f"trip_stats folded={n_new} days={len(days)} life_m={life_m:.1f}")


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
  st = load_stats()
  trip = trip or {}
  days = {str(k): {"m": _f(v, "m"), "e": _f(v, "e")}
          for k, v in (st.get("days") or {}).items() if isinstance(v, dict)}
  today = day_id()
  tm, te = _f(trip, "today_m"), _f(trip, "today_eng_m")
  b = _day_bucket(days, today)
  folded_m, folded_e = _f(b, "m"), _f(b, "e")
  if tm > 1:
    b["m"] = tm
    b["e"] = te
  else:
    b["m"], b["e"] = folded_m, folded_e
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
  tw, tew = _f(trip, "week_m"), _f(trip, "week_eng_m")
  if tw > 1:
    week_m = tw
  if tew > 1:
    week_e = tew

  life_m = max(_f(st, "life_m"), sum(_f(d, "m") for d in days.values()), week_m, _f(trip, "life_m"))
  life_e = max(_f(st, "life_e"), sum(_f(d, "e") for d in days.values()), week_e, _f(trip, "life_e"))

  current, window = _streaks(days)
  streak_days = max(int(st.get("max_day_streak") or 0), current, window,
                    int(trip.get("max_day_streak") or 0))

  months = []
  cur_month = chicago_now().strftime("%Y-%m")
  stored_months = st.get("months") or {}
  for mk in _month_keys(6):
    sm = stored_months.get(mk) if isinstance(stored_months.get(mk), dict) else {}
    from_days_m = sum(_f(d, "m") for k, d in days.items() if str(k).startswith(mk))
    from_days_e = sum(_f(d, "e") for k, d in days.items() if str(k).startswith(mk))
    months.append({"id": mk, "m": max(_f(sm, "m"), from_days_m),
                   "e": max(_f(sm, "e"), from_days_e), "current": mk == cur_month})

  return {
    "pct": _pct(life_e, life_m),
    "week_pct": _pct(week_e, week_m),
    "today_pct": _pct(today_e, today_m),
    "streak_days": streak_days,
    "week_days": week_days,
    "months": months,
    "longest_m": max(_f(st, "max_streak_m"), _f(trip, "max_streak_m")),
    "life_m": life_m,
    "life_e": life_e,
    "week_m": week_m,
    "week_e": week_e,
    "today_m": today_m,
    "today_e": today_e,
  }


def apply_stats_to_trip(trip: dict) -> dict:
  """Lifetime / streak only. Do not copy today/week into trip_meter."""
  v = stats_view(trip)
  trip["life_m"] = max(_f(trip, "life_m"), float(v["life_m"]))
  trip["life_e"] = max(_f(trip, "life_e"), float(v["life_e"]))
  trip["max_streak_m"] = max(_f(trip, "max_streak_m"), float(v["longest_m"]))
  trip["max_day_streak"] = max(int(trip.get("max_day_streak") or 0), int(v["streak_days"] or 0))
  tm = _f(trip, "today_m")
  folded_today = _f((load_stats().get("days") or {}).get(day_id()) or {}, "m")
  if tm > 50 and folded_today > 50 and tm > folded_today * 1.55 and tm < folded_today * 2.55:
    trip["today_m"] = folded_today
    te = _f(trip, "today_eng_m")
    folded_e = _f((load_stats().get("days") or {}).get(day_id()) or {}, "e")
    if te > folded_e * 1.55:
      trip["today_eng_m"] = folded_e
  wm = _f(trip, "week_m")
  if wm > 50:
    fixed_w = float(v["week_m"])
    if wm > fixed_w * 1.55 and wm < fixed_w * 2.55:
      trip["week_m"] = fixed_w
  if not str(trip.get("week_id") or ""):
    trip["week_id"] = sunday_id()
  if not str(trip.get("day_id") or ""):
    trip["day_id"] = day_id()
  return trip
