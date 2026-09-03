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
STATS_LOOKBACK_SEC = 3 * 86400
CACHE_LOCK = Path("/data/trip_cache.lock")
# Empty leftover files (old O_EXCL locks) or a dead pid must not block forever.
LOCK_STALE_CACHE_SEC = 2 * 3600
LOCK_STALE_STATS_SEC = 10 * 60


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


def _offroad() -> bool:
  try:
    from openpilot.common.params import Params
    return bool(Params().get_bool("IsOffroad"))
  except Exception:
    return True


def _pid_alive(pid: int) -> bool:
  if pid <= 0:
    return False
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  except OSError:
    return False
  return True


def _lock_stale(path: Path, stale_sec: float) -> bool:
  try:
    age = time.time() - path.stat().st_mtime
  except OSError:
    return True
  pid = None
  try:
    raw = path.read_text(encoding="utf-8").strip().split()
    if raw:
      pid = int(raw[0])
  except (OSError, ValueError):
    pid = None
  if pid is not None:
    if not _pid_alive(pid):
      return True
    return age > stale_sec
  # Old empty O_EXCL lock: no owner to check.
  return age > min(stale_sec, 120.0)


def acquire_file_lock(path: Path, stale_sec: float) -> bool:
  """Exclusive lock. Steals the file if the owner pid is dead or the lock is old."""
  payload = f"{os.getpid()} {time.time():.0f}\n".encode()

  def _create() -> bool:
    try:
      fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
      return False
    try:
      os.write(fd, payload)
    finally:
      os.close(fd)
    return True

  if _create():
    return True
  if not _lock_stale(path, stale_sec):
    return False
  try:
    path.unlink()
  except FileNotFoundError:
    pass
  except OSError:
    return False
  return _create()


def release_file_lock(path: Path) -> None:
  try:
    raw = path.read_text(encoding="utf-8").strip().split()
    if raw and int(raw[0]) != os.getpid():
      return
  except (OSError, ValueError):
    pass
  try:
    path.unlink()
  except FileNotFoundError:
    pass
  except OSError:
    pass


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
      time.sleep(0.002)
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
    time.sleep(0.05)
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


def _fold() -> None:
  from openpilot.selfdrive.ui.layouts.settings.trip_stats import fold_stats_history
  fold_stats_history()


def _with_cache_lock() -> bool:
  return acquire_file_lock(CACHE_LOCK, LOCK_STALE_CACHE_SEC)


def _unlock() -> None:
  release_file_lock(CACHE_LOCK)


def cache_segments_idle() -> None:
  """Parked, after a drive. Commit overlays first so a short park still lands miles."""
  if not _with_cache_lock():
    # Another fill is alive. Still fold so Today is not waiting on LogReader.
    try:
      _fold()
    except Exception:
      from openpilot.common.swaglog import cloudlog
      cloudlog.exception("trip cache fold-only")
    return
  try:
    # Fold before any LogReader work so live/pending land in days[] even if
    # the car cuts power before hot qlogs are readable.
    _fold()
    n = _fill_seg_cache(lookback_sec=STATS_LOOKBACK_SEC)
    _fold()
    from openpilot.common.swaglog import cloudlog
    cloudlog.info(f"trip_cache wrote={n}")
  except Exception:
    from openpilot.common.swaglog import cloudlog
    cloudlog.exception("trip cache")
  finally:
    _unlock()


def _rebuild() -> None:
  """Statistics / boot. Fold first, recent qlogs, then the long scan only if parked."""
  from openpilot.common.swaglog import cloudlog
  if not _with_cache_lock():
    # Park cache already reading qlogs. Fold whatever is on disk.
    try:
      _fold()
    except Exception:
      cloudlog.exception("trip rebuild fold-only")
    return
  try:
    _fold()
    n = _fill_seg_cache(lookback_sec=STATS_LOOKBACK_SEC)
    _fold()
    if _offroad():
      n += _fill_seg_cache(lookback_sec=CACHE_KEEP_SEC)
      _fold()
    cloudlog.info(f"trip_rebuild wrote={n} offroad={_offroad()}")
  except Exception:
    cloudlog.exception("trip rebuild")
  finally:
    _unlock()


if __name__ == "__main__":
  import sys
  try:
    os.nice(15)
  except OSError:
    pass
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
