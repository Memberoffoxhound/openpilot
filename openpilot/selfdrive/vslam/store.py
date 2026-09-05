from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path("/data/vslam")
EVENTS_PATH = ROOT / "events.jsonl"
TRACE_DIR = ROOT / "traces"
ALERT_UNTIL_PATH = ROOT / "alert_until"
ENABLED_PATH = ROOT / "enabled"
ENABLED_PARAM = "VSlamEnabled"
FILTER_PATH = ROOT / "filter"
FILTER_PARAM = "VSlamFilterEnabled"
ALERT_S = 3.0
MAX_EVENTS = 400


def ensure() -> None:
  TRACE_DIR.mkdir(parents=True, exist_ok=True)


def fire_logged_alert(duration_s: float = ALERT_S) -> None:
  """Stamp a 3s onroad toast. UI reads this; no panda / selfdrived change."""
  ensure()
  try:
    ALERT_UNTIL_PATH.write_text(f"{time.time() + duration_s:.3f}\n", encoding="utf-8")
  except OSError:
    pass


def is_enabled(params=None) -> bool:
  """Default on. File wins so the toggle works before a params rebuild."""
  try:
    if ENABLED_PATH.is_file():
      return ENABLED_PATH.read_text(encoding="utf-8").strip() != "0"
  except OSError:
    pass
  if params is not None:
    try:
      return bool(params.get_bool(ENABLED_PARAM))
    except Exception:
      pass
  return True


def set_enabled(on: bool, params=None) -> None:
  ensure()
  try:
    ENABLED_PATH.write_text("1\n" if on else "0\n", encoding="utf-8")
  except OSError:
    pass
  if params is not None:
    try:
      params.put_bool(ENABLED_PARAM, bool(on), block=True)
    except Exception:
      pass


def op_long_active(params=None) -> bool:
  """True when openpilot long is the live policy. False = Tesla TACC owns gas/brake."""
  if params is None:
    try:
      from openpilot.common.params import Params
      params = Params()
    except Exception:
      return False
  try:
    return bool(params.get_bool("AlphaLongitudinalEnabled"))
  except Exception:
    return False


def is_filter_enabled(params=None) -> bool:
  """Armed only on OP long. File wins so the toggle works before a params rebuild."""
  if not op_long_active(params):
    return False
  try:
    if FILTER_PATH.is_file():
      return FILTER_PATH.read_text(encoding="utf-8").strip() != "0"
  except OSError:
    pass
  if params is not None:
    try:
      return bool(params.get_bool(FILTER_PARAM))
    except Exception:
      pass
  return True


def set_filter_enabled(on: bool, params=None) -> bool:
  """Persist the filter toggle. Forced off when TACC is the long policy."""
  if not op_long_active(params):
    on = False
  ensure()
  try:
    FILTER_PATH.write_text("1\n" if on else "0\n", encoding="utf-8")
  except OSError:
    pass
  if params is not None:
    try:
      params.put_bool(FILTER_PARAM, bool(on), block=True)
    except Exception:
      pass
  return bool(on) and op_long_active(params)


_alert_cache: tuple[float, float] = (0.0, 0.0)  # mtime, until


def alert_until() -> float:
  global _alert_cache
  try:
    mtime = ALERT_UNTIL_PATH.stat().st_mtime
  except OSError:
    return 0.0
  if _alert_cache[0] == mtime:
    return _alert_cache[1]
  try:
    until = float(ALERT_UNTIL_PATH.read_text(encoding="utf-8").strip())
  except (OSError, ValueError):
    until = 0.0
  _alert_cache = (mtime, until)
  return until


def load_events(limit: int = 200) -> list[dict]:
  if not EVENTS_PATH.is_file():
    return []
  out: list[dict] = []
  try:
    with EVENTS_PATH.open("r", encoding="utf-8") as f:
      for line in f:
        line = line.strip()
        if not line:
          continue
        try:
          ev = json.loads(line)
        except json.JSONDecodeError:
          continue
        if isinstance(ev, dict) and ev.get("id"):
          out.append(ev)
  except OSError:
    return []
  return out[-limit:]


def append_event(ev: dict) -> None:
  ensure()
  with EVENTS_PATH.open("a", encoding="utf-8") as f:
    f.write(json.dumps(ev, separators=(",", ":")) + "\n")
  events = load_events(MAX_EVENTS + 80)
  if len(events) > MAX_EVENTS:
    keep = events[-MAX_EVENTS:]
    with EVENTS_PATH.open("w", encoding="utf-8") as f:
      for e in keep:
        f.write(json.dumps(e, separators=(",", ":")) + "\n")
    keep_ids = {e["id"] for e in keep}
    for p in TRACE_DIR.glob("*.json"):
      if p.stem not in keep_ids:
        try:
          p.unlink()
        except OSError:
          pass


def write_trace(eid: str, samples: list[dict]) -> None:
  ensure()
  path = TRACE_DIR / f"{eid}.json"
  path.write_text(json.dumps({"id": eid, "samples": samples}, separators=(",", ":")), encoding="utf-8")


def load_trace(eid: str) -> dict:
  path = TRACE_DIR / f"{eid}.json"
  if not path.is_file():
    return {"id": eid, "samples": []}
  try:
    obj = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return {"id": eid, "samples": []}
  if not isinstance(obj, dict):
    return {"id": eid, "samples": []}
  obj.setdefault("id", eid)
  obj.setdefault("samples", [])
  return obj


def compact_spark(samples: list[dict], n: int = 48) -> list[dict]:
  """Downsampled vCruise + in_slam flags for the event-list mini spark."""
  if not samples:
    return []
  step = max(1, len(samples) // n)
  pts: list[dict] = []
  for s in samples[::step]:
    pts.append({
      "v": round(float(s.get("v_cruise_mph") or 0), 1),
      "s": 1 if s.get("in_slam") else 0,
    })
  last = samples[-1]
  last_pt = {
    "v": round(float(last.get("v_cruise_mph") or 0), 1),
    "s": 1 if last.get("in_slam") else 0,
  }
  if not pts or pts[-1] != last_pt:
    pts.append(last_pt)
  return pts
