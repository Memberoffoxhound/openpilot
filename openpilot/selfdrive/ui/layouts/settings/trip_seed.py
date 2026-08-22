"""Rebuild Today/Week meters from onboard qlogs. /data survives overlay; this refills after install."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from openpilot.common.swaglog import cloudlog

DATA_DIR = Path("/data/media/0")
SEG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})--")
TZ = ZoneInfo("America/Chicago")
SKIP = {"clips", "screenshots"}


def _bounds():
  now = datetime.now(TZ)
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
  """Distance / engaged-distance for Chicago today and this week (Sunday start)."""
  try:
    from openpilot.tools.lib.logreader import LogReader
  except Exception:
    cloudlog.exception("trip_seed import")
    return None

  now, day0, week0 = _bounds()
  week_cut = week0.timestamp() - 12 * 3600  # UTC folder names can be a day early
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
      if wt < week0.timestamp() or wt > now.timestamp() + 60:
        continue
      dt = min(1.0, max(0.0, wt - last_t)) if last_t else 0.0
      last_t = wt
      which = msg.which()
      if which == "carState":
        v = max(0.0, float(msg.carState.vEgo))
      elif which == "selfdriveState":
        en = bool(msg.selfdriveState.enabled)
      else:
        continue
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
  cloudlog.info(f"trip_seed segs={n_seg} week_m={week_m:.1f} today_m={today_m:.1f}")
  return {
    "week_m": week_m,
    "week_eng_m": week_e,
    "today_m": today_m,
    "today_eng_m": today_e,
    "week_id": f"{week0.year:04d}-{week0.month:02d}-{week0.day:02d}",
    "day_id": f"{day0.year:04d}-{day0.month:02d}-{day0.day:02d}",
    "seed": "qlog",
  }
