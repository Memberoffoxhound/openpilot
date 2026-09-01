"""Label vSlam events as cornering vs straight road.

Observe-only. Does not touch panda, actuators, or the planner.

  cornering  → honor Tesla's set-speed drop (ramp / real curve)
  straight   → ignore candidate (slam on a lane that is not turning)
  unknown    → hold current behavior until the trace has enough path
"""
from __future__ import annotations

import math
from typing import Any


R_EARTH_M = 6371000.0


def _f(v: Any, default: float = 0.0) -> float:
  try:
    if v is None or v == "":
      return default
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

  model_yaw = event.get("model_yaw_4s")
  if model_yaw is None and slam:
    model_yaw = slam[0].get("model_yaw_4s")
  model_y = event.get("model_y_3s")
  if model_y is None and slam:
    model_y = slam[0].get("model_y_3s")
  model_yaw_f = None if model_yaw is None else abs(_f(model_yaw))
  model_y_f = None if model_y is None else abs(_f(model_y))

  corner = 0
  straight = 0
  facts: list[str] = []

  if model_yaw_f is not None:
    if model_yaw_f >= 12:
      corner += 3
      facts.append(f"model yaw {model_yaw_f:.0f} deg at 4s")
    elif model_yaw_f < 8:
      straight += 2
      facts.append(f"model yaw {model_yaw_f:.0f} deg at 4s")
  if model_y_f is not None:
    if model_y_f >= 2.0:
      corner += 2
      facts.append(f"model path y {model_y_f:.1f} m at 3s")
    elif model_y_f < 1.2:
      straight += 1
      facts.append(f"model path y {model_y_f:.1f} m at 3s")
  if model_yaw_f is None and model_y_f is None:
    facts.append("model path not on this trace")

  if heading is not None:
    if heading >= 25:
      corner += 3
      facts.append(f"GPS heading {heading:.0f} deg")
    elif heading >= 15:
      corner += 2
      facts.append(f"GPS heading {heading:.0f} deg")
    elif heading < 8:
      straight += 2
      facts.append(f"GPS heading {heading:.0f} deg")

  if ratio is not None:
    if ratio >= 1.06:
      corner += 2
      facts.append(f"path/chord {ratio:.2f}")
    elif ratio <= 1.02:
      straight += 1
      facts.append(f"path/chord {ratio:.2f}")

  if blinker:
    corner += 2
    facts.append("blinker")

  if pre >= 62 and v_ego_med >= pre - 8:
    straight += 1
    facts.append(f"still {v_ego_med:.0f} mph")
  elif slam_mph and v_ego_med <= slam_mph + 6 and delta <= -10:
    corner += 1

  if a_min <= -2.0:
    facts.append(f"aEgo {a_min:.1f}")
  elif a_min <= -1.2:
    facts.append(f"aEgo {a_min:.1f}")

  if recovered and 0 < dur <= 8:
    straight += 1
    facts.append("quick recover")

  if v_plan_pre and pre and v_plan_pre <= pre - 6:
    corner += 1
    facts.append(f"vPlan already {v_plan_pre:.0f}")

  if corner >= straight + 2 and corner >= 3:
    path = "cornering"
    hint = "honor"
  elif straight >= corner + 2 and straight >= 3:
    path = "straight"
    hint = "ignore"
  else:
    path = "unknown"
    hint = "hold"

  if path == "cornering":
    headline = "Cornering \u2014 honor"
    summary = (
      "Path is bending (ramp or real curve). Honor this slam. "
      "openpilot long is not ready to invent that slowdown."
    )
  elif path == "straight":
    headline = "Straight road \u2014 ignore"
    summary = (
      "Path stayed a lane. Tesla dumped set speed on a straight road. "
      "Ignore candidate \u2014 same class as Ferguson, on any road."
    )
  else:
    headline = "Not enough path \u2014 hold"
    summary = (
      "Trace is thin or mixed. Hold current behavior (honor) until "
      "more events vote. Logger is observe-only."
    )

  return {
    "kind": path,
    "path": path,
    "filter": hint,
    "headline": headline,
    "summary": summary,
    "heading_delta_deg": geo["heading_delta_deg"],
    "path_ratio": geo["path_ratio"],
    "path_m": geo["path_m"],
    "a_ego_min": round(a_min, 3),
    "v_ego_med": round(v_ego_med, 2),
    "class_why": " \u00b7 ".join(facts) if facts else "thin trace",
    "facts": facts,
    "corner_score": corner,
    "straight_score": straight,
    "model_yaw_4s": None if model_yaw_f is None else round(model_yaw_f, 1),
    "model_y_3s": None if model_y_f is None else round(model_y_f, 2),
  }


def annotate(event: dict, samples: list[dict] | None = None) -> dict:
  """Mutate event with classify() fields. Safe to call twice."""
  event.update(classify(event, samples))
  return event
