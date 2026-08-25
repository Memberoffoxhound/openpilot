#!/usr/bin/env python3
"""First drive of the local day (GPS): forecast + two news bites. Preview anytime."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

from openpilot.selfdrive.weather_news import mode as wx
from openpilot.selfdrive.weather_news.news_bites import get_news_cycle
from openpilot.selfdrive.weather_news.voice import speak_lines
from openpilot.selfdrive.weather_news.weather_lady import generate_forecast_script, generate_overnight_note, enjoy_your_drive, pay_attention

ONROAD_DELAY_S = 10.0
ONROAD_STABLE_S = 2.0
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "S3XYPilot-WeatherNews/0.5"


def local_day(lon: float) -> str:
  # C4 clock is UTC. 15° ≈ 1h. DST is ±1h; first drive of the day does not care.
  hours = max(-12, min(14, int(round(float(lon) / 15.0))))
  return datetime.now(timezone(timedelta(hours=hours))).date().isoformat()


def _str(params: Params, name: str, default: str = "") -> str:
  try:
    v = params.get(name)
    return str(v) if v else default
  except Exception:
    return default


def _put(params: Params, name: str, value: str) -> None:
  try:
    params.put(name, value, block=True)
  except Exception as e:
    cloudlog.warning(f"weather_news: write {name}: {e}")


def onroad(sm: messaging.SubMaster) -> bool:
  try:
    return sm.recv_frame.get("deviceState", 0) > 0 and bool(sm["deviceState"].started)
  except Exception:
    return False


def peek_preview(params: Params) -> str:
  return _str(params, "WeatherNewsPreview").strip().lower()


def poll(params: Params, sm: messaging.SubMaster, seconds: float, *, need_onroad: bool) -> bool:
  """Sleep up to `seconds`. False if preview arrives or (need_onroad and we drop offroad)."""
  deadline = time.time() + seconds
  while time.time() < deadline:
    sm.update(0)
    if peek_preview(params):
      return False
    if need_onroad and not onroad(sm):
      return False
    time.sleep(0.4)
  return True


def location(sm: messaging.SubMaster, params: Params) -> tuple[float, float, str] | None:
  try:
    if sm.recv_frame.get("gpsLocationExternal", 0) > 0:
      g = sm["gpsLocationExternal"]
      lat, lon = float(g.latitude), float(g.longitude)
      if lat or lon:
        _put(params, "LastGPSPosition", f"{lat:.5f},{lon:.5f}")
        return lat, lon, "your area"
  except Exception:
    pass
  raw = _str(params, "LastGPSPosition")
  if raw:
    try:
      a, b = raw.split(",", 1)
      return float(a), float(b), "your area"
    except Exception:
      pass
  try:
    import requests
    j = requests.get("https://ipapi.co/json/", timeout=4).json()
    lat, lon = float(j["latitude"]), float(j["longitude"])
    _put(params, "LastGPSPosition", f"{lat:.5f},{lon:.5f}")
    return lat, lon, j.get("city") or "your area"
  except Exception:
    return None


def fetch_weather(lat: float, lon: float) -> dict[str, Any] | None:
  import requests
  q = {
    "latitude": lat, "longitude": lon,
    "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,"
             "precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
    "timezone": "auto", "temperature_unit": "fahrenheit",
    "wind_speed_unit": "mph", "precipitation_unit": "inch", "forecast_days": 1,
  }
  try:
    r = requests.get(OPEN_METEO, params=q, timeout=10, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    daily = r.json().get("daily") or {}
    if not daily.get("time"):
      return None
    return {k: (v[0] if isinstance(v, list) and v else v) for k, v in daily.items()}
  except Exception as e:
    cloudlog.warning(f"weather_news: Open-Meteo failed: {e}")
    return None


def build_lines(aggressive: bool, loc: tuple[float, float, str] | None) -> list[str]:
  lines: list[str] = []
  day = fetch_weather(loc[0], loc[1]) if loc else None
  if day:
    name = loc[2] if loc else "your area"
    lines.append(generate_forecast_script(day, aggressive=aggressive, location_name=name))
    lines.append(generate_overnight_note(day, aggressive=aggressive))
  else:
    lines.append(
      "Weather data is being a little bitch right now. Skipping the forecast."
      if aggressive else
      "Weather data is being shy right now. Skipping the forecast."
    )
  lines.extend(get_news_cycle(num_bites=2, aggressive=aggressive))
  lines.append(enjoy_your_drive(aggressive=aggressive))
  lines.append(pay_attention(aggressive=aggressive))
  return lines


def run_cycle(aggressive: bool, loc: tuple[float, float, str] | None) -> bool:
  return speak_lines(build_lines(aggressive, loc), aggressive=aggressive)


def handle_preview(params: Params, sm: messaging.SubMaster) -> bool:
  preview = peek_preview(params)
  if preview == "nice":
    aggressive = False
  elif preview == "aggressive":
    aggressive = True
  else:
    return False
  _put(params, "WeatherNewsPreview", "")
  ok = run_cycle(aggressive, location(sm, params))
  cloudlog.info(f"weather_news: preview queued={ok}")
  return True


def main() -> None:
  cloudlog.info("weather_news: start")
  params = Params()
  sm = messaging.SubMaster(["deviceState", "gpsLocationExternal"])
  stable_t: float | None = None

  while True:
    try:
      sm.update(0)
      if handle_preview(params, sm):
        continue

      m = wx.get(params)
      if m == wx.OFF:
        stable_t = None
        poll(params, sm, 15, need_onroad=False)
        continue

      loc = location(sm, params)
      if loc is None:
        poll(params, sm, 5, need_onroad=False)
        continue

      today = local_day(loc[1])
      if _str(params, "WeatherNewsLastRunDate") == today:
        stable_t = None
        poll(params, sm, 30, need_onroad=False)
        continue

      if not onroad(sm):
        stable_t = None
        time.sleep(0.5)
        continue

      if stable_t is None:
        stable_t = time.time()
      if time.time() - stable_t < ONROAD_STABLE_S:
        time.sleep(0.4)
        continue

      cloudlog.info(f"weather_news: first drive {today} lon={loc[1]:.2f}, waiting {ONROAD_DELAY_S:.0f}s")
      if not poll(params, sm, ONROAD_DELAY_S, need_onroad=True):
        stable_t = None
        continue

      loc = location(sm, params) or loc
      today = local_day(loc[1])
      m = wx.get(params)
      if m == wx.OFF or _str(params, "WeatherNewsLastRunDate") == today or not onroad(sm):
        stable_t = None
        continue

      ok = run_cycle(m == wx.AGGRESSIVE, loc)
      if ok:
        _put(params, "WeatherNewsLastRunDate", today)
        cloudlog.info("weather_news: daily queued")
      else:
        cloudlog.warning("weather_news: no audio queued, will retry")
      time.sleep(5)

    except KeyboardInterrupt:
      break
    except Exception:
      cloudlog.exception("weather_news")
      time.sleep(15)


if __name__ == "__main__":
  main()
