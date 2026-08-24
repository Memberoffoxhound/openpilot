#!/usr/bin/env python3
"""
Alpha process: Weather Lady + Elon news for S3XYPilot Highland / Comma 4.

- Runs only on the first drive of the day (WeatherNewsLastRunDate param).
- 10 s delay after onroad, then one weather + news cycle.
- Preview: set WeatherNewsPreview=personable|aggressive for instant sample.
- Toggles: WeatherNewsEnable, WeatherNewsAggressive
"""

import os
import time
import traceback
from datetime import date
from typing import Optional, Dict, Any

import requests

from weather_lady import generate_forecast_script, generate_overnight_note
from news_bites import get_news_cycle

ONROAD_DELAY_S = 10.0
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "S3XYPilot-WeatherNews-Alpha/0.2"


def get_param(name: str, default: str = "") -> str:
    env = os.environ.get(name.upper())
    if env is not None:
        return env
    try:
        path = f"/data/params/d/{name}"
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return default


def get_params_toggle(name: str, default: bool = False) -> bool:
    val = get_param(name, "1" if default else "0")
    return val.lower() in ("1", "true", "yes", "on")


def set_param(name: str, value: str):
    try:
        path = f"/data/params/d/{name}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(value))
    except Exception as e:
        print(f"[weather_news] could not write param {name}: {e}")


def fetch_weather(lat: float, lon: float, timezone: str = "auto") -> Optional[Dict[str, Any]]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "timezone": timezone,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "forecast_days": 1,
    }
    try:
        r = requests.get(OPEN_METEO, params=params, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
        daily = data.get("daily", {})
        if not daily or not daily.get("time"):
            return None
        day = {k: (v[0] if isinstance(v, list) and v else v) for k, v in daily.items()}
        return day
    except Exception as e:
        print(f"[weather_news] Open-Meteo failed: {e}")
        return None


def get_location_fallback() -> tuple:
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        j = r.json()
        return float(j["latitude"]), float(j["longitude"]), j.get("city", "your area")
    except Exception:
        return 38.63, -90.20, "St. Louis"


def speak(text: str, aggressive: bool = False):
    tag = "AGGRESSIVE" if aggressive else "PERSONABLE"
    print(f"\n===== WEATHER/NEWS [{tag}] =====")
    print(text)
    print("===== END =====\n")
    try:
        import subprocess
        voice = "en+f3" if not aggressive else "en+m3"
        subprocess.Popen(["espeak", "-v", voice, "-s", "150", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def is_onroad() -> bool:
    if os.environ.get("ONROAD", "1") == "1":
        return True
    return True  # TODO: cereal SubMaster carState / selfdriveState


def run_full_cycle(aggressive: bool, loc_name: str, lat: float, lon: float):
    day = fetch_weather(lat, lon)
    if day:
        script = generate_forecast_script(day, aggressive=aggressive, location_name=loc_name)
        overnight = generate_overnight_note(day, aggressive=aggressive)
        speak(f"{script} {overnight}", aggressive=aggressive)
    else:
        speak("Weather data is being shy right now. Skipping the forecast.", aggressive)

    time.sleep(1.5)
    bites = get_news_cycle(num_bites=2, aggressive=aggressive)
    for b in bites:
        speak(b, aggressive=aggressive)
        time.sleep(1.2)


def handle_preview() -> bool:
    preview = get_param("WeatherNewsPreview", "").lower()
    if preview not in ("personable", "aggressive"):
        return False
    print(f"[weather_news] Preview requested: {preview}")
    aggressive = preview == "aggressive"
    lat, lon, loc_name = get_location_fallback()
    run_full_cycle(aggressive, loc_name, lat, lon)
    set_param("WeatherNewsPreview", "")
    return True


def main_loop():
    print("[weather_news] Alpha v0.2 starting (first-drive-of-day + preview)")
    while True:
        try:
            if handle_preview():
                time.sleep(5)
                continue
            if not get_params_toggle("WeatherNewsEnable", default=True):
                time.sleep(30)
                continue
            today = date.today().isoformat()
            last_run = get_param("WeatherNewsLastRunDate", "")
            if last_run == today:
                time.sleep(60)
                continue
            if not is_onroad():
                time.sleep(2)
                continue
            print(f"[weather_news] First drive of {today} detected. Waiting {ONROAD_DELAY_S}s ...")
            time.sleep(ONROAD_DELAY_S)
            if not get_params_toggle("WeatherNewsEnable", default=True):
                continue
            if get_param("WeatherNewsLastRunDate", "") == today:
                continue
            aggressive = get_params_toggle("WeatherNewsAggressive", default=False)
            lat, lon, loc_name = get_location_fallback()
            print(f"[weather_news] Running daily cycle (aggressive={aggressive})")
            run_full_cycle(aggressive, loc_name, lat, lon)
            set_param("WeatherNewsLastRunDate", today)
            print("[weather_news] Daily cycle complete. Next run tomorrow.")
            time.sleep(60)
        except KeyboardInterrupt:
            print("[weather_news] Shutting down.")
            break
        except Exception as e:
            print(f"[weather_news] Loop error: {e}")
            traceback.print_exc()
            time.sleep(30)


if __name__ == "__main__":
    main_loop()
