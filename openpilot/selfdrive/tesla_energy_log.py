#!/usr/bin/env python3
"""2 Hz Tesla Party energy + trip meter. Onroad only. Does not talk to panda."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("PYTHONPATH", "/data/openpilot")

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper

REALDATA = Path("/data/media/0/realdata")
TRIP_PATH = Path("/data/trip_meter.json")
IDS = {0x108, 0x126, 0x118, 0x257}


def _bits(dat: bytes, start: int, length: int, signed: bool = False) -> int:
  val = 0
  for i in range(length):
    if dat[(start + i) // 8] & (1 << ((start + i) % 8)):
      val |= 1 << i
  if signed and val & (1 << (length - 1)):
    val -= 1 << length
  return val


def _sunday_id() -> str:
  now = time.localtime()
  sun = time.mktime(now) - ((now.tm_wday + 1) % 7) * 86400
  st = time.localtime(sun)
  return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d}"


def _load_trip() -> dict:
  t = {"trip_m": 0.0, "eng_s": 0.0, "tot_s": 0.0,
       "last_m": 0.0, "last_eng_s": 0.0, "last_tot_s": 0.0, "route": "",
       "week_m": 0.0, "week_eng_s": 0.0, "week_tot_s": 0.0, "week_id": ""}
  try:
    t.update(json.loads(TRIP_PATH.read_text()))
  except Exception:
    pass
  return t


def _save_trip(t: dict) -> None:
  tmp = TRIP_PATH.with_suffix(".tmp")
  tmp.write_text(json.dumps(t))
  tmp.replace(TRIP_PATH)


def main() -> None:
  params = Params()
  sm = messaging.SubMaster(["carState", "selfdriveState"])
  logcan = messaging.sub_sock("can", timeout=100)
  rk = Ratekeeper(2.0, print_delay_threshold=None)
  trip = _load_trip()
  last_t = time.monotonic()
  last_flush = 0.0
  frames: dict[int, bytes] = {}
  log_fp = None
  log_name = ""

  while True:
    sm.update(0)
    for msg in messaging.drain_sock(logcan):
      for y in msg.can:
        if int(y.src) == 0 and int(y.address) in IDS:
          frames[int(y.address)] = bytes(y.dat)

    now = time.monotonic()
    dt = min(1.0, max(0.0, now - last_t))
    last_t = now

    route = params.get("CurrentRoute") or ""
    offroad = params.get_bool("IsOffroad")
    wid = _sunday_id()
    if trip.get("week_id") != wid:
      trip["week_m"] = trip["week_eng_s"] = trip["week_tot_s"] = 0.0
      trip["week_id"] = wid
    if route and route != trip.get("route"):
      if trip.get("tot_s", 0) > 5:
        trip["last_m"] = trip["trip_m"]
        trip["last_eng_s"] = trip["eng_s"]
        trip["last_tot_s"] = trip["tot_s"]
      trip["trip_m"] = trip["eng_s"] = trip["tot_s"] = 0.0
      trip["route"] = route
      if log_fp:
        log_fp.close()
        log_fp = None

    if not offroad and sm.recv_frame["carState"] > 0:
      v = float(sm["carState"].vEgo)
      trip["trip_m"] += v * dt
      trip["tot_s"] += dt
      trip["week_m"] += v * dt
      trip["week_tot_s"] += dt
      if sm.recv_frame["selfdriveState"] > 0 and sm["selfdriveState"].enabled:
        trip["eng_s"] += dt
        trip["week_eng_s"] += dt

      tq = rpm = kw = hv = None
      d108 = frames.get(0x108)
      if d108 and len(d108) >= 8:
        tq = _bits(d108, 27, 13, True) * 2.0
        rpm = _bits(d108, 40, 16, True) * 0.1
        kw = (tq * rpm) / 9549.3 if rpm else 0.0
      d126 = frames.get(0x126)
      if d126 and len(d126) >= 2:
        hv = int.from_bytes(d126[:2], "little") * 0.01

      if route:
        name = f"tesla_energy-{route}.jsonl"
        if log_fp is None or log_name != name:
          if log_fp:
            log_fp.close()
          path = REALDATA / name
          log_fp = open(path, "a", buffering=1)
          log_name = name
        rec = {
          "t": time.time(), "v": round(v, 3), "kw": None if kw is None else round(kw, 2),
          "nm": None if tq is None else round(tq, 1), "rpm": None if rpm is None else round(rpm, 1),
          "hv": None if hv is None else round(hv, 1),
          "en": bool(sm.recv_frame["selfdriveState"] > 0 and sm["selfdriveState"].enabled),
          "x126": None if not d126 else d126.hex(),
        }
        log_fp.write(json.dumps(rec) + "\n")

    if now - last_flush > 5.0:
      _save_trip(trip)
      last_flush = now
      if log_fp:
        log_fp.flush()

    rk.keep_time()


if __name__ == "__main__":
  main()
