"""Label vSlam events as ramp vs mid-interstate.

Observe-only. Does not touch panda, actuators, or the planner.
Used to decide a *future* vCruise filter:

  ramp        → honor Tesla's set-speed drop (exits). OP long is not
                good enough on ramps yet.
  interstate  → candidate to ignore as a cruise ceiling. Tesla dumping
                speed in a live freeway lane is what rear-ends you.
  unknown     → hold current behavior (honor) until more traces vote.
"""
from __future__ import annotations

import math
from typing import Any


R_EARTH_M = 6371000.0


def _f(v: Any, default: float = 0.0) -> float:
  try:
    return float(v)
  except (TypeError, ValueError):
    return default


def _gps_ok(s: dict) -> bool:
  return abs(_f(s.get("lat"))) > 1e-4 and abs(_f(s.get("lon"))) > 1e-4


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
  lat1, lon1 = math.radians(a[0]), math.radians(a[1])
  lat2, lon2 = math.radians(b[0]), math.radians(b[1])
  dlat, dlon = lat2 - lat1, lon2 - lon1
  h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
  return 2.0 * R_EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def _bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
  lat1, lon1 = math.radians(a[0]), math.radians(a[1])
  lat2, lon2 = math.radians(b[0]), math.radians(b[1])
  dlon = lon2 - lon1
  x = math.sin(dlon) * math.cos(lat2)
  y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
  return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _unwrap_delta(a: float, b: float) -> float:
  return (b - a + 180.0) % 360.0 - 180.0


def _median(xs: list[float]) -> float:
  if not xs:
    return 0.0
  ys = sorted(xs)
  n = len(ys)
  mid = n // 2
  if n % 2:
    return ys[mid]
  return 0.5 * (ys[mid - 1] + ys[mid])


def path_metrics(samples: list[dict]) -> dict:
  pts = [(_f(s.get("lat")), _f(s.get("lon"))) for s in samples if _gps_ok(s)]
  if len(pts) < 3:
    return {"heading_delta_deg": None, "path_ratio": None, "path_m": None}
  n = len(pts)
  i0, i1 = 0, min(2, n - 1)
  j0, j1 = max(0, n - 3), n - 1
  heading = abs(_unwrap_delta(_bearing_deg(pts[i0], pts[i1]), _bearing_deg(pts[j0], pts[j1])))
  path = sum(_haversine_m(pts[i], pts[i + 1]) for i in range(n - 1))
  chord = _haversine_m(pts[0], pts[-1])
  ratio = path / max(chord, 1.0)
  return {
    "heading_delta_deg": round(heading, 1),
    "path_ratio": round(ratio, 3),
    "path_m": round(path, 1),
  }


def classify(event: dict, samples: list[dict] | None = None) -> dict:
  samples = list(samples or [])
  slam = [s for s in samples if s.get("in_slam")] or samples
  pre = _f(event.get("pre_mph"))
  slam_mph = _f(event.get("slam_mph"))
  delta = _f(event.get("delta_mph"), slam_mph - pre)
  dur = _f(event.get("duration_s"))
  recovered = bool(event.get("recovered"))
  blinker = bool(event.get("blinker")) or any(bool(s.get("blinker")) for s in slam[: max(1, len(slam) // 4)])
  a_min = min((_f(s.get("a_ego")) for s in slam), default=_f(event.get("a_ego")))
  v_ego_med = _median([_f(s.get("v_ego_mph")) for s in slam] or [_f(event.get("v_ego_mph"))])
  v_plan_pre = _f(event.get("v_plan_pre_mph"))
  geo = path_metrics(slam if slam else samples)
  heading = geo["heading_delta_deg"]
  ratio = geo["path_ratio"]

  ramp = 0
  hw = 0
  why: list[str] = []

  if heading is not None:
    if heading >= 25:
      ramp += 3
      why.append(f"turn {heading:.0f}°")
    elif heading >= 15:
      ramp += 2
      why.append(f"bend {heading:.0f}°")
    elif heading < 8:
      hw += 2
      why.append(f"straight {heading:.0f}°")

  if ratio is not None:
    if ratio >= 1.06:
      ramp += 2
    elif ratio <= 1.02:
      hw += 1

  if blinker:
    ramp += 2
    why.append("blinker")

  if pre >= 62:
    hw += 1
  elif pre < 55:
    ramp += 1

  if pre >= 62 and v_ego_med >= pre - 8:
    hw += 2
    why.append(f"vEgo {v_ego_med:.0f}")
  elif slam_mph and v_ego_med <= slam_mph + 6 and delta <= -10:
    ramp += 1

  if a_min <= -2.0:
    hw += 2
    why.append(f"aEgo {a_min:.1f}")
  elif a_min <= -1.2:
    hw += 1
    why.append(f"aEgo {a_min:.1f}")

  if recovered and 0 < dur <= 8:
    hw += 1
    why.append("quick recover")

  if v_plan_pre and pre and v_plan_pre <= pre - 6:
    ramp += 1
    why.append("vPlan already down")

  if ramp >= hw + 2 and ramp >= 3:
    kind = "ramp"
    hint = "honor"
  elif hw >= ramp + 2 and hw >= 3:
    kind = "interstate"
    hint = "ignore"
  else:
    kind = "unknown"
    hint = "hold"

  return {
    "kind": kind,
    "filter": hint,
    "heading_delta_deg": geo["heading_delta_deg"],
    "path_ratio": geo["path_ratio"],
    "path_m": geo["path_m"],
    "a_ego_min": round(a_min, 3),
    "v_ego_med": round(v_ego_med, 2),
    "class_why": " · ".join(why) if why else "thin trace",
    "ramp_score": ramp,
    "interstate_score": hw,
  }


def annotate(event: dict, samples: list[dict] | None = None) -> dict:
  """Mutate event with classify() fields. Safe to call twice."""
  event.update(classify(event, samples))
  return event
