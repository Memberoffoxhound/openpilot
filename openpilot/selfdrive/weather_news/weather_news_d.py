#!/usr/bin/env python3
"""
S3XYPilot Weather Lady + Elon news — full integration for Highland / Comma 4.

Behavior
--------
- Always-running process (previews work offroad).
- Daily cycle only on the **first drive of the day** (WeatherNewsLastRunDate).
- 10 s after onroad, one weather + news cycle.
- Preview: write WeatherNewsPreview = "personable" | "aggressive" (deviceweb / ssh).
- Master toggle WeatherNewsEnable (default on).
- Mode toggle WeatherNewsAggressive (default off = personable).

Voice (best practical Ara-style on device)
------------------------------------------
- Personable: warmer, slightly slower female espeak voice.
- Aggressive (Ara / MF'n): faster, lower, rougher delivery + foul scripts.
True neural Ara voice is not on-device; personality lives in the scripts +
prosody. WAV is rendered then played via aplay for reliable C4 speaker output.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import traceback
from datetime import date
from pathlib import Path
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

ONROAD_DELAY_S = 10.0
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "S3XYPilot-WeatherNews/0.4"
PARAM_DIR = Path("/data/params/d")

# ---------- Params helpers (custom keys may not be in keys.h) ----------

def _param_path(name: str) -> Path:
  return PARAM_DIR / name


def get_str(name: str, default: str = "") -> str:
  try:
    p = Params()
    v = p.get(name)
    if v is not None and v != "":
      return str(v)
  except Exception:
    pass
  try:
    path = _param_path(name)
    if path.exists():
      return path.read_text().strip()
  except Exception:
    pass
  return default


def get_bool(name: str, default: bool = False) -> bool:
  v = get_str(name, "1" if default else "0").lower()
  return v in ("1", "true", "yes", "on")


def set_str(name: str, value: str) -> None:
  try:
    Params().put(name, value)
  except Exception:
    pass
  try:
    PARAM_DIR.mkdir(parents=True, exist_ok=True)
    _param_path(name).write_text(str(value))
  except Exception as e:
    cloudlog.warning(f"weather_news: could not write {name}: {e}")


# ---------- Location ----------

def location_from_cereal(sm: messaging.SubMaster) -> tuple[float, float, str]:
  """Prefer live GPS; fall back to last known / St. Louis."""
  try:
    if sm.recv_frame.get("gpsLocationExternal", 0) > 0:
      g = sm["gpsLocationExternal"]
      if getattr(g, "flags", 0) or getattr(g, "hasFix", False) or g.latitude != 0.0:
        return float(g.latitude), float(g.longitude), "your area"
  except Exception:
    pass
  try:
    if sm.recv_frame.get("liveLocationKalman", 0) > 0:
      llk = sm["liveLocationKalman"]
      pos = llk.positionGeodetic
      if pos.valid:
        return float(pos.value[0]), float(pos.value[1]), "your area"
  except Exception:
    pass
  try:
    import requests
    r = requests.get("https://ipapi.co/json/", timeout=4)
    j = r.json()
    return float(j["latitude"]), float(j["longitude"]), j.get("city", "your area")
  except Exception:
    return 38.63, -90.20, "St. Louis"


def fetch_weather(lat: float, lon: float) -> Optional[dict[str, Any]]:
  import requests
  params = {
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
    r = requests.get(OPEN_METEO, params=params, timeout=10, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    daily = r.json().get("daily", {})
    if not daily or not daily.get("time"):
      return None
    return {k: (v[0] if isinstance(v, list) and v else v) for k, v in daily.items()}
  except Exception as e:
    cloudlog.warning(f"weather_news: Open-Meteo failed: {e}")
    return None


# ---------- Ara-style voice ----------

def _which(bins: list[str]) -> Optional[str]:
  for b in bins:
    try:
      subprocess.check_call(["which", b], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      return b
    except Exception:
      continue
  return None


def speak(text: str, aggressive: bool = False) -> None:
  """Best on-device voice approximating Grok Ara personality via prosody + WAV play."""
  tag = "ARA/AGGRESSIVE" if aggressive else "PERSONABLE"
  cloudlog.info(f"weather_news [{tag}]: {text[:140]}...")
  print(f"\n===== WEATHER/NEWS [{tag}] =====\n{text}\n===== END =====\n")

  espeak = _which(["espeak-ng", "espeak"])
  if not espeak:
    cloudlog.warning("weather_news: no espeak-ng/espeak — text only")
    return

  # Ara: lower pitch, faster, denser. Personable: warmer female, slower.
  if aggressive:
    voice, pitch, speed, amp, gap = "en-us+m3", "26", "178", "200", "3"
  else:
    voice, pitch, speed, amp, gap = "en-us+f3", "58", "142", "170", "7"

  wav_path = None
  try:
    fd, wav_path = tempfile.mkstemp(prefix="wxnews_", suffix=".wav")
    os.close(fd)
    cmd = [
      espeak, "-v", voice, "-p", pitch, "-s", speed, "-a", amp, "-g", gap,
      "-w", wav_path, text,
    ]
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)

    player = _which(["aplay", "paplay", "ffplay"])
    if player == "aplay":
      subprocess.run(["aplay", "-q", wav_path], check=False, timeout=90)
    elif player == "paplay":
      subprocess.run(["paplay", wav_path], check=False, timeout=90)
    elif player == "ffplay":
      subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", wav_path], check=False, timeout=90)
    else:
      # last resort: direct speak (may overlap poorly)
      subprocess.run(
        [espeak, "-v", voice, "-p", pitch, "-s", speed, "-a", amp, "-g", gap, text],
        check=False, timeout=60,
      )
  except Exception as e:
    cloudlog.warning(f"weather_news speak failed: {e}")
  finally:
    if wav_path:
      try:
        os.unlink(wav_path)
      except OSError:
        pass


def run_full_cycle(aggressive: bool, lat: float, lon: float, loc_name: str) -> None:
  day = fetch_weather(lat, lon)
  if day:
    script = generate_forecast_script(day, aggressive=aggressive, location_name=loc_name)
    overnight = generate_overnight_note(day, aggressive=aggressive)
    speak(f"{script} {overnight}", aggressive=aggressive)
  else:
    msg = (
      "Weather data is being a little bitch right now. Skipping the forecast."
      if aggressive else
      "Weather data is being shy right now. Skipping the forecast."
    )
    speak(msg, aggressive)

  time.sleep(0.8)
  for bite in get_news_cycle(num_bites=2, aggressive=aggressive):
    speak(bite, aggressive=aggressive)
    time.sleep(0.6)


def handle_preview(sm: messaging.SubMaster) -> bool:
  preview = get_str("WeatherNewsPreview", "").lower().strip()
  if preview not in ("personable", "aggressive"):
    return False
  cloudlog.info(f"weather_news: preview requested → {preview}")
  aggressive = preview == "aggressive"
  lat, lon, loc = location_from_cereal(sm)
  run_full_cycle(aggressive, lat, lon, loc)
  set_str("WeatherNewsPreview", "")
  return True


def is_onroad(params: Params, sm: messaging.SubMaster) -> bool:
  try:
    if params.get_bool("IsOffroad"):
      return False
  except Exception:
    pass
  try:
    if sm.recv_frame.get("deviceState", 0) > 0:
      ds = sm["deviceState"]
      if hasattr(ds, "started") and ds.started:
        return True
  except Exception:
    pass
  try:
    if sm.recv_frame.get("selfdriveState", 0) > 0:
      return True
  except Exception:
    pass
  return False


def main() -> None:
  cloudlog.info("weather_news: v0.4 full integration (first-drive + Ara wav voice)")
  params = Params()
  sm = messaging.SubMaster([
    "deviceState",
    "selfdriveState",
    "carState",
    "gpsLocationExternal",
    "liveLocationKalman",
  ])
  rk = Ratekeeper(1.0, print_delay_threshold=None)

  while True:
    try:
      sm.update(0)

      if handle_preview(sm):
        time.sleep(2)
        continue

      if not get_bool("WeatherNewsEnable", default=True):
        time.sleep(20)
        continue

      today = date.today().isoformat()
      if get_str("WeatherNewsLastRunDate", "") == today:
        time.sleep(30)
        continue

      if not is_onroad(params, sm):
        rk.keep_time()
        continue

      cloudlog.info(f"weather_news: first drive of {today} — waiting {ONROAD_DELAY_S}s")
      time.sleep(ONROAD_DELAY_S)

      sm.update(0)
      if not get_bool("WeatherNewsEnable", default=True):
        continue
      if get_str("WeatherNewsLastRunDate", "") == today:
        continue
      if not is_onroad(params, sm):
        continue

      aggressive = get_bool("WeatherNewsAggressive", default=False)
      lat, lon, loc = location_from_cereal(sm)
      cloudlog.info(f"weather_news: running daily cycle aggressive={aggressive} loc={loc}")
      run_full_cycle(aggressive, lat, lon, loc)
      set_str("WeatherNewsLastRunDate", today)
      cloudlog.info("weather_news: daily cycle complete")

      time.sleep(30)

    except KeyboardInterrupt:
      break
    except Exception:
      cloudlog.exception("weather_news loop error")
      traceback.print_exc()
      time.sleep(15)


if __name__ == "__main__":
  main()
