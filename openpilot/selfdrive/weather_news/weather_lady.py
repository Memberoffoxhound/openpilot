#!/usr/bin/env python3
"""Spoken forecast. aggressive=True is Unhinged."""

import random
from typing import Any

# WMO weather codes
CLEAR = {0, 1}
CLOUDY = {2, 3}
FOG = {45, 48}
DRIZZLE = {51, 53, 55, 56, 57}
RAIN = {61, 63, 65, 66, 67, 80, 81, 82}
SNOW = {71, 73, 75, 77, 85, 86}
THUNDER = {95, 96, 99}

def categorize(code: int) -> str:
  if code in CLEAR:
    return "clear"
  if code in CLOUDY:
    return "cloudy"
  if code in FOG:
    return "fog"
  if code in DRIZZLE:
    return "drizzle"
  if code in RAIN:
    return "rain"
  if code in SNOW:
    return "snow"
  if code in THUNDER:
    return "thunder"
  return "mixed"


def _pick(templates: list[str], **kwargs) -> str:
  return random.choice(templates).format(**kwargs)


# nice
PERSONABLE_OPENERS = [
  "Hey there, your friendly weather lady checking in.",
  "Good morning drivers, or whatever time it is out there.",
  "Alright crew, let's talk about what Mother Nature has planned.",
  "Hi friends, time for your local forecast with a smile.",
]

PERSONABLE_CLEAR = [
  "It's looking absolutely gorgeous out there. High of {high}\u00b0, low overnight around {low}\u00b0. "
  "Sunset at {sunset}. Perfect day to enjoy the open road.",
  "Clear skies and sunshine all the way. We're talking a high near {high} and a comfortable overnight low of {low}. "
  "Sun drops at {sunset}. Make the most of it.",
]

PERSONABLE_CLOUDY = [
  "A bit overcast today with highs around {high}\u00b0. Overnight lows settling near {low}\u00b0. "
  "Sunset still on schedule at {sunset}. Not the prettiest, but drive safe.",
  "Cloudy cover keeping things mild. High {high}, overnight {low}. Sun sets at {sunset}.",
]

PERSONABLE_RAIN = [
  "Looks like some rain in the picture. Highs near {high}\u00b0, overnight down to {low}\u00b0. "
  "Precipitation chance up, sunset at {sunset}. Keep those wipers ready and leave extra following distance.",
  "Wet roads expected. High {high}, low {low}, sunset {sunset}. Take it easy out there, friends.",
]

PERSONABLE_SNOW = [
  "Winter wonderland alert. Highs only {high}\u00b0, overnight {low}\u00b0. "
  "Snow possible, sunset early at {sunset}. Slow down and watch the ice.",
]

PERSONABLE_HOT = [
  "It's a scorcher. Highs climbing to {high}\u00b0. Overnight still warm around {low}\u00b0. "
  "Sunset at {sunset}. Stay hydrated and don't leave pets or kids in the car.",
]

PERSONABLE_COLD = [
  "Bundle up. Highs struggling to {high}\u00b0, overnight dipping to {low}\u00b0. "
  "Sunset at {sunset}. Watch for black ice in the morning.",
]

PERSONABLE_CLOSERS = [
  "That's the outlook. Drive chill and I'll catch you next cycle.",
  "Stay safe out there. Weather lady out.",
  "Enjoy the ride, and keep an eye on the skies.",
]


# unhinged
AGGRESSIVE_OPENERS = [
  "Alright you beautiful bastards, your foul-mouthed weather bitch is here.",
  "Listen up you horny road warriors, time for the real fucking forecast.",
  "Yo, your favorite dirty weather lady checking in. Don't act surprised.",
  "MF'n weather update incoming. Brace your sensitive asses.",
]

AGGRESSIVE_CLEAR = [
  "Clear as a porn star's schedule. High of a sweaty {high}\u00b0, overnight a sticky {low}\u00b0. "
  "Sun drops its pants at {sunset}. Perfect day to get your rocks off on the open highway.",
  "Blue skies and zero excuses. High {high}, low {low}, sunset {sunset}. "
  "Go outside and do something that would make your mother blush.",
]

AGGRESSIVE_CLOUDY = [
  "Cloudy as your browser history. High around {high}\u00b0, overnight {low}\u00b0. "
  "Sunset at {sunset}. Not pretty, but neither are most of you after a long drive.",
  "Overcast and mildly depressing. {high} up top, {low} when the sun finally gives up at {sunset}.",
]

AGGRESSIVE_RAIN = [
  "It's gonna piss down. High {high}\u00b0, overnight {low}\u00b0. "
  "Rain chance is real, sunset at {sunset}. Your tires better have grip or you're gonna hydroplane like a drunk at a bachelor party.",
  "Wet as a... well, you get it. High {high}, low {low}, sun clocks out at {sunset}. "
  "Leave more space or eat shit, your choice.",
]

AGGRESSIVE_SNOW = [
  "Snow's coming, you poor frozen bastards. High a miserable {high}\u00b0, overnight {low}\u00b0. "
  "Sunset at {sunset}. Drive like your balls are made of glass.",
]

AGGRESSIVE_HOT = [
  "Hotter than two rats fucking in a wool sock. High {high}\u00b0 of pure ball-sweat weather. "
  "Overnight still a muggy {low}\u00b0. Sunset at {sunset}. "
  "If you're not careful your seat is gonna look like a crime scene.",
  "This heat will melt the chrome off a trailer hitch. {high}\u00b0 high, {low} overnight, sun dips at {sunset}. "
  "Stay hydrated or your dick will dry up and fall off. Science.",
]

AGGRESSIVE_COLD = [
  "Colder than a witch's tit in a brass bra. High only {high}\u00b0, overnight a ball-shriveling {low}\u00b0. "
  "Sunset at {sunset}. Warm up the car before you freeze your nipples off.",
]

AGGRESSIVE_CLOSERS = [
  "That's the dirty truth. Now go drive like you have a pair. Weather bitch out.",
  "Don't crash, I still need an audience. Later, degenerates.",
  "Keep it rubber side down, you magnificent assholes.",
]


def generate_forecast_script(
  data: dict[str, Any],
  aggressive: bool = False,
  location_name: str = "your area",
) -> str:
  code = int(data.get("weather_code", 0))
  high = round(float(data.get("temperature_2m_max", 70)))
  low = round(float(data.get("temperature_2m_min", 50)))
  sunset_raw = data.get("sunset", "19:00")
  if "T" in str(sunset_raw):
    sunset = sunset_raw.split("T")[1][:5]
  else:
    sunset = str(sunset_raw)[:5]

  cat = categorize(code)
  is_hot = high >= 88
  is_cold = high <= 45

  if aggressive:
    openers = AGGRESSIVE_OPENERS
    closers = AGGRESSIVE_CLOSERS
    if is_hot:
      body_pool = AGGRESSIVE_HOT
    elif is_cold:
      body_pool = AGGRESSIVE_COLD
    elif cat == "clear":
      body_pool = AGGRESSIVE_CLEAR
    elif cat in ("rain", "drizzle", "thunder"):
      body_pool = AGGRESSIVE_RAIN
    elif cat == "snow":
      body_pool = AGGRESSIVE_SNOW
    else:
      body_pool = AGGRESSIVE_CLOUDY
  else:
    openers = PERSONABLE_OPENERS
    closers = PERSONABLE_CLOSERS
    if is_hot:
      body_pool = PERSONABLE_HOT
    elif is_cold:
      body_pool = PERSONABLE_COLD
    elif cat == "clear":
      body_pool = PERSONABLE_CLEAR
    elif cat in ("rain", "drizzle", "thunder"):
      body_pool = PERSONABLE_RAIN
    elif cat == "snow":
      body_pool = PERSONABLE_SNOW
    else:
      body_pool = PERSONABLE_CLOUDY

  opener = _pick(openers)
  body = _pick(body_pool, high=high, low=low, sunset=sunset)
  closer = _pick(closers)

  loc_bit = ""
  if random.random() < 0.4:
    loc_bit = f" Here in {location_name}, "

  script = f"{opener} {loc_bit}{body} {closer}"
  return " ".join(script.split())


def generate_overnight_note(data: dict[str, Any], aggressive: bool = False) -> str:
  low = round(float(data.get("temperature_2m_min", 50)))
  precip = float(data.get("precipitation_sum", 0) or 0)
  if aggressive:
    if precip > 0.1:
      return f"Overnight that low of {low}\u00b0 is coming with some wet bullshit. Don't leave the windows down unless you want a swamp in your ride."
    return f"Overnight bottoms out around a chilly {low}\u00b0. Perfect for bad decisions and regrettable texts."
  else:
    if precip > 0.1:
      return f"Overnight low near {low}\u00b0 with a chance of more precipitation. Secure any outdoor gear."
    return f"Overnight low around {low}\u00b0. Should be a quiet night for most of us."
