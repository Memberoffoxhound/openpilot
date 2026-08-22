#!/usr/bin/env python3
"""2 Hz Tesla Party energy jsonl. Onroad only. Does not talk to panda. Trip meter lives in the UI."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("PYTHONPATH", "/data/openpilot")

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper

REALDATA = Path("/data/media/0/realdata")
IDS = {0x108, 0x126, 0x118, 0x257}


def _bits(dat: bytes, start: int, length: int, signed: bool = False) -> int:
  val = 0
  for i in range(length):
    if dat[(start + i) // 8] & (1 << ((start + i) % 8)):
      val |= 1 << i
  if signed and val & (1 << (length - 1)):
    val -= 1 << length
  return val


def main() -> None:
  params = Params()
  sm = messaging.SubMaster(["carState", "selfdriveState"])
  logcan = messaging.sub_sock("can", timeout=100)
  rk = Ratekeeper(2.0, print_delay_threshold=None)
  frames: dict[int, bytes] = {}
  log_fp = None
  log_name = ""

  while True:
    sm.update(0)
    for msg in messaging.drain_sock(logcan):
      for y in msg.can:
        if int(y.src) == 0 and int(y.address) in IDS:
          frames[int(y.address)] = bytes(y.dat)

    offroad = params.get_bool("IsOffroad")
    route = params.get("CurrentRoute") or ""
    if (not offroad) and sm.recv_frame["carState"] > 0 and route:
      v = float(sm["carState"].vEgo)
      tq = rpm = kw = hv = None
      d108 = frames.get(0x108)
      if d108 and len(d108) >= 8:
        tq = _bits(d108, 27, 13, True) * 2.0
        rpm = _bits(d108, 40, 16, True) * 0.1
        kw = (tq * rpm) / 9549.3 if rpm else 0.0
      d126 = frames.get(0x126)
      if d126 and len(d126) >= 2:
        hv = int.from_bytes(d126[:2], "little") * 0.01
      name = f"tesla_energy-{route}.jsonl"
      if log_fp is None or log_name != name:
        if log_fp:
          log_fp.close()
        log_fp = open(REALDATA / name, "a", buffering=1)
        log_name = name
      rec = {
        "t": time.time(), "v": round(v, 3), "kw": None if kw is None else round(kw, 2),
        "nm": None if tq is None else round(tq, 1), "rpm": None if rpm is None else round(rpm, 1),
        "hv": None if hv is None else round(hv, 1),
        "en": bool(sm.recv_frame["selfdriveState"] > 0 and sm["selfdriveState"].enabled),
      }
      log_fp.write(json.dumps(rec) + "\n")
    elif log_fp is not None:
      log_fp.close()
      log_fp = None
      log_name = ""

    rk.keep_time()


if __name__ == "__main__":
  main()
