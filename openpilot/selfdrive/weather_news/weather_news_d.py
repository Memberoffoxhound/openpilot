#!/usr/bin/env python3
"""
S3XYPilot Weather Lady + Elon news — Highland / Comma 4.

- Mode: WeatherNewsMode 0=off 1=nice 2=aggressive (Unhinged in UI).
- First drive of the Chicago-local day, ~10s after onroad is stable.
- Preview: WeatherNewsPreview = personable|aggressive. Does not consume the day.
- Speech goes through soundd (not aplay).
"""

from __future__ import annotations

import os
import time
import traceback
from datetime import datetime
from typing import Any, Optional

os.environ.setdefault("PYTHONPATH", "/data/openpilot")

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.realtime import Ratekeeper

from openpilot.selfdrive.weather_news.weather_lady import (
  generate_forecast_script,
  generate_overnight_note,
)
from openpilot.selfdrive.weather_news.news_bites import get_news_cycle
from openpilot.selfdrive.weather_news.voice import speak_lines

ONROAD_DELAY_S = 10.0
ONROAD_STABLE_S = 2.0
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "S3XYPilot-WeatherNews/0.5"
CHICAGO = "America/Chicago"

MODE_OFF = 0
MODE_NICE = 1
MODE_AGGRESSIVE = 2


def chicago_day() -> str:
  try:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(CHICAGO)).date().isoformat()
  except Exception:
    return datetime.now().date().isoformat()


def get_mode(params: Params) -> int:
  try:
    v = params.get("WeatherNewsMode", return_default=True)
    if v is not None:
      return max(MODE_OFF, min(MODE_AGGRESSIVE, int(v)))
  except Exception:
    pass
  return MODE_NICE


def set_str(params: Params, name: str, value: str) -> None:
  try:
    params.put(name, value, block=True)
  except Exception as e:
    cloudlog.warning(f"weather_news: could not write {name}: {e}")


def get_str(params: Params, name: str, default: str = "") -> str:
  try:
    v = params.get(name)
    if v is not None and v != "":
      return str(v)
  except Exception:
    pass
  return default


def is_onroad(params: Params, sm: messaging.SubMaster) -> bool:
  try:
    if params.get_bool("IsOffroad"):
      return False
  except Exception:
    pass
  try:
    if sm.recv_frame.get("deviceState", 0) > 0:
      return bool(sm["deviceState"].started)
  except Exception:
    pass
  return False


def wait_onroad(params: Params, sm: messaging.SubMaster, seconds: float) -> bool:
  deadline = time.time() + seconds
  while time.time() < deadline:
    sm.update(0)
    if get_str(params, "WeatherNewsPreview", "").strip():
      return False
    if not is_onroad(params, sm):
      return False
    time.sleep(0.4)
  return True


def idle_until_preview(params: Params, sm: messaging.SubMaster, seconds: float) -> None:
  deadline = time.time() + seconds
  while time.time() < deadline:
    sm.update(0)
    if get_str(params, "WeatherNewsPreview", "").strip():
      return
    time.sleep(0.4)


def _parse_latlon(raw: str) -> Optional[tuple[float, float]]:
  try:
    raw = raw.strip()
    if raw.startswith("{"):
      import json
      j = json.loads(raw)
      return float(j["latitude"]), float(j["longitude"])
    a, b = raw.split(",", 1)
    return float(a), float(b)
  except Exception:
    return None


def location_from_cereal(sm: messaging.SubMaster, params: Params) -> tuple[float, float, str]:
  try:
    if sm.recv_frame.get("gpsLocationExternal", 0) > 0:
      g = sm["gpsLocationExternal"]
      lat, lon = float(g.latitude), float(g.longitude)
      if lat != 0.0 or lon != 0.0:
        try:
          params.put("LastGPSPosition", f"{lat:.5f},{lon:.5f}")
        except Exception:
          pass
        return lat, lon, "your area"
  except Exception:
    pass
  cached = _parse_latlon(get_str(params, "LastGPSPosition", ""))
  if cached:
    return cached[0], cached[1], "your area"
  try:
    import requests
    r = requests.get("https://ipapi.co/json/", timeout=4)
    j = r.json()
    return float(j["latitude"]), float(j["longitude"]), j.get("city", "your area")
  except Exception:
    return 38.63, -90.20, "St. Louis"


def fetch_weather(lat: float, lon: float) -> Optional[dict[str, Any]]:
  import requests
  q = {
    "latitude": lat,
    "longitude": lon,
    "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,"
             "precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
    "timezone": "auto",
    "temperature_unit": "fahrenheit",
    "wind_speed_unit": "mph",
    "precipitation_unit": "inch",
    "forecast_days": 1,
  }
  try:
    r = requests.get(OPEN_METEO, params=q, timeout=10, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    daily = r.json().get("daily", {})
    if not daily or not daily.get("time"):
      return None
    return {k: (v[0] if isinstance(v, list) and v else v) for k, v in daily.items()}
  except Exception as e:
    cloudlog.warning(f"weather_news: Open-Meteo failed: {e}")
    return None


def build_lines(aggressive: bool, lat: float, lon: float, loc_name: str) -> list[str]:
  lines: list[str] = []
  day = fetch_weather(lat, lon)
  if day:
    lines.append(generate_forecast_script(day, aggressive=aggressive, location_name=loc_name))
    lines.append(generate_overnight_note(day, aggressive=aggressive))
  else:
    lines.append(
      "Weather data is being a little bitch right now. Skipping the forecast."
      if aggressive else
      "Weather data is being shy right now. Skipping the forecast."
    )
  lines.extend(get_news_cycle(num_bites=2, aggressive=aggressive))
  return lines


def run_cycle(aggressive: bool, lat: float, lon: float, loc_name: str) -> bool:
  lines = build_lines(aggressive, lat, lon, loc_name)
  return speak_lines(lines, aggressive=aggressive)


def handle_preview(params: Params, sm: messaging.SubMaster) -> bool:
  preview = get_str(params, "WeatherNewsPreview", "").lower().strip()
  if preview in ("nice", "personable"):
    aggressive = False
  elif preview in ("unhinged", "aggressive"):
    aggressive = True
  else:
    return False
  cloudlog.info(f"weather_news: preview requested → {preview}")
  set_str(params, "WeatherNewsPreview", "")
  lat, lon, loc = location_from_cereal(sm, params)
  ok = run_cycle(aggressive, lat, lon, loc)
  cloudlog.info(f"weather_news: preview queued={ok}")
  return True


def main() -> None:
  cloudlog.info("weather_news: v0.5 soundd path + Off/Nice/Unhinged")
  params = Params()
  sm = messaging.SubMaster([
    "deviceState",
    "gpsLocationExternal",
  ])
  rk = Ratekeeper(1.0, print_delay_threshold=None)
  stable_t: float | None = None

  while True:
    try:
      sm.update(0)

      if handle_preview(params, sm):
        time.sleep(1)
        continue

      mode = get_mode(params)
      if mode == MODE_OFF:
        stable_t = None
        idle_until_preview(params, sm, 15)
        continue

      today = chicago_day()
      if get_str(params, "WeatherNewsLastRunDate", "") == today:
        stable_t = None
        idle_until_preview(params, sm, 30)
        continue

      if not is_onroad(params, sm):
        stable_t = None
        rk.keep_time()
        continue

      if stable_t is None:
        stable_t = time.time()
      if time.time() - stable_t < ONROAD_STABLE_S:
        rk.keep_time()
        continue

      cloudlog.info(f"weather_news: first drive of {today} — waiting {ONROAD_DELAY_S}s")
      if not wait_onroad(params, sm, ONROAD_DELAY_S):
        stable_t = None
        continue

      if get_mode(params) == MODE_OFF:
        continue
      if get_str(params, "WeatherNewsLastRunDate", "") == today:
        continue
      if not is_onroad(params, sm):
        stable_t = None
        continue

      mode = get_mode(params)
      aggressive = mode == MODE_AGGRESSIVE
      lat, lon, loc = location_from_cereal(sm, params)
      cloudlog.info(f"weather_news: running daily cycle aggressive={aggressive} loc={loc}")
      ok = run_cycle(aggressive, lat, lon, loc)
      if ok:
        set_str(params, "WeatherNewsLastRunDate", today)
        cloudlog.info("weather_news: daily cycle queued to soundd")
      else:
        cloudlog.warning("weather_news: cycle did not queue audio — will retry")
      time.sleep(20)

    except KeyboardInterrupt:
      break
    except Exception:
      cloudlog.exception("weather_news loop error")
      traceback.print_exc()
      time.sleep(15)


if __name__ == "__main__":
  main()
