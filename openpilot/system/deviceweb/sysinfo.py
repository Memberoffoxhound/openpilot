"""Tiny CPU/mem helpers shared by deviceweb handlers."""
from __future__ import annotations

import os
from pathlib import Path

_cpu_last: tuple[int, int] | None = None


def cpu_pct() -> int | None:
  global _cpu_last
  try:
    with open("/proc/stat") as f:
      nums = [int(x) for x in f.readline().split()[1:8]]
    idle, total = nums[3] + nums[4], sum(nums)
    prev = _cpu_last
    _cpu_last = (idle, total)
    if prev is None:
      return cpu_pct()
    didle, dtotal = idle - prev[0], total - prev[1]
    if dtotal <= 0:
      return None
    return max(0, min(100, round(100.0 * (1.0 - didle / dtotal))))
  except Exception:
    return None


def mem_pct() -> int | None:
  try:
    vals: dict[str, int] = {}
    with open("/proc/meminfo") as f:
      for line in f:
        k, rest = line.split(":", 1)
        vals[k] = int(rest.strip().split()[0])
    total, avail = vals.get("MemTotal") or 0, vals.get("MemAvailable") or 0
    if total <= 0:
      return None
    return max(0, min(100, round(100.0 * (1.0 - avail / total))))
  except Exception:
    return None


def cpu_temp_c() -> int | None:
  temps: list[float] = []
  try:
    for name in os.listdir("/sys/class/thermal"):
      if not name.startswith("thermal_zone"):
        continue
      base = Path("/sys/class/thermal") / name
      try:
        kind = (base / "type").read_text().strip().lower()
        if "cpu" not in kind:
          continue
        temps.append(int((base / "temp").read_text().strip()) / 1000.0)
      except Exception:
        continue
  except Exception:
    return None
  if not temps:
    return None
  return round(sum(temps) / len(temps))
