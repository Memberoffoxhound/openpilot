"""Qlog reader for the one trip cache.

Segment cache: /data/trip_seed_cache.json. Fold in trip_stats.py
rebuilds days[] from this cache. Nothing here writes today/week.
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
CACHE_VER = 1
HOT_SEC = 120.0
CACHE_KEEP_SEC = 200 * 86400
CACHE_LOCK = Path("/data/trip_cache.lock")


def _f(d: dict, k: str) -> float:
  try:
    return float(d.get(k) or 0)
  except (TypeError, ValueError):
    return 0.0


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


def _read_qlog(path: Path) -> tuple[float, float, float, float] | None:
  """(wall_start, meters, engaged_meters, max_engaged_streak_m) or None."""
  try:
    from openpilot.tools.lib.logreader import LogReader
    lr = LogReader(str(path))
  except Exception:
    return None
  origin_wall = None
  last_mono = None
  v = 0.0
  en = False
  meters = eng = streak = cur = 0.0
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
      cur += d
      if cur > streak:
        streak = cur
    else:
      cur = 0.0
  if origin_wall is None:
    return None
  return origin_wall, meters, eng, streak


def _seg_tuple(hit: dict) -> tuple[float, float, float, float]:
  return (
    float(hit.get("t0") or 0),
    float(hit.get("m") or 0),
    float(hit.get("e") or 0),
    float(hit.get("s") or 0),
  )


def _fill_seg_cache(lookback_sec: float | None = None) -> int:
  """LogReader finished qlogs that are not already cached. Returns new entries."""
  if lookback_sec is None:
    _, _, week0 = _bounds()
    min_mt = week0.timestamp() - 2 * 86400
  else:
    min_mt = time.time() - lookback_sec
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
    t0, meters, eng, streak = got
    cache[name] = {
      "sz": int(sz), "mt": float(mt), "t0": float(t0),
      "m": float(meters), "e": float(eng), "s": float(streak),
    }
    wrote += 1
    dirty = True
    if wrote % 8 == 0:
      _save_seg_cache(cache)
      dirty = False
  if dirty or wrote:
    _save_seg_cache(cache)
  return wrote


def cache_segments_idle() -> None:
  """Parked, after a drive. Fill the qlog segment cache, then rebuild the one stats cache."""
  try:
    fd = os.open(CACHE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
  except FileExistsError:
    return
  try:
    n = _fill_seg_cache()
    time.sleep(45.0)
    n += _fill_seg_cache()
    n += _fill_seg_cache(lookback_sec=CACHE_KEEP_SEC)
    from openpilot.selfdrive.ui.layouts.settings.trip_stats import fold_stats_history
    fold_stats_history()
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


def _rebuild() -> None:
  _fill_seg_cache(lookback_sec=CACHE_KEEP_SEC)
  from openpilot.selfdrive.ui.layouts.settings.trip_stats import fold_stats_history
  fold_stats_history()


if __name__ == "__main__":
  import sys
  kind = sys.argv[1] if len(sys.argv) > 1 else "cache"
  try:
    if kind in ("seed", "stats"):
      _rebuild()
    else:
      cache_segments_idle()
  except Exception:
    from openpilot.common.swaglog import cloudlog
    cloudlog.exception("trip_seed main")
    raise
