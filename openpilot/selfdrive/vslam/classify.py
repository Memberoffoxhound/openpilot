"""Observe-only: label vSlam events as cornering vs straight."""
from __future__ import annotations

import math
from typing import Any


R_EARTH_M = 6371000.0
SLAM_MPH = 6.0
STRAIGHT_RECOVER_S = 6.0
RISE_MPH = 1.0


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


def recover_window(event: dict, samples: list[dict] | None = None,
                   window_s: float = STRAIGHT_RECOVER_S) -> dict:
  """Did set speed start increasing within window_s after the slam floor?"""
  samples = list(samples or [])
  t0 = _f(event.get("t0"))
  slam_mph = _f(event.get("slam_mph"))
  dur = _f(event.get("duration_s"))
  recovered = bool(event.get("recovered"))

  timed = []
  if t0:
    for s in samples:
      t = _f(s.get("t"))
      if t0 <= t <= t0 + window_s:
        timed.append(s)
  if not timed:
    timed = [s for s in samples if s.get("in_slam")]
    if timed and not t0:
      t0 = _f(timed[0].get("t"))
      timed = [s for s in timed if _f(s.get("t")) <= t0 + window_s]

  driver = bool(event.get("gas"))
  for s in timed:
    if bool(s.get("gas")):
      driver = True

  floor = slam_mph
  vs = [_f(s.get("v_cruise_mph")) for s in timed]
  if vs:
    floor = min(vs)

  rise_s = None
  rise_mph = None
  seen_floor = False
  for s in timed:
    v = _f(s.get("v_cruise_mph"))
    t = _f(s.get("t"))
    if v <= floor + 0.15:
      seen_floor = True
    if seen_floor and v >= floor + RISE_MPH:
      rise_s = round(max(0.0, t - t0), 2) if t0 else None
      rise_mph = round(v, 2)
      break

  if rise_s is None and not timed and recovered and 0 < dur <= window_s:
    rise_s = round(dur, 2)
    rise_mph = _f(event.get("recover_mph"), _f(event.get("pre_mph")))

  return {
    "recover_wait_s": window_s,
    "slam_floor_mph": round(floor, 2) if floor else None,
    "rise_started": rise_s is not None,
    "rise_s": rise_s,
    "rise_mph": rise_mph,
    "driver_adjust": driver,
  }


def _straight_filter(rw: dict) -> tuple[str, str, str]:
  if rw.get("driver_adjust"):
    return (
      "driver",
      "Straight road \u2014 driver",
      "Driver is adjusting speed. Leave the set-speed change alone.",
    )
  if rw.get("rise_started"):
    when = rw.get("rise_s")
    when_s = f" at {when:.1f}s" if when is not None else ""
    return (
      "ignore",
      "Straight road \u2014 ignore",
      f"Set speed started increasing{when_s} inside the 6s window. "
      "Treat as a glitch \u2014 do not follow the slam down.",
    )
  return (
    "honor",
    "Straight road \u2014 honor",
    "Set speed did not start increasing after 6s. Follow set speed down.",
  )


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
  rw = recover_window(event, samples)

  corner = 0
  straight = 0
  facts: list[str] = []

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

  if a_min <= -1.2:
    facts.append(f"aEgo {a_min:.1f}")

  if recovered and 0 < dur <= 8:
    straight += 1
    facts.append("quick recover")

  if v_plan_pre and pre and v_plan_pre <= pre - 6:
    corner += 1
    facts.append(f"vPlan already {v_plan_pre:.0f}")

  if rw["driver_adjust"]:
    facts.append("driver adjusting")
  elif rw["rise_started"]:
    if rw["rise_s"] is not None:
      facts.append(f"set speed rose at {rw['rise_s']:.1f}s")
    else:
      facts.append("set speed rose in 6s")
  elif abs(delta) >= SLAM_MPH or slam_mph:
    facts.append("no rise in 6s")

  if corner >= straight + 2 and corner >= 3:
    path = "cornering"
    hint = "honor"
  elif straight >= corner + 2 and straight >= 3:
    path = "straight"
    hint = "hold"  # overwritten below for straight
  else:
    path = "unknown"
    hint = "hold"

  if path == "cornering":
    headline = "Cornering \u2014 honor"
    summary = "Path is bending (ramp or real curve). Honor this slam."
  elif path == "straight":
    hint, headline, summary = _straight_filter(rw)
  else:
    headline = "Not enough path \u2014 hold"
    summary = (
      "Trace is thin or mixed. Hold current behavior (honor) until "
      "more events vote. Logger is observe-only."
    )

  return {
    "path": path,
    "filter": hint,
    "headline": headline,
    "summary": summary,
    "heading_delta_deg": geo["heading_delta_deg"],
    "path_ratio": geo["path_ratio"],
    "path_m": geo["path_m"],
    "a_ego_min": round(a_min, 3),
    "v_ego_med": round(v_ego_med, 2),
    "facts": facts,
    "corner_score": corner,
    "straight_score": straight,
    "recover_wait_s": rw["recover_wait_s"],
    "slam_floor_mph": rw["slam_floor_mph"],
    "rise_started": rw["rise_started"],
    "rise_s": rw["rise_s"],
    "rise_mph": rw["rise_mph"],
    "driver_adjust": rw["driver_adjust"],
  }


def annotate(event: dict, samples: list[dict] | None = None) -> dict:
  """Mutate event with classify() fields. Safe to call twice."""
  event.update(classify(event, samples))
  return event
