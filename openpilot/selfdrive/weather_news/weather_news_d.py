#!/usr/bin/env python3
"""3x/day briefing (morning / afternoon / after 7pm), never stacked. Grok + Ara TTS."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

from openpilot.selfdrive.weather_news import config as grok_cfg
from openpilot.selfdrive.weather_news import grok as grok_api
from openpilot.selfdrive.weather_news import mode as wx
from openpilot.selfdrive.weather_news.news_bites import fetch_rss_items
from openpilot.selfdrive.weather_news.voice import speak_lines

ONROAD_DELAY_S = 10.0
ONROAD_STABLE_S = 2.0
OFFROAD_RESET_S = 8.0
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "S3XYPilot-WeatherNews/0.9"
MORNING_START = 5
AFTERNOON_START = 12
EVENING_START = 19  # 7pm


def local_dt(lon: float) -> datetime:
  hours = max(-12, min(14, int(round(float(lon) / 15.0))))
  return datetime.now(timezone(timedelta(hours=hours)))


def local_day(lon: float) -> str:
  return local_dt(lon).date().isoformat()


def briefing_slot(lon: float) -> tuple[str, str]:
  """One window at a time. Evening before 5am belongs to the previous calendar day.

  Morning 5:00–11:59, afternoon 12:00–18:59, evening 19:00–04:59.
  Missed windows stay missed — never stacked.
  """
  dt = local_dt(lon)
  h = dt.hour
  if h < MORNING_START:
    day = (dt.date() - timedelta(days=1)).isoformat()
    return day, "evening"
  day = dt.date().isoformat()
  if h < AFTERNOON_START:
    return day, "morning"
  if h < EVENING_START:
    return day, "afternoon"
  return day, "evening"


def slot_key(lon: float) -> str:
  day, slot = briefing_slot(lon)
  return f"{day}:{slot}"


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


def on_wifi(sm: messaging.SubMaster) -> bool:
  try:
    return int(sm["deviceState"].networkType) == 1
  except Exception:
    return True


def peek_preview(params: Params) -> str:
  return _str(params, "WeatherNewsPreview").strip().lower()


def poll(params: Params, sm: messaging.SubMaster, seconds: float, *, need_onroad: bool) -> bool:
  deadline = time.time() + seconds
  while time.time() < deadline:
    sm.update(0)
    if peek_preview(params) or grok_cfg.ondemand():
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
        return lat, lon, ""
  except Exception:
    pass
  raw = _str(params, "LastGPSPosition")
  if raw:
    try:
      a, b = raw.split(",", 1)
      return float(a), float(b), ""
    except Exception:
      pass
  try:
    import requests
    j = requests.get("https://ipapi.co/json/", timeout=4).json()
    lat, lon = float(j["latitude"]), float(j["longitude"])
    _put(params, "LastGPSPosition", f"{lat:.5f},{lon:.5f}")
    return lat, lon, j.get("city") or ""
  except Exception:
    return None


def reverse_place(lat: float, lon: float, fallback: str = "") -> str:
  import requests
  try:
    r = requests.get(
      NOMINATIM,
      params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12, "addressdetails": 1},
      timeout=4, headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    a = (r.json().get("address") or {})
    city = a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or a.get("county")
    state = a.get("state") or a.get("region")
    if city and state:
      return f"{city}, {state}"
    return city or state or fallback or "your area"
  except Exception as e:
    cloudlog.warning(f"weather_news: reverse geo failed: {e}")
    return fallback or "your area"


def fetch_weather(lat: float, lon: float) -> dict[str, Any] | None:
  import requests
  q = {
    "latitude": lat, "longitude": lon,
    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
               "wind_speed_10m,precipitation,cloud_cover",
    "hourly": "temperature_2m,precipitation_probability,weather_code,precipitation",
    "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,"
             "precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
    "timezone": "auto", "temperature_unit": "fahrenheit",
    "wind_speed_unit": "mph", "precipitation_unit": "inch", "forecast_days": 1,
  }
  try:
    r = requests.get(OPEN_METEO, params=q, timeout=10, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    j = r.json()
    cur = j.get("current") or {}
    daily = j.get("daily") or {}
    hourly = j.get("hourly") or {}
    today = {k: (v[0] if isinstance(v, list) and v else v) for k, v in daily.items()}
    hours: list[dict[str, Any]] = []
    times = hourly.get("time") or []
    now_s = str(cur.get("time") or "")
    for i, t in enumerate(times):
      if now_s and t < now_s:
        continue
      hours.append({
        "time": t,
        "temp_f": (hourly.get("temperature_2m") or [None])[i] if i < len(hourly.get("temperature_2m") or []) else None,
        "precip_chance": (hourly.get("precipitation_probability") or [None])[i]
        if i < len(hourly.get("precipitation_probability") or []) else None,
        "precip_in": (hourly.get("precipitation") or [None])[i] if i < len(hourly.get("precipitation") or []) else None,
        "weather_code": (hourly.get("weather_code") or [None])[i] if i < len(hourly.get("weather_code") or []) else None,
      })
      if len(hours) >= 8:
        break
    if not cur and not today:
      return None
    return {
      "current": {
        "time": cur.get("time"),
        "temp_f": cur.get("temperature_2m"),
        "feels_like_f": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind_mph": cur.get("wind_speed_10m"),
        "precip_in": cur.get("precipitation"),
        "cloud_cover": cur.get("cloud_cover"),
        "weather_code": cur.get("weather_code"),
      },
      "today": {
        "high_f": today.get("temperature_2m_max"),
        "low_f": today.get("temperature_2m_min"),
        "sunrise": today.get("sunrise"),
        "sunset": today.get("sunset"),
        "precip_in": today.get("precipitation_sum"),
        "precip_chance": today.get("precipitation_probability_max"),
        "wind_max_mph": today.get("wind_speed_10m_max"),
        "weather_code": today.get("weather_code"),
      },
      "next_hours": hours,
      "timezone": j.get("timezone"),
      "utc_offset_seconds": j.get("utc_offset_seconds"),
    }
  except Exception as e:
    cloudlog.warning(f"weather_news: Open-Meteo failed: {e}")
    return None


def _local_clock(lon: float, weather: dict[str, Any] | None) -> str:
  offset = None if not weather else weather.get("utc_offset_seconds")
  try:
    if offset is not None:
      dt = datetime.now(timezone(timedelta(seconds=int(offset))))
    else:
      dt = local_dt(lon)
  except Exception:
    dt = local_dt(lon)
  h = dt.hour % 12 or 12
  ampm = "AM" if dt.hour < 12 else "PM"
  return f"{dt.strftime('%A')} {h}:{dt.strftime('%M')} {ampm}"


def already_ran(params: Params, loc: tuple[float, float, str], ran_this_onroad: bool) -> bool:
  if grok_cfg.every_drive():
    return ran_this_onroad
  return _str(params, "WeatherNewsLastRunDate") == slot_key(loc[1])


def build_and_speak(params: Params, aggressive: bool, loc: tuple[float, float, str] | None,
                    sm: messaging.SubMaster | None = None, window: str = "") -> bool:
  if not grok_cfg.voice_enabled():
    _put(params, "WeatherNewsStatus", "enable grok")
    time.sleep(1.2)
    _put(params, "WeatherNewsStatus", "")
    return False
  if not grok_cfg.configured():
    _put(params, "WeatherNewsStatus", "scan QR")
    time.sleep(1.5)
    _put(params, "WeatherNewsStatus", "")
    return False
  if grok_cfg.wifi_only() and sm is not None and not on_wifi(sm):
    _put(params, "WeatherNewsStatus", "wifi only")
    time.sleep(1.5)
    _put(params, "WeatherNewsStatus", "")
    return False

  lat = lon = None
  name = "your area"
  if loc:
    lat, lon, name = loc[0], loc[1], (loc[2] or "")
    if not window:
      _, window = briefing_slot(lon)
    _put(params, "WeatherNewsStatus", "finding location")
    name = reverse_place(lat, lon, fallback=name)
  clock = _local_clock(lon or 0.0, None)

  _put(params, "WeatherNewsStatus", "fetching weather")
  day = fetch_weather(lat, lon) if lat is not None and lon is not None else None
  if day:
    clock = _local_clock(lon or 0.0, day)
  _put(params, "WeatherNewsStatus", "getting news")
  news = fetch_rss_items(grok_cfg.topics())

  _put(params, "WeatherNewsStatus", "asking grok")
  script = grok_api.write_script(
    day, news, unhinged=aggressive, location_name=name or "your area",
    lat=lat, lon=lon, local_time=clock, window=window,
  )
  if not script:
    cloudlog.warning("weather_news: grok chat missed")
    _put(params, "WeatherNewsStatus", "failed")
    time.sleep(2.0)
    _put(params, "WeatherNewsStatus", "")
    return False

  ok = speak_lines(
    [script], aggressive=aggressive, on_status=lambda m: _put(params, "WeatherNewsStatus", m),
  )
  b = grok_api.last_bytes()
  total = b.get("chat", 0) + b.get("tts", 0)
  cloudlog.info(
    f"weather_news: lte chat={b.get('chat', 0)/1024:.1f}kB tts={b.get('tts', 0)/1048576:.2f}MB "
    f"total={total/1048576:.2f}MB queued={ok} place={name!r} window={window} t={clock}"
  )
  _put(params, "WeatherNewsStatus", "playing" if ok else "failed")
  time.sleep(1.5 if ok else 2.5)
  _put(params, "WeatherNewsStatus", "")
  return ok


def handle_preview(params: Params, sm: messaging.SubMaster) -> bool:
  preview = peek_preview(params)
  if preview == "nice":
    aggressive = False
  elif preview == "aggressive":
    aggressive = True
  else:
    return False
  _put(params, "WeatherNewsPreview", "")
  if not grok_cfg.voice_enabled():
    _put(params, "WeatherNewsStatus", "enable grok")
    time.sleep(1.2)
    _put(params, "WeatherNewsStatus", "")
    return True
  if not grok_cfg.configured():
    _put(params, "WeatherNewsStatus", "scan QR")
    time.sleep(1.5)
    _put(params, "WeatherNewsStatus", "")
    return True
  if grok_cfg.wifi_only() and not on_wifi(sm):
    _put(params, "WeatherNewsStatus", "wifi only")
    time.sleep(1.5)
    _put(params, "WeatherNewsStatus", "")
    return True
  _put(params, "WeatherNewsStatus", "asking grok")
  line = grok_api.write_preview(unhinged=aggressive)
  if not line:
    _put(params, "WeatherNewsStatus", "failed")
    time.sleep(2.0)
    _put(params, "WeatherNewsStatus", "")
    return True
  ok = speak_lines([line], aggressive=aggressive, on_status=lambda m: _put(params, "WeatherNewsStatus", m))
  _put(params, "WeatherNewsStatus", "playing" if ok else "failed")
  time.sleep(1.2 if ok else 2.0)
  _put(params, "WeatherNewsStatus", "")
  cloudlog.info(f"weather_news: preview queued={ok}")
  return True


def handle_ondemand(params: Params, sm: messaging.SubMaster) -> bool:
  if not grok_cfg.ondemand():
    return False
  grok_cfg.clear_ondemand()
  if not grok_cfg.voice_enabled():
    _put(params, "WeatherNewsStatus", "enable grok")
    time.sleep(1.0)
    _put(params, "WeatherNewsStatus", "")
    return True
  if not grok_cfg.configured():
    _put(params, "WeatherNewsStatus", "scan QR")
    time.sleep(1.2)
    _put(params, "WeatherNewsStatus", "")
    return True
  m = wx.get(params)
  loc = location(sm, params)
  window = briefing_slot(loc[1])[1] if loc else ""
  ok = build_and_speak(params, m == wx.AGGRESSIVE, loc, sm, window=window)
  cloudlog.info(f"weather_news: ondemand queued={ok}")
  return True


def main() -> None:
  cloudlog.info("weather_news: start")
  params = Params()
  sm = messaging.SubMaster(["deviceState", "gpsLocationExternal"])
  stable_t: float | None = None
  ran_this_onroad = False
  offroad_since = 0.0

  while True:
    try:
      sm.update(0)
      if handle_preview(params, sm):
        continue
      if handle_ondemand(params, sm):
        continue

      m = wx.get(params)
      if m == wx.OFF or not grok_cfg.voice_enabled():
        stable_t = None
        poll(params, sm, 15, need_onroad=False)
        continue

      loc = location(sm, params)
      if loc is None:
        poll(params, sm, 5, need_onroad=False)
        continue

      if not onroad(sm):
        stable_t = None
        if ran_this_onroad:
          if not offroad_since:
            offroad_since = time.time()
          elif time.time() - offroad_since >= OFFROAD_RESET_S:
            ran_this_onroad = False
            offroad_since = 0.0
        else:
          offroad_since = 0.0
        time.sleep(0.5)
        continue

      offroad_since = 0.0
      key = slot_key(loc[1])
      if already_ran(params, loc, ran_this_onroad):
        stable_t = None
        poll(params, sm, 30, need_onroad=False)
        continue

      if stable_t is None:
        stable_t = time.time()
      if time.time() - stable_t < ONROAD_STABLE_S:
        time.sleep(0.4)
        continue

      day, slot = briefing_slot(loc[1])
      cloudlog.info(
        f"weather_news: drive {key} every={int(grok_cfg.every_drive())} "
        f"lon={loc[1]:.2f}, waiting {ONROAD_DELAY_S:.0f}s"
      )
      if not poll(params, sm, ONROAD_DELAY_S, need_onroad=True):
        stable_t = None
        continue

      loc = location(sm, params) or loc
      key = slot_key(loc[1])
      day, slot = briefing_slot(loc[1])
      m = wx.get(params)
      if m == wx.OFF or not grok_cfg.voice_enabled() or already_ran(params, loc, ran_this_onroad) or not onroad(sm):
        stable_t = None
        continue

      ok = build_and_speak(params, m == wx.AGGRESSIVE, loc, sm, window=slot)
      if ok:
        ran_this_onroad = True
        _put(params, "WeatherNewsLastRunDate", key)
        cloudlog.info(f"weather_news: briefing queued slot={key}")
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
