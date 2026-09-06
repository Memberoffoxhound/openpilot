"""Park/boot fold helpers for trip_stats."""
from __future__ import annotations

from datetime import datetime, timedelta

from openpilot.selfdrive.ui.layouts.settings.trip_seed import (
  CACHE_KEEP_SEC, TZ, _f, _iter_qlogs, _load_seg_cache, _save_seg_cache,
  _cache_hit, _read_qlog, _seg_tuple, chicago_now, day_id, engaged_pct, sunday_id,
)
from openpilot.selfdrive.ui.layouts.settings.trip_overlay import (
  empty_live, empty_pending, normalize_live, normalize_pending,
  overlay_day, day_bucket, commit_overlay,
)


def run_fold(load_stats, save_stats, is_offroad, current_route, skip_name,
             merge_buckets, streaks, stats_ver, day_keep) -> None:
  st = load_stats()
  prev_life_m, prev_life_e = _f(st, "life_m"), _f(st, "life_e")
  prev_days = st.get("days") or {}
  prev_months = st.get("months") or {}
  offroad = is_offroad()
  route = current_route()
  today = day_id()
  prev_today_m = _f(prev_days.get(today) or {}, "m")
  prev_today_e = _f(prev_days.get(today) or {}, "e")
  prev_live = normalize_live(st.get("live"))
  prev_pending = normalize_pending(st.get("pending"))
  min_mt = chicago_now().timestamp() - CACHE_KEEP_SEC
  lookback = (chicago_now().date() - timedelta(days=int(CACHE_KEEP_SEC / 86400) + 2)).isoformat()
  keep_after = (chicago_now().date() - timedelta(days=day_keep)).isoformat()
  old_days = {str(k): {"m": _f(v, "m"), "e": _f(v, "e")}
              for k, v in prev_days.items()
              if isinstance(v, dict) and keep_after <= str(k) < lookback}

  cache = _load_seg_cache()
  dirty_cache = False
  n_new = 0
  for name, q, sz, mt in _iter_qlogs(min_mt):
    if skip_name(name, route, offroad, mt) or _cache_hit(cache, name, sz, mt) is not None:
      continue
    got = _read_qlog(q)
    if got is None:
      continue
    t0, meters, eng, streak = got
    cache[name] = {"sz": int(sz), "mt": float(mt), "t0": float(t0),
                   "m": float(meters), "e": float(eng), "s": float(streak)}
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
    if skip_name(name, route, offroad, mt):
      continue
    t0, meters, eng, streak = _seg_tuple(hit)
    if t0 < 1e9 or meters <= 0:
      continue
    key = datetime.fromtimestamp(t0, TZ).date().isoformat()
    if key < keep_after:
      continue
    b = day_bucket(days, key)
    b["m"] = _f(b, "m") + meters
    b["e"] = _f(b, "e") + eng
    mb = day_bucket(months, key[:7])
    mb["m"] = _f(mb, "m") + meters
    mb["e"] = _f(mb, "e") + eng
    life_m += meters
    life_e += eng
    max_s = max(max_s, streak)
    folded.append(name)

  for k, v in old_days.items():
    if k not in days:
      days[k] = v
      life_m += _f(v, "m")
      life_e += _f(v, "e")

  merge_buckets(days, prev_days)
  merge_buckets(months, prev_months)
  life_m = max(life_m, prev_life_m, sum(_f(v, "m") for v in days.values()))
  life_e = max(life_e, prev_life_e, sum(_f(v, "e") for v in days.values()))

  live = prev_live
  pday = overlay_day(str(prev_pending.get("day") or ""), today, False)
  lday = overlay_day(str(live.get("day") or ""), today, not offroad)
  add_m = add_e = 0.0
  if pday != today:
    am, ae = commit_overlay(days, months, prev_days, pday,
                            _f(prev_pending, "m"), _f(prev_pending, "e"))
    add_m += am
    add_e += ae

  held_m, held_e = prev_today_m, prev_today_e
  if str(prev_pending.get("day") or "") == today:
    held_m += _f(prev_pending, "m")
    held_e += _f(prev_pending, "e")

  if offroad:
    if lday == today:
      held_m += _f(live, "m")
      held_e += _f(live, "e")
    else:
      am, ae = commit_overlay(days, months, prev_days, lday, _f(live, "m"), _f(live, "e"))
      add_m += am
      add_e += ae
    live = empty_live()

  leftover_m = max(0.0, held_m - _f(days.get(today) or {}, "m"))
  leftover_e = max(0.0, held_e - _f(days.get(today) or {}, "e"))
  if offroad:
    am, ae = commit_overlay(days, months, prev_days, today, leftover_m, leftover_e)
    add_m += am
    add_e += ae
    pending = empty_pending()
  else:
    pending = {"day": today if leftover_m or leftover_e else "",
               "m": leftover_m, "e": leftover_e}

  life_m = max(life_m + add_m, sum(_f(v, "m") for v in days.values()))
  life_e = max(life_e + add_e, sum(_f(v, "e") for v in days.values()))
  current, window = streaks(days)
  st = {
    "v": stats_ver, "days": days, "months": months, "folded": folded[-8000:],
    "life_m": life_m, "life_e": life_e, "max_streak_m": max_s,
    "max_day_streak": max(int(st.get("max_day_streak") or 0), current, window),
    "live": live, "pending": pending,
  }
  save_stats(st)
  from openpilot.common.swaglog import cloudlog
  cloudlog.info(
    f"trip_stats rebuilt segs={len(folded)} new={n_new} days={len(days)} "
    f"life_m={life_m:.1f} pending_m={pending['m']:.1f} offroad={offroad}"
  )


def run_view(st: dict, is_offroad, streaks) -> dict:
  days = {str(k): {"m": _f(v, "m"), "e": _f(v, "e")}
          for k, v in (st.get("days") or {}).items() if isinstance(v, dict)}
  live = normalize_live(st.get("live"))
  pending = normalize_pending(st.get("pending"))
  today = day_id()
  offroad = is_offroad()
  live_day = overlay_day(str(live.get("day") or ""), today, not offroad)
  pend_day = str(pending.get("day") or "")
  lm = _f(live, "m") if live_day == today else 0.0
  le = _f(live, "e") if live_day == today else 0.0
  pm = _f(pending, "m") if pend_day == today else 0.0
  pe = _f(pending, "e") if pend_day == today else 0.0
  b = day_bucket(days, today)
  today_m = _f(b, "m") + lm + pm
  today_e = _f(b, "e") + le + pe
  b["m"], b["e"] = today_m, today_e
  if pend_day and pend_day != today:
    pb = day_bucket(days, pend_day)
    pb["m"] += _f(pending, "m")
    pb["e"] += _f(pending, "e")
  if live_day != today and live_day:
    lb = day_bucket(days, live_day)
    lb["m"] += _f(live, "m")
    lb["e"] += _f(live, "e")

  sun = datetime.strptime(sunday_id(), "%Y-%m-%d").date()
  week_ids = [(sun + timedelta(days=i)).isoformat() for i in range(7)]
  week_days = []
  week_m = week_e = 0.0
  for key in week_ids:
    d = days.get(key) or {}
    m, e = _f(d, "m"), _f(d, "e")
    week_days.append({"id": key, "m": m, "e": e})
    week_m += m
    week_e += e

  life_m = max(_f(st, "life_m") + lm + pm, sum(_f(d, "m") for d in days.values()))
  life_e = max(_f(st, "life_e") + le + pe, sum(_f(d, "e") for d in days.values()))
  current, window = streaks(days)

  now = chicago_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
  month_keys = []
  for i in range(5, -1, -1):
    y, m = now.year, now.month - i
    while m <= 0:
      m += 12
      y -= 1
    month_keys.append(f"{y:04d}-{m:02d}")
  months = []
  cur_month = chicago_now().strftime("%Y-%m")
  stored_months = st.get("months") or {}
  for mk in month_keys:
    sm = stored_months.get(mk) if isinstance(stored_months.get(mk), dict) else {}
    from_days_m = sum(_f(d, "m") for k, d in days.items() if str(k).startswith(mk))
    from_days_e = sum(_f(d, "e") for k, d in days.items() if str(k).startswith(mk))
    if mk == cur_month:
      mm, ee = from_days_m, from_days_e
    else:
      mm, ee = max(_f(sm, "m"), from_days_m), max(_f(sm, "e"), from_days_e)
    months.append({"id": mk, "m": mm, "e": ee, "current": mk == cur_month})

  return {
    "pct": engaged_pct(life_e, life_m), "week_pct": engaged_pct(week_e, week_m),
    "today_pct": engaged_pct(today_e, today_m),
    "streak_days": max(int(st.get("max_day_streak") or 0), current, window),
    "week_days": week_days, "months": months,
    "longest_m": max(_f(st, "max_streak_m"), _f(live, "streak_m")),
    "life_m": life_m, "life_e": life_e, "week_m": week_m, "week_e": week_e,
    "today_m": today_m, "today_e": today_e,
  }
