#!/usr/bin/env python3
"""Builds weekstart.json, the IANA zone -> first day of the week table tz.py reads. Dev only, not run on the device:
  uv pip install tzdata && python build_weekstart.py [weekData.json]

First days come from Unicode CLDR supplemental weekData (firstDay by country; downloaded from cldr-json when no
file is given). Countries come from tzdata's zone.tab, which gives every land zone exactly one country. Only zones
in tzgrid.bin are listed, and only those that do not start on CLDR's world default (Monday). Zones that are not in
zone.tab (the Etc/ ocean zones) are left out, so they get the unknown-zone answer, Sunday.
"""
import json
import sys
import urllib.request
import zlib
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

HERE = Path(__file__).parent
CLDR = "https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-core/supplemental/weekData.json"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def build(week_data: dict, zone_tab: str, zones: list[str]) -> dict:
  first = {k: v for k, v in week_data["supplemental"]["weekData"]["firstDay"].items() if "-" not in k}
  country = {}
  for line in zone_tab.splitlines():
    if line and not line.startswith("#"):
      cc, _coords, name = line.split("\t")[:3]
      country[name] = cc
  default = first["001"]
  out: dict[str, list[str]] = {}
  for z in sorted(zones):
    if z in country and (day := first.get(country[z], default)) != default:
      out.setdefault(day, []).append(z)
  ver = week_data["supplemental"]["version"]["_cldrVersion"]
  return {"src": f"CLDR {ver} weekData, tzdata {version('tzdata')} zone.tab", "default": default, "unknown": "sun",
          "zones": {d: out[d] for d in DAYS if d in out}}


if __name__ == "__main__":
  if len(sys.argv) > 1:
    wd = json.loads(Path(sys.argv[1]).read_text())
  else:
    with urllib.request.urlopen(CLDR, timeout=30) as r:
      wd = json.load(r)
  head = json.loads(zlib.decompress((HERE / "tzgrid.bin").read_bytes()).split(b"\n", 1)[0])
  table = build(wd, files("tzdata").joinpath("zoneinfo", "zone.tab").read_text(), head["zones"])
  out = HERE / "weekstart.json"
  out.write_text(json.dumps(table, indent=0, separators=(",", ":")) + "\n")
  print(out, out.stat().st_size, "bytes")
