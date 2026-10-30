#!/usr/bin/env python3
"""Builds tzgrid.bin, the offline lat/lon -> IANA zone table tz.py reads. Dev only, not run on the device:
  uv pip install timezonefinder numpy && python build_tzgrid.py [step_deg]

Each STEP x STEP degree cell holds the zone at its center (timezone-boundary-builder polygons, via
timezonefinder_data). Rows run north to south from 90, cells west to east from -180. zlib of
  {"step", "zones", "src"} JSON, "\n", then (count u8, zone index u16 LE) runs over all cells.
"""
import json
import struct
import sys
import zlib
from importlib.metadata import version
from pathlib import Path

import numpy as np
from timezonefinder import TimezoneFinder


def build(step: float) -> bytes:
  tf = TimezoneFinder(in_memory=True)
  nlat, nlon = round(180 / step), round(360 / step)
  zones: dict[str, int] = {}
  runs = bytearray()
  for i in range(nlat):
    lat = 90 - (i + 0.5) * step
    row = np.array([zones.setdefault(tf.timezone_at(lat=lat, lng=-180 + (j + 0.5) * step) or "Etc/UTC", len(zones))
                    for j in range(nlon)], np.int32)
    starts = np.r_[0, np.flatnonzero(np.diff(row)) + 1]
    for s, e in zip(starts, np.r_[starts[1:], nlon], strict=True):
      n = int(e - s)
      while n:
        k = min(n, 255)
        runs += struct.pack("<BH", k, int(row[s]))
        n -= k
  head = {"step": step, "zones": list(zones), "src": f"timezonefinder_data {version('timezonefinder_data')}"}
  return zlib.compress(json.dumps(head, separators=(",", ":")).encode() + b"\n" + bytes(runs), 9)


if __name__ == "__main__":
  out = Path(__file__).with_name("tzgrid.bin")
  out.write_bytes(build(float(sys.argv[1]) if len(sys.argv) > 1 else 0.05))
  print(out, out.stat().st_size, "bytes")
