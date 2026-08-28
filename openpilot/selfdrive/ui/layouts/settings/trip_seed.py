"""Today/Week trip totals. Qlogs backfill a missing week; they never zero live counters."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path("/data/media/0/realdata")
TZ = ZoneInfo("America/Chicago")
SKIP = {"boot", "clips", "screenshots"}
WEEK_KEYS = ("week_m", "week_eng_m", "week_eng_s", "week_tot_s")
DAY_KEYS = ("today_m", "today_eng_m")
TRIP_KEYS = WEEK_KEYS + DAY_KEYS + ("week_id", "day_id", "seed")


def empty_trip() -> dict:
  return {
    "trip_m": 0.0, "eng_m": 0.0, "eng_s": 0.0, "tot_s": 0.0,
    "last_m": 0.0, "last_eng_m": 0.0, "last_eng_s": 0.0, "last_tot_s": 0.0, "route": "",
    "week_m": 0.0, "week_eng_m": 0.0, "week_eng_s": 0.0, "week_tot_s": 0.0, "week_id": "",
    "today_m": 0.0, "today_eng_m": 0.0, "day_id": "", "seed": "",
  }


def _f(d: dict, k: str) -> float:
  try:
    return float(d.get(k) or 0)
  except (TypeError, ValueError):
    return 0.0


def _merge_period(out: dict, a: dict, b: dict, id_key: str, keys: tuple[str, ...], current_id: str) -> None:
  aid, bid = str(a.get(id_key) or ""), str(b.get(id_key) or "")
  if aid and aid == bid:
    out[id_key] = aid
    for k in keys:
      out[k] = max(_f(a, k), _f(b, k))
    return
  if bid == current_id and aid != current_id:
    src = b
  elif aid == current_id or not bid:
    src = a
  else:
    src = b
  out[id_key] = str(src.get(id_key) or "")
  for k in keys:
    out[k] = _f(src, k)


def merge_snapshots(a: dict | None, b: dict | None) -> dict:
  """Keep the higher same-period totals. Prefer the snapshot for the current Chicago day/week."""
  a = a or {}
  b = b or {}
  out = empty_trip()
  for k, v in a.items():
    out[k] = v
  for k, v in b.items():
    if k not in out or out[k] in ("", None, 0, 0.0):
      out[k] = v
  _merge_period(out, a, b, "week_id", WEEK_KEYS, sunday_id())
  _merge_period(out, a, b, "day_id", DAY_KEYS, day_id())
  return out


def apply_seed(trip: dict, seed: dict | None) -> dict:
  """Qlog rebuild is a floor for the current period. Never drop live miles."""
  if not seed:
    return trip
  return merge_snapshots(trip, seed)


def roll_ids(trip: dict) -> dict:
  """Zero Today at Chicago midnight, Week on Sunday. Does not touch a matching period."""
  wid, did = sunday_id(), day_id()
  if trip.get("week_id") != wid:
    for k in WEEK_KEYS:
      trip[k] = 0.0
    trip["week_id"] = wid
  if trip.get("day_id") != did:
    for k in DAY_KEYS:
      trip[k] = 0.0
    trip["day_id"] = did
  return trip


def chicago_now() -> datetime:
  return datetime.now(TZ)


def day_id(dt: datetime | None = None) -> str:
  return (dt or chicago_now()).date().isoformat()


def sunday_id(dt: datetime | None = None) -> str:
  now = dt or chicago_now()
  sun = now - timedelta(days=(now.weekday() + 1) % 7)
  return sun.date().isoformat()


def _bounds() -> tuple[datetime, datetime, datetime]:
  now = chicago_now()
  day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
  sun = now - timedelta(days=(now.weekday() + 1) % 7)
  week0 = sun.replace(hour=0, minute=0, second=0, microsecond=0)
  return now, day0, week0


def _qlog(seg: Path) -> Path | None:
  for name in ("qlog", "qlog.zst", "qlog.bz2"):
    p = seg / name
    if p.is_file() and p.stat().st_size > 64:
      return p
  return None


def seed_week_today() -> dict | None:
  from openpilot.common.swaglog import cloudlog
  try:
    from openpilot.tools.lib.logreader import LogReader
  except Exception:
    cloudlog.exception("trip_seed import")
    return None

  now, day0, week0 = _bounds()
  week0_ts, day0_ts, now_ts = week0.timestamp(), day0.timestamp(), now.timestamp()
  week_m = week_e = today_m = today_e = 0.0
  n_seg = 0
  try:
    entries = list(os.scandir(DATA_DIR))
  except OSError:
    return None

  for ent in entries:
    if not ent.is_dir(follow_symlinks=False) or ent.name in SKIP:
      continue
    try:
      if ent.stat().st_mtime < week0_ts - 2 * 86400:
        continue
    except OSError:
      continue
    q = _qlog(Path(ent.path))
    if q is None:
      continue
    try:
      lr = LogReader(str(q))
    except Exception:
      continue
    origin_wall = origin_mono = None
    last_mono = None
    v = 0.0
    en = False
    used = False
    for msg in lr:
      which = msg.which()
      mono = msg.logMonoTime / 1e9
      if origin_wall is None:
        wt = 0.0
        if which == "initData":
          try:
            wt = float(msg.initData.wallTimeNanos) / 1e9
          except Exception:
            wt = 0.0
        elif which == "clocks":
          try:
            wt = float(msg.clocks.wallTimeNanos) / 1e9
          except Exception:
            wt = 0.0
        if wt > 1e9:
          origin_wall, origin_mono = wt, mono
        continue
      wall = origin_wall + (mono - origin_mono)
      if wall < week0_ts:
        last_mono = mono
        continue
      if wall > now_ts + 120:
        break
      if which == "carState":
        v = max(0.0, float(msg.carState.vEgo))
      elif which == "selfdriveState":
        en = bool(msg.selfdriveState.enabled)
      else:
        last_mono = mono if last_mono is None else last_mono
        continue
      dt = 0.0 if last_mono is None else min(1.0, max(0.0, mono - last_mono))
      last_mono = mono
      if dt <= 0 or v <= 0.15:
        continue
      d = v * dt
      week_m += d
      if en:
        week_e += d
      if wall >= day0_ts:
        today_m += d
        if en:
          today_e += d
      used = True
    if used:
      n_seg += 1

  cloudlog.info(f"trip_seed segs={n_seg} week_m={week_m:.1f} today_m={today_m:.1f}")
  return {
    "week_m": week_m,
    "week_eng_m": week_e,
    "today_m": today_m,
    "today_eng_m": today_e,
    "week_id": sunday_id(now),
    "day_id": day_id(now),
    "seed": "qlog",
  }
