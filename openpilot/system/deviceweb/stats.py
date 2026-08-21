"""Drive reports from local qlogs. Offroad parse, cache on disk."""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

from openpilot.common.swaglog import cloudlog

DATA_DIR = Path("/data/media/0")
CACHE_DIR = DATA_DIR / "stats"
SEG_RE = re.compile(
  r"^(?:(?P<dongle>[0-9a-fA-F]{16})[|_])?(?P<time>\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})(?:--(?P<seg>\d+))?$"
)
MAX_POINTS = 2200
MAX_RANGE_DAYS = 31

_lock = threading.Lock()
_job: dict = {"state": "idle", "error": "", "from": "", "to": "", "result": None}
_thread: threading.Thread | None = None


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
  r = 6371000.0
  p1, p2 = math.radians(a[0]), math.radians(b[0])
  dphi = math.radians(b[0] - a[0])
  dl = math.radians(b[1] - a[1])
  h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
  return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _valid_day(s: str) -> str | None:
  try:
    datetime.strptime(s, "%Y-%m-%d")
    return s
  except ValueError:
    return None


def _qlogs_in_range(start: str, end: str) -> list[tuple[str, Path]]:
  if not DATA_DIR.is_dir():
    return []
  out: list[tuple[str, Path]] = []
  try:
    entries = list(os.scandir(DATA_DIR))
  except OSError:
    return []
  for ent in entries:
    m = SEG_RE.match(ent.name)
    if not m or not ent.is_dir(follow_symlinks=False):
      continue
    day = m.group("time")[:10]
    if day < start or day > end:
      continue
    qlog = None
    try:
      for f in os.scandir(ent.path):
        if f.name.startswith("qlog"):
          qlog = Path(f.path)
          break
    except OSError:
      continue
    if qlog is not None:
      out.append((day, qlog))
  out.sort()
  return out


def _parse_qlog(path: Path) -> dict:
  try:
    from openpilot.tools.lib.logreader import LogReader
  except Exception as e:
    raise RuntimeError(f"LogReader unavailable: {e}") from e

  points: list[list[float]] = []
  last_pt: tuple[float, float] | None = None
  meters = 0.0
  engaged_s = 0.0
  total_s = 0.0
  disengages = 0
  last_t: float | None = None
  last_eng: bool | None = None
  t0 = time.monotonic()

  lr = LogReader(str(path))
  for msg in lr:
    if time.monotonic() - t0 > 25:
      break
    t = msg.logMonoTime / 1e9
    if last_t is not None and 0 < t - last_t < 5:
      dt = t - last_t
      total_s += dt
      if last_eng:
        engaged_s += dt
    last_t = t
    which = msg.which()
    if which in ("gpsLocation", "gpsLocationExternal"):
      g = getattr(msg, which)
      lat, lon = float(g.latitude), float(g.longitude)
      if abs(lat) < 1 and abs(lon) < 1:
        continue
      pt = (lat, lon)
      if last_pt is None or _haversine_m(last_pt, pt) >= 18:
        if last_pt is not None:
          meters += _haversine_m(last_pt, pt)
        points.append([round(lat, 6), round(lon, 6)])
        last_pt = pt
    elif which == "selfdriveState":
      eng = bool(msg.selfdriveState.enabled)
      if last_eng is True and not eng:
        disengages += 1
      last_eng = eng
    elif which == "controlsState" and last_eng is None:
      eng = bool(msg.controlsState.enabled)
      if last_eng is True and not eng:
        disengages += 1
      last_eng = eng

  return {
    "meters": meters,
    "engaged_s": engaged_s,
    "total_s": total_s,
    "disengages": disengages,
    "points": points,
  }


def _downsample(points: list[list[float]]) -> list[list[float]]:
  n = len(points)
  if n <= MAX_POINTS:
    return points
  step = max(1, n // MAX_POINTS)
  slim = points[::step]
  if slim[-1] != points[-1]:
    slim.append(points[-1])
  return slim[:MAX_POINTS]


def _cache_path(start: str, end: str) -> Path:
  return CACHE_DIR / f"{start}_{end}.json"


def _build_report(start: str, end: str) -> dict:
  qlogs = _qlogs_in_range(start, end)
  meters = engaged_s = total_s = 0.0
  disengages = 0
  points: list[list[float]] = []
  days: dict[str, float] = {}
  routes = 0
  for day, path in qlogs:
    try:
      part = _parse_qlog(path)
    except Exception:
      cloudlog.exception(f"stats parse {path}")
      continue
    routes += 1
    meters += part["meters"]
    engaged_s += part["engaged_s"]
    total_s += part["total_s"]
    disengages += part["disengages"]
    days[day] = days.get(day, 0.0) + part["meters"]
    points.extend(part["points"])
  miles = meters / 1609.344
  engaged_pct = (100.0 * engaged_s / total_s) if total_s > 1 else 0.0
  report = {
    "from": start,
    "to": end,
    "routes": routes,
    "miles": round(miles, 1),
    "km": round(meters / 1000.0, 1),
    "hours": round(total_s / 3600.0, 2),
    "engagedHours": round(engaged_s / 3600.0, 2),
    "engagedPct": round(engaged_pct, 1),
    "disengages": disengages,
    "points": _downsample(points),
    "byDay": {k: round(v / 1609.344, 2) for k, v in sorted(days.items())},
  }
  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  _cache_path(start, end).write_text(json.dumps(report))
  return report


def status() -> dict:
  with _lock:
    return {
      "state": _job["state"],
      "error": _job["error"],
      "from": _job["from"],
      "to": _job["to"],
      "result": _job["result"],
    }


def _run(start: str, end: str) -> None:
  try:
    report = _build_report(start, end)
    with _lock:
      if _job["state"] != "running":
        return
      _job["state"] = "done"
      _job["error"] = ""
      _job["result"] = report
  except Exception as e:
    cloudlog.exception("stats job")
    with _lock:
      _job["state"] = "error"
      _job["error"] = str(e)


def start(start: str, end: str, offroad: bool) -> dict:
  start = _valid_day(start) or ""
  end = _valid_day(end) or ""
  if not start or not end or end < start:
    return {"ok": False, "error": "bad date range"}
  if (date.fromisoformat(end) - date.fromisoformat(start)).days > MAX_RANGE_DAYS:
    return {"ok": False, "error": f"max {MAX_RANGE_DAYS} days"}
  cached = _cache_path(start, end)
  if cached.is_file():
    try:
      report = json.loads(cached.read_text())
      with _lock:
        _job.update({"state": "done", "error": "", "from": start, "to": end, "result": report})
      return {"ok": True, "cached": True, "job": status()}
    except Exception:
      pass
  if not offroad:
    return {"ok": False, "error": "Park to generate a new report. Cached reports still load."}
  with _lock:
    if _job["state"] == "running":
      return {"ok": False, "error": "already generating"}
    _job.update({"state": "running", "error": "", "from": start, "to": end, "result": None})
  threading.Thread(target=_run, args=(start, end), daemon=True).start()
  return {"ok": True, "job": status()}


def default_range() -> tuple[str, str]:
  today = date.today()
  start = today.replace(day=1)
  return start.isoformat(), today.isoformat()
