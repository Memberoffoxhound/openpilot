"""Today/Week meters. Seed from onboard qlogs; tick from the UI thread."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state

DATA_DIR = Path("/data/media/0")
SEG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})--")
TZ = ZoneInfo("America/Chicago")
SKIP = {"clips", "screenshots"}
TRIP_PATH = "/data/trip_meter.json"
CACHE_KEEP_SEC = 200 * 86400
HOT_SEC = 120.0

_trip: dict | None = None
_trip_t = 0.0
_trip_flush = 0.0
_seed_started = False


def _day_id() -> str:
  now = datetime.now(TZ)
  return f"{now.year:04d}-{now.month:02d}-{now.day:02d}"


def _sunday_id() -> str:
  now = datetime.now(TZ)
  sun = now - timedelta(days=(now.weekday() + 1) % 7)
  return f"{sun.year:04d}-{sun.month:02d}-{sun.day:02d}"


def day_id() -> str:
  return _day_id()


def sunday_id() -> str:
  return _sunday_id()


def chicago_now() -> datetime:
  return datetime.now(TZ)


def _f(d: dict, k: str) -> float:
  try:
    return float(d.get(k) or 0)
  except (TypeError, ValueError):
    return 0.0


def _undouble(live: float, seed: float) -> float:
  live = float(live or 0)
  seed = float(seed or 0)
  if seed <= 0:
    return live
  if live <= 0:
    return seed
  hi, lo = (live, seed) if live >= seed else (seed, live)
  if lo > 50 and hi > lo * 1.55 and hi < lo * 2.55:
    return lo
  return max(live, seed)


def _iter_qlogs(min_mtime: float):
  return
  yield


def _load_seg_cache() -> dict:
  return {}


def _save_seg_cache(seg: dict) -> None:
  return


def _cache_hit(cache, name, sz, mt):
  return None


def _read_qlog(path: Path):
  return None


def _seg_tuple(hit: dict):
  return 0.0, 0.0, 0.0, 0.0


def _qlog(seg: Path) -> Path | None:
  for name in ("qlog", "qlog.zst", "qlog.bz2"):
    p = seg / name
    if p.is_file() and p.stat().st_size > 64:
      return p
  return None


def seed_week_today() -> dict | None:
  try:
    from openpilot.tools.lib.logreader import LogReader
  except Exception:
    cloudlog.exception("trip_seed import")
    return None

  now = datetime.now(TZ)
  day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
  sun = now - timedelta(days=(now.weekday() + 1) % 7)
  week0 = sun.replace(hour=0, minute=0, second=0, microsecond=0)
  week_cut = week0.timestamp() - 12 * 3600
  week_m = week_e = today_m = today_e = 0.0
  n_seg = 0
  try:
    entries = list(os.scandir(DATA_DIR))
  except OSError:
    return None

  for ent in entries:
    if not ent.is_dir(follow_symlinks=False) or ent.name in SKIP:
      continue
    m = SEG_RE.match(ent.name)
    if not m:
      continue
    try:
      folder_day = datetime.strptime(m.group(1), "%Y-%m-%d").timestamp()
    except ValueError:
      continue
    if folder_day < week_cut:
      continue
    q = _qlog(Path(ent.path))
    if q is None:
      continue
    try:
      lr = LogReader(str(q))
    except Exception:
      continue
    n_seg += 1
    last_t = 0.0
    v = 0.0
    en = False
    for msg in lr:
      try:
        wt = float(msg.wallTimeNanos) / 1e9
      except Exception:
        continue
      which = msg.which()
      if which == "carState":
        v = max(0.0, float(msg.carState.vEgo))
      elif which == "selfdriveState":
        en = bool(msg.selfdriveState.enabled)
        continue
      else:
        continue
      if wt < week0.timestamp() or wt > now.timestamp() + 60:
        continue
      dt = min(1.0, max(0.0, wt - last_t)) if last_t else 0.0
      last_t = wt
      if dt <= 0 or v <= 0.15:
        continue
      d = v * dt
      week_m += d
      if en:
        week_e += d
      if wt >= day0.timestamp():
        today_m += d
        if en:
          today_e += d

  if n_seg == 0 and week_m <= 0:
    return None
  return {
    "week_m": week_m,
    "week_eng_m": week_e,
    "today_m": today_m,
    "today_eng_m": today_e,
    "week_id": _sunday_id(),
    "day_id": _day_id(),
    "seed": "qlog",
  }


def _load_trip() -> dict:
  t = {"week_m": 0.0, "week_eng_m": 0.0, "week_id": "",
       "today_m": 0.0, "today_eng_m": 0.0, "day_id": ""}
  try:
    t.update(json.loads(open(TRIP_PATH, encoding="utf-8").read()))
  except Exception:
    pass
  return t


def _save_trip(t: dict) -> None:
  tmp = TRIP_PATH + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(t, f)
  os.replace(tmp, TRIP_PATH)


def _run_seed() -> None:
  global _trip
  try:
    s = seed_week_today()
  except Exception:
    cloudlog.exception("trip seed")
    return
  if not s or _trip is None:
    return
  _trip["week_m"] = _undouble(float(_trip.get("week_m") or 0), float(s["week_m"]))
  _trip["week_eng_m"] = _undouble(float(_trip.get("week_eng_m") or 0), float(s["week_eng_m"]))
  _trip["today_m"] = _undouble(float(_trip.get("today_m") or 0), float(s["today_m"]))
  _trip["today_eng_m"] = _undouble(float(_trip.get("today_eng_m") or 0), float(s["today_eng_m"]))
  _trip["week_id"] = s["week_id"]
  _trip["day_id"] = s["day_id"]
  try:
    _save_trip(_trip)
  except Exception:
    pass


def trip_snapshot() -> dict:
  if _trip is not None:
    return dict(_trip)
  return _load_trip()


def tick_trip() -> None:
  global _trip, _trip_t, _trip_flush, _seed_started
  now = time.monotonic()
  if _trip is None:
    _trip = _load_trip()
    _trip_t = now
    if not _seed_started:
      _seed_started = True
      threading.Thread(target=_run_seed, daemon=True).start()
  dt = min(1.0, max(0.0, now - _trip_t))
  _trip_t = now
  day, week = _day_id(), _sunday_id()
  if _trip.get("day_id") != day:
    _trip["today_m"] = _trip["today_eng_m"] = 0.0
    _trip["day_id"] = day
  if _trip.get("week_id") != week:
    _trip["week_m"] = _trip["week_eng_m"] = 0.0
    _trip["week_id"] = week
  try:
    offroad = ui_state.params.get_bool("IsOffroad")
    cs_ok = ui_state.sm.recv_frame["carState"] > 0
  except Exception:
    offroad, cs_ok = True, False
  if (not offroad) and cs_ok:
    v = max(0.0, float(ui_state.sm["carState"].vEgo))
    if v > 0.15:
      _trip["week_m"] += v * dt
      _trip["today_m"] += v * dt
      try:
        if ui_state.sm.recv_frame["selfdriveState"] > 0 and ui_state.sm["selfdriveState"].enabled:
          _trip["week_eng_m"] += v * dt
          _trip["today_eng_m"] += v * dt
      except Exception:
        pass
  if now - _trip_flush > 1.0:
    _save_trip(_trip)
    _trip_flush = now
