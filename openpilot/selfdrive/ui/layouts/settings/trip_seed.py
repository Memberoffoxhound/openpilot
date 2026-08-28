"""Today/Week trip totals.

/data/trip_meter.json + TripMeter param are the live cache. Boot does not
LogReader when week_id is already this Chicago Sunday.

Per-segment cache (/data/trip_seed_cache.json) is filled at the end of a
drive while parked, so a later reseed (install, missing json) is cheap.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path("/data/media/0/realdata")
CACHE_PATH = Path("/data/trip_seed_cache.json")
TZ = ZoneInfo("America/Chicago")
SKIP = {"boot", "clips", "screenshots"}
WEEK_KEYS = ("week_m", "week_eng_m", "week_eng_s", "week_tot_s")
DAY_KEYS = ("today_m", "today_eng_m")
CACHE_VER = 1
HOT_SEC = 120.0
CACHE_KEEP_SEC = 14 * 86400
SEED_OUT = Path("/data/trip_seed_out.json")
CACHE_LOCK = Path("/data/trip_cache.lock")


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


def week_cache_valid(trip: dict | None) -> bool:
  """True when the live JSON/param already holds this Chicago week. Do not LogReader."""
  return bool(trip) and str(trip.get("week_id") or "") == sunday_id()


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


def _load_seg_cache() -> dict:
  try:
    raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if int(raw.get("v", 0)) != CACHE_VER or not isinstance(raw.get("seg"), dict):
      return {}
    return raw["seg"]
  except Exception:
    return {}


def _save_seg_cache(seg: dict) -> None:
  keep_after = time.time() - CACHE_KEEP_SEC
  pruned = {k: v for k, v in seg.items()
            if isinstance(v, dict) and float(v.get("mt") or 0) >= keep_after}
  tmp = str(CACHE_PATH) + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"v": CACHE_VER, "seg": pruned}, f)
  os.replace(tmp, CACHE_PATH)


def _cache_hit(cache: dict, name: str, sz: int, mt: float) -> dict | None:
  e = cache.get(name)
  if not isinstance(e, dict):
    return None
  try:
    if int(e.get("sz", -1)) != sz:
      return None
    if abs(float(e.get("mt", 0)) - mt) > 1.5:
      return None
    return e
  except (TypeError, ValueError):
    return None


def _iter_qlogs(min_mtime: float):
  try:
    entries = list(os.scandir(DATA_DIR))
  except OSError:
    return
  for ent in entries:
    if not ent.is_dir(follow_symlinks=False) or ent.name in SKIP:
      continue
    try:
      if ent.stat().st_mtime < min_mtime:
        continue
    except OSError:
      continue
    q = _qlog(Path(ent.path))
    if q is None:
      continue
    try:
      st = q.stat()
    except OSError:
      continue
    yield ent.name, q, st.st_size, st.st_mtime


def _read_qlog(path: Path) -> tuple[float, float, float] | None:
  """(wall_start, meters, engaged_meters) for the whole file, or None."""
  try:
    from openpilot.tools.lib.logreader import LogReader
    lr = LogReader(str(path))
  except Exception:
    return None
  origin_wall = None
  last_mono = None
  v = 0.0
  en = False
  meters = eng = 0.0
  n = 0
  for msg in lr:
    n += 1
    if n % 400 == 0:
      time.sleep(0)
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
        origin_wall = wt
      continue
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
    meters += d
    if en:
      eng += d
  if origin_wall is None:
    return None
  return origin_wall, meters, eng


def _fill_seg_cache() -> int:
  """LogReader finished qlogs that are not already cached. Returns new entries."""
  _, _, week0 = _bounds()
  min_mt = week0.timestamp() - 2 * 86400
  cache = _load_seg_cache()
  wrote = 0
  dirty = False
  for name, q, sz, mt in _iter_qlogs(min_mt):
    if (time.time() - mt) < HOT_SEC:
      continue
    if _cache_hit(cache, name, sz, mt) is not None:
      continue
    got = _read_qlog(q)
    time.sleep(0.01)
    if got is None:
      continue
    t0, meters, eng = got
    cache[name] = {"sz": int(sz), "mt": float(mt), "t0": float(t0), "m": float(meters), "e": float(eng)}
    wrote += 1
    dirty = True
    if wrote % 8 == 0:
      _save_seg_cache(cache)
      dirty = False
  if dirty or wrote:
    _save_seg_cache(cache)
  return wrote


def cache_segments_idle() -> None:
  """Parked, after a drive. Fill the segment cache. Does not touch trip_meter.json."""
  try:
    fd = os.open(CACHE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
  except FileExistsError:
    return
  try:
    n = _fill_seg_cache()
    time.sleep(45.0)
    n += _fill_seg_cache()
    from openpilot.common.swaglog import cloudlog
    cloudlog.info(f"trip_cache wrote={n}")
  except Exception:
    from openpilot.common.swaglog import cloudlog
    cloudlog.exception("trip cache")
  finally:
    try:
      CACHE_LOCK.unlink()
    except FileNotFoundError:
      pass


def write_seed_out(seed: dict | None) -> None:
  blob = seed or {}
  tmp = str(SEED_OUT) + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(blob, f)
  os.replace(tmp, SEED_OUT)


def seed_week_today() -> dict | None:
  from openpilot.common.swaglog import cloudlog
  now, day0, week0 = _bounds()
  week0_ts, day0_ts = week0.timestamp(), day0.timestamp()
  week_m = week_e = today_m = today_e = 0.0
  n_seg = n_hit = 0
  cache = _load_seg_cache()
  dirty = False
  try:
    for name, q, sz, mt in _iter_qlogs(week0_ts - 2 * 86400):
      hot = (time.time() - mt) < HOT_SEC
      hit = None if hot else _cache_hit(cache, name, sz, mt)
      if hit is not None:
        t0, meters, eng = float(hit.get("t0") or 0), float(hit.get("m") or 0), float(hit.get("e") or 0)
        n_hit += 1
      else:
        got = _read_qlog(q)
        time.sleep(0)
        if got is None:
          continue
        t0, meters, eng = got
        if not hot:
          cache[name] = {"sz": int(sz), "mt": float(mt), "t0": float(t0), "m": float(meters), "e": float(eng)}
          dirty = True
      if t0 < week0_ts or meters <= 0:
        continue
      week_m += meters
      week_e += eng
      if t0 >= day0_ts:
        today_m += meters
        today_e += eng
      n_seg += 1
  finally:
    if dirty:
      try:
        _save_seg_cache(cache)
      except Exception:
        pass

  cloudlog.info(f"trip_seed segs={n_seg} cache_hits={n_hit} week_m={week_m:.1f} today_m={today_m:.1f}")
  return {
    "week_m": week_m,
    "week_eng_m": week_e,
    "today_m": today_m,
    "today_eng_m": today_e,
    "week_id": sunday_id(now),
    "day_id": day_id(now),
    "seed": "qlog",
  }


if __name__ == "__main__":
  import sys
  kind = sys.argv[1] if len(sys.argv) > 1 else "cache"
  if kind == "seed":
    write_seed_out(seed_week_today())
  else:
    cache_segments_idle()
