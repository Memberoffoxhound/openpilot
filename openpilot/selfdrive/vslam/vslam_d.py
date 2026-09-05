#!/usr/bin/env python3
"""Detect vCruise slams >= 6 mph and persist traces + place names.

Does not touch panda safety or actuation. Observe-only.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.vslam.classify import recover_window
from openpilot.selfdrive.vslam.store import EVENTS_PATH, append_event, compact_spark, fire_logged_alert, is_enabled, write_trace

MPH = 2.2369362920544
SLAM_MPH = 6.0
RECOVER_MPH = 2.0
MAX_EVENT_S = 20.0
WINDOW_S = 60.0
PRE_S = 5.0
POST_S = 5.0
HZ = 20
try:
  CHI = ZoneInfo("America/Chicago")
except Exception:
  CHI = timezone.utc


def _mph(ms: float) -> float:
  return float(ms) * MPH


def _local(ts: float) -> str:
  return datetime.fromtimestamp(ts, CHI).strftime("%Y-%m-%d %I:%M:%S %p")


def _eid(ts: float) -> str:
  return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]


def _route(params: Params) -> str:
  raw = params.get("CurrentRoute")
  if raw:
    return raw if isinstance(raw, str) else raw.decode()
  dongle = params.get("DongleId") or ""
  if isinstance(dongle, bytes):
    dongle = dongle.decode()
  try:
    from pathlib import Path
    rd = Path("/data/media/0/realdata")
    if rd.is_dir():
      dirs = sorted([p.name for p in rd.iterdir() if p.is_dir() and "--" in p.name])
      if dirs:
        return f"{dongle}|{dirs[-1]}" if dongle else dirs[-1]
  except OSError:
    pass
  return dongle or ""


def _a_target(lp) -> float:
  try:
    accels = list(lp.accels)
    if accels:
      return float(accels[0])
  except Exception:
    pass
  try:
    return float(lp.aTarget)
  except Exception:
    return 0.0


def _v_plan(lp) -> float:
  try:
    speeds = list(lp.speeds)
    if speeds:
      return float(speeds[0])
  except Exception:
    return 0.0


def _reverse(lat: float, lon: float) -> dict:
  if abs(lat) < 1e-6 and abs(lon) < 1e-6:
    return {}
  q = urllib.parse.urlencode({
    "lat": f"{lat:.6f}",
    "lon": f"{lon:.6f}",
    "format": "jsonv2",
    "zoom": 16,
    "addressdetails": 1,
  })
  req = urllib.request.Request(
    "https://nominatim.openstreetmap.org/reverse?" + q,
    headers={"User-Agent": "S3XYPilot-vslam/0.11.23 (hobby device)"},
  )
  try:
    with urllib.request.urlopen(req, timeout=6) as r:
      data = json.loads(r.read().decode())
  except Exception:
    return {}
  addr = data.get("address") or {}
  road = addr.get("road") or addr.get("highway") or addr.get("residential") or ""
  ref = addr.get("road_ref") or ""
  if not road and data.get("name"):
    road = data["name"]
  city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or addr.get("county") or ""
  state = addr.get("state_code") or addr.get("state") or ""
  if isinstance(state, str) and len(state) > 2:
    state = addr.get("ISO3166-2-lvl4", state)
    if isinstance(state, str) and "-" in state:
      state = state.split("-")[-1]
  label = ", ".join([p for p in (road or ref, city, state) if p])
  return {
    "road": road or ref,
    "city": city,
    "state": state,
    "place": label or data.get("display_name") or "",
  }


class VSlamD:
  def __init__(self):
    self.params = Params()
    # liveLocationKalman is gone on this cereal — unknown sockets crash SubMaster
    # and manager then blocks engage with processNotRunning.
    self.sm = messaging.SubMaster([
      "carState", "longitudinalPlan", "gpsLocation", "gpsLocationExternal",
      "deviceState",
    ])
    self.buf: deque[dict] = deque(maxlen=HZ * int(WINDOW_S) + 40)
    self.active: dict | None = None
    self.pending: dict | None = None
    self.prev_v = None
    self._geo_lock = threading.Lock()

  def _gps(self) -> tuple[float, float]:
    for name in ("gpsLocationExternal", "gpsLocation"):
      if not self.sm.valid.get(name):
        continue
      g = self.sm[name]
      lat, lon = float(g.latitude), float(g.longitude)
      if abs(lat) > 1e-4:
        return lat, lon
    return 0.0, 0.0

  def sample(self, now: float) -> dict | None:
    cs = self.sm["carState"]
    if not self.sm.valid["carState"]:
      return None
    cruise = cs.cruiseState
    v_c = float(cruise.speed or 0.0)
    lp = self.sm["longitudinalPlan"] if self.sm.valid["longitudinalPlan"] else None
    lat, lon = self._gps()
    return {
      "t": now,
      "v_cruise_mph": round(_mph(v_c), 3),
      "v_ego_mph": round(_mph(float(cs.vEgo)), 3),
      "a_ego": round(float(cs.aEgo), 4),
      "a_target": round(_a_target(lp) if lp is not None else 0.0, 4),
      "v_plan_mph": round(_mph(_v_plan(lp)) if lp is not None else 0.0, 3),
      "enabled": bool(cruise.enabled),
      "gas": bool(cs.gasPressed),
      "brake": bool(cs.brakePressed),
      "blinker": bool(cs.leftBlinker or cs.rightBlinker),
      "lat": lat,
      "lon": lon,
    }

  def _window(self, t0: float, t1: float) -> list[dict]:
    lo = t0 - PRE_S
    hi = t1 + POST_S
    samples = [dict(s) for s in self.buf if lo <= s["t"] <= hi]
    for s in samples:
      s["in_slam"] = t0 <= s["t"] <= t1
    return samples

  def _finish(self, ev: dict, recovered: bool) -> None:
    ev["recovered"] = recovered
    ev["duration_s"] = round(ev["t_end"] - ev["t0"], 3)
    ev["local_end"] = _local(ev["t_end"])
    samples = self._window(ev["t0"], ev["t_end"])
    ev["spark"] = compact_spark(samples)
    ev.update(recover_window(ev, samples))
    write_trace(ev["id"], samples)
    append_event({k: v for k, v in ev.items() if not str(k).startswith("_")})
    cloudlog.warning(
      f"vslam {ev['pre_mph']:.0f}->{ev['slam_mph']:.0f} mph "
      f"{ev['duration_s']:.1f}s {ev.get('place') or ''} {ev.get('route') or ''}"
    )
    lat, lon = ev.get("lat") or 0.0, ev.get("lon") or 0.0
    if abs(lat) > 1e-4:
      threading.Thread(target=self._fill_place, args=(ev["id"], lat, lon), daemon=True).start()

  def _fill_place(self, eid: str, lat: float, lon: float) -> None:
    info = _reverse(lat, lon)
    if not info:
      return
    with self._geo_lock:
      try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
      except OSError:
        return
      out = []
      for line in lines:
        try:
          obj = json.loads(line)
        except json.JSONDecodeError:
          out.append(line)
          continue
        if obj.get("id") == eid:
          obj.update(info)
        out.append(json.dumps(obj, separators=(",", ":")))
      EVENTS_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")

  def tick(self, now: float) -> None:
    if not is_enabled(self.params):
      if self.active is not None:
        self.active = None
      if self.pending is not None:
        self.pending = None
      self.prev_v = None
      return
    s = self.sample(now)
    if s is None:
      return
    self.buf.append(s)
    v = s["v_cruise_mph"]
    prev = self.prev_v
    self.prev_v = v

    if self.pending is not None:
      if now >= float(self.pending.get("_hold_until") or 0):
        ev = self.pending
        self.pending = None
        self._finish(ev, recovered=bool(ev.get("recovered")))
      return

    if self.active is not None:
      ev = self.active
      ev["t_end"] = now
      ev["slam_mph"] = min(ev["slam_mph"], v)
      ev["delta_mph"] = round(ev["slam_mph"] - ev["pre_mph"], 2)
      if s["lat"]:
        ev["lat"], ev["lon"] = s["lat"], s["lon"]
      recovered = (v + RECOVER_MPH) >= ev["pre_mph"]
      timed_out = (now - ev["t0"]) >= MAX_EVENT_S
      dropped_enable = not s["enabled"]
      if recovered or timed_out or dropped_enable:
        ev["recover_mph"] = round(v, 2)
        ev["recovered"] = recovered and not dropped_enable
        ev["t_end"] = now
        ev["_hold_until"] = now + POST_S
        self.pending = ev
        self.active = None
      return

    if prev is None or not s["enabled"]:
      return
    drop = prev - v
    if drop < SLAM_MPH:
      return
    eid = _eid(now)
    ev = {
      "id": eid,
      "t0": now,
      "t_end": now,
      "local_time": _local(now),
      "tz": "America/Chicago",
      "route": _route(self.params),
      "pre_mph": round(prev, 2),
      "slam_mph": round(v, 2),
      "delta_mph": round(-drop, 2),
      "recover_mph": None,
      "recovered": False,
      "duration_s": 0.0,
      "v_ego_mph": round(s["v_ego_mph"], 2),
      "a_ego": round(s["a_ego"], 3),
      "a_target_pre": round(s["a_target"], 3),
      "v_plan_pre_mph": round(s["v_plan_mph"], 2),
      "gas": s["gas"],
      "brake": s["brake"],
      "blinker": s["blinker"],
      "lat": s["lat"],
      "lon": s["lon"],
      "road": "",
      "city": "",
      "state": "",
      "place": "",
    }
    self.active = ev
    fire_logged_alert()
    cloudlog.info(f"vslam start {ev['pre_mph']:.0f}->{ev['slam_mph']:.0f}")

  def run(self) -> None:
    rk = Ratekeeper(HZ)
    cloudlog.warning("vslam_d started")
    while True:
      try:
        self.sm.update(0)
        self.tick(time.time())
      except Exception:
        cloudlog.exception("vslam_d tick")
      rk.keep_time()


def main() -> None:
  while True:
    try:
      VSlamD().run()
    except Exception:
      cloudlog.exception("vslam_d died; restarting")
      time.sleep(1.0)


if __name__ == "__main__":
  main()
