"""The device's time zone for Day / Week: an IANA name in the Timezone param, found offline from the last GPS fix.

No Timezone yet, or a name this device's tzdata doesn't know: the system zone.
zone_at() reads tzgrid.bin (build_tzgrid.py): one zone per 0.05 degree cell, about 190 KB.
first_day() reads weekstart.json (build_weekstart.py): the zones whose week does not start Monday, about 3 KB.
"""
from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, tzinfo
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from openpilot.common.params_compat import get, put

PARAM = "Timezone"
GRID = Path(__file__).with_name("tzgrid.bin")
WEEK = Path(__file__).with_name("weekstart.json")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")    # index = date.weekday()
SUNDAY = 6


def zone_at(lat: float, lon: float, grid: Path = GRID) -> str:
  """IANA zone at lat / lon. Accurate except within a few km of a zone border."""
  head, runs = zlib.decompress(grid.read_bytes()).split(b"\n", 1)
  h = json.loads(head)
  step = h["step"]
  nlat, nlon = round(180 / step), round(360 / step)
  target = min(max(int((90 - lat) / step), 0), nlat - 1) * nlon + int(((lon + 180) % 360) / step) % nlon
  pos = 0
  for n, z in struct.iter_unpack("<BH", runs):
    pos += n
    if pos > target:
      return h["zones"][z]
  raise ValueError("short grid")


@cache
def _week_table(path: Path = WEEK) -> tuple[dict[str, int], int]:
  t = json.loads(path.read_text())
  return {z: DAYS.index(d) for d, zs in t["zones"].items() for z in zs}, DAYS.index(t["default"])


def first_day(zone: tzinfo | str | None) -> int:
  """First day of the week where zone is (date.weekday(): 0 Monday .. 6 Sunday), from the country it is in.
  No zone (system zone), an Etc/ zone or a missing table: Sunday."""
  name = zone if isinstance(zone, str) else getattr(zone, "key", None) or ""
  try:
    table, default = _week_table()
  except Exception:
    return SUNDAY
  if name in table:
    return table[name]
  return default if "/" in name and not name.startswith("Etc/") else SUNDAY


def _name(params, key: str) -> str:
  v = get(params, key)
  return (v.decode(errors="replace") if isinstance(v, bytes) else v or "").strip()


def current(params) -> tuple[ZoneInfo | None, str, str]:
  """(zone, name, source): the GPS zone, else (None, abbreviation, "system")."""
  try:
    if name := _name(params, PARAM):
      return ZoneInfo(name), name, "gps"
  except Exception:
    pass
  return None, datetime.now().astimezone().tzname() or "", "system"


def zone(params) -> ZoneInfo | None:
  """The zone Day / Week use, or None for the system zone."""
  return current(params)[0]


def last_fix(params) -> tuple[float, float] | None:
  """(lat, lon) of LastGPSPosition, which ubloxd saves once a minute with a fix."""
  try:
    from openpilot.cereal import log
    with log.Event.from_bytes(get(params, "LastGPSPosition")) as evt:
      g = evt.gpsLocationExternal
      return (g.latitude, g.longitude) if g.latitude or g.longitude else None
  except Exception:
    return None


def update(params) -> str | None:
  """Timezone from the last GPS fix. Call off the UI thread (about 0.1 s). Returns the zone if it changed."""
  if (fix := last_fix(params)) is None:
    return None
  name = zone_at(*fix)
  if name != _name(params, PARAM):
    put(params, PARAM, name, name.encode())
    return name
  return None
