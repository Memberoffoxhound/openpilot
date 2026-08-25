"""Rebuild Today/Week from onboard qlogs. Survives reboot, overlay, reinstall."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from openpilot.common.swaglog import cloudlog

DATA_DIR = Path("/data/media/0/realdata")
TZ = ZoneInfo("America/Chicago")
SKIP = {"boot", "clips", "screenshots"}


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
