"""Stats for the web GUI. Every value comes from an existing source, named in `src`; missing -> None."""
from __future__ import annotations

import os
import shutil
import threading

PERSONALITY = {0: "Aggressive", 1: "Standard", 2: "Relaxed"}
PARAMS = ("Version", "GitBranch", "GitCommit", "IsOffroad", "IsEngaged", "IsMetric", "CurrentRoute", "LongitudinalPersonality")
_sm = None
_lock = threading.Lock()  # server is threaded; SubMaster is not thread-safe


def _sub():
  global _sm
  if _sm is None:
    from openpilot.cereal import messaging
    _sm = messaging.SubMaster(["deviceState", "pandaStates", "carState"])  # read-only, never publishes
  return _sm


def _s(p, k: str) -> str:
  v = p.get(k)
  return v.decode(errors="replace") if isinstance(v, bytes) else (v or "")


def drives_on_device(realdata: str) -> int | None:
  # "<route>--<seg>" dirs; route = everything before the last "--"
  try:
    return len({n.rsplit("--", 1)[0] for n in os.listdir(realdata) if n.count("--") >= 1})
  except OSError:
    return None


def collect(data: str = "/data") -> dict:
  with _lock:
    return _collect(data)


def _collect(data: str) -> dict:
  from openpilot.common.params import Params
  p = Params()
  out: dict = {"mock": False}

  try:
    from openpilot.selfdrive.ui.tripstats import store, tz
    st, (zone, name, src) = store.load(p), tz.current(p)
    v, cur = store.view(st, st["open"], tz=zone), (st["open"] or [{}])[-1]
    out["timezone"] = {"name": name, "source": src}
    out["trips"] = {k: v[k] for k in ("today_m", "today_e", "today_pct", "week_m", "week_e", "week_pct",
                                      "life_m", "life_e", "pct", "streak_days", "longest_m", "week_days", "today_i")}
    out["current"] = {"route": cur.get("id") or "", "m": cur.get("m") or 0.0, "e": cur.get("e") or 0.0}
  except Exception:
    out["trips"], out["current"], out["timezone"] = None, None, None

  pers = p.get("LongitudinalPersonality")
  out["sw"] = {"version": _s(p, "Version"), "branch": _s(p, "GitBranch"), "commit": _s(p, "GitCommit")[:9]}
  out["state"] = {"onroad": not p.get_bool("IsOffroad"), "engaged": p.get_bool("IsEngaged"), "metric": p.get_bool("IsMetric"),
                  "route": _s(p, "CurrentRoute"), "personality": PERSONALITY.get(int(pers)) if pers is not None else None}
  out["drives_on_device"] = drives_on_device(os.path.join(data, "media/0/realdata"))

  try:
    du = shutil.disk_usage(data)
    out["storage"] = {"total": du.total, "free": du.free}
  except OSError:
    out["storage"] = None

  dev = panda = car = None
  try:
    sm = _sub()
    sm.update(50)
    if sm.seen["deviceState"]:
      ds = sm["deviceState"]
      temps, cores = list(ds.cpuTempC), list(ds.cpuUsagePercent)
      dev = {"cpu_temp": max(temps) if temps else None, "cpu_pct": round(sum(cores) / len(cores)) if cores else None,
             "mem_pct": int(ds.memoryUsagePercent), "free_pct": round(ds.freeSpacePercent, 1),
             "thermal": str(ds.thermalStatus), "network": str(ds.networkType), "fan_pct": int(ds.fanSpeedPercentDesired)}
    if sm.seen["pandaStates"]:
      ps = list(sm["pandaStates"])
      panda = {"connected": sm.alive["pandaStates"] and len(ps) > 0, "count": len(ps),
               "type": str(ps[0].pandaType) if ps else None, "ignition": any(x.ignitionLine or x.ignitionCan for x in ps)}
    if sm.seen["carState"] and sm.alive["carState"]:
      cs = sm["carState"]
      car = {"v_ego": cs.vEgo, "set_speed": cs.cruiseState.speed if cs.cruiseState.enabled else None,
             "cruise_on": cs.cruiseState.enabled}
  except Exception:
    pass
  out["device"], out["panda"], out["car"] = dev, panda, car

  out["src"] = {
    "trips": "DriveSummaryLast via tripstats (same as Home/Statistics)",
    "current": "DriveSummaryLast drive in progress (saved every 30 s)",
    "timezone": "params Timezone (from the last GPS fix), else the system zone",
    "sw": "params Version/GitBranch/GitCommit",
    "state": "params IsOffroad/IsEngaged/LongitudinalPersonality/CurrentRoute",
    "drives_on_device": "route dirs in /data/media/0/realdata (rotates out)",
    "storage": "statvfs /data",
    "device": "deviceState", "panda": "pandaStates", "car": "carState (onroad only)",
  }
  return out


def mock() -> dict:
  days = [("2026-10-25", 0, 0), ("2026-10-26", 41200, 36800), ("2026-10-27", 18300, 15900),
          ("2026-10-28", 96400, 88100), ("2026-10-29", 23800, 21000), ("2026-10-30", 0, 0), ("2026-10-31", 0, 0)]
  return {
    "mock": True,
    "trips": {"today_m": 23800.0, "today_e": 21000.0, "today_pct": 88, "week_m": 179700.0, "week_e": 161800.0, "week_pct": 90,
              "life_m": 9654000.0, "life_e": 8303000.0, "pct": 86, "streak_days": 12, "longest_m": 182000.0,
              "week_days": [{"id": d, "m": m, "e": e} for d, m, e in days], "today_i": 4},
    "current": {"route": "0000012a--4f3c9e1d2b", "m": 8400.0, "e": 7900.0},
    "timezone": {"name": "America/Denver", "source": "gps"},
    "sw": {"version": "0.11.23", "branch": "jetlink-sync-agnos19", "commit": "4c6ce3d32"},
    "state": {"onroad": True, "engaged": True, "metric": False, "route": "0000012a--4f3c9e1d2b", "personality": "Aggressive"},
    "drives_on_device": 37,
    "storage": {"total": 476_000_000_000, "free": 311_000_000_000},
    "device": {"cpu_temp": 61.0, "cpu_pct": 34, "mem_pct": 48, "free_pct": 65.3, "thermal": "green", "network": "wifi", "fan_pct": 30},
    "panda": {"connected": True, "count": 1, "type": "redPanda", "ignition": True},
    "car": {"v_ego": 29.1, "set_speed": 31.29, "cruise_on": True},
    "src": dict.fromkeys(("trips", "current", "timezone", "sw", "state", "drives_on_device", "storage", "device", "panda", "car"), "MOCK"),
  }
