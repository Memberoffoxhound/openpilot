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
  "That's the outlook. I'll catch you next cycle.",
  "Stay safe out there. Weather lady out.",
  "Keep an eye on the skies.",
]

ENJOY_NICE = [
  "Enjoy your drive.",
  "Have a good drive.",
  "Enjoy the ride.",
  "Have a good one out there.",
  "Drive safe, and enjoy it.",
]

ENJOY_UNHINGED = [
  "Enjoy your drive.",
  "Enjoy your drive. Or don't.",
  "Have a good one. Try not to be an idiot.",
  "Enjoy the ride, you animal.",
  "Drive. Enjoy it. Don't die.",
]

PAY_ATTENTION_NICE = [
  "Pay attention out there.",
  "Keep your eyes on the road.",
  "Stay alert.",
  "Watch the road.",
  "Pay attention. You're still the driver.",
]

PAY_ATTENTION_UNHINGED = [
  "Pay attention. I'm not driving.",
  "Eyes on the road, dipshit.",
  "Pay attention or eat shit.",
  "You're still the driver. Act like it.",
  "Watch the fucking road.",
]


# unhinged — grok-style: normal cadence, foul, not a shock-jock bit
AGGRESSIVE_OPENERS = [
  "Alright. Unhinged forecast. If you wanted nice, you picked the wrong fucking mode.",
  "Weather. I'm not holding your hand.",
  "Sit down. Here's the sky, you impatient bitch.",
  "Forecast. Try to keep up.",
]

AGGRESSIVE_CLEAR = [
  "Blue sky, no excuses. High {high}, overnight {low}. Sun dies at {sunset}. Go outside.",
  "Clear as hell. High {high}, low {low}, sunset {sunset}. Touch grass.",
]

AGGRESSIVE_CLOUDY = [
  "Grey and ugly. High {high}, overnight {low}. Sunset {sunset}. The sky's in a mood. Join it.",
  "Clouds. High {high}, low {low}. Sunset {sunset}. Don't expect a miracle.",
]

AGGRESSIVE_RAIN = [
  "It's going to piss down. High {high}, low {low}, sunset {sunset}. Hydroplane and eat shit if you want. That's on you.",
  "Rain. Actual rain. High {high}, overnight {low}. Leave space or crash. Sunset {sunset}.",
]

AGGRESSIVE_SNOW = [
  "Snow, you poor bastard. High a miserable {high}, overnight {low}. Sunset {sunset}. Drive like your life depends on it, because it does.",
]

AGGRESSIVE_HOT = [
  "It's a cunt of a day. High {high}. Overnight still a sticky {low}. Sunset {sunset}. Hydrate or suffer.",
  "Hot as hell. {high} high, {low} overnight, sun clocks out at {sunset}. Don't leave a dog in the car, you animal.",
]

AGGRESSIVE_COLD = [
  "Cold as a witch's tit. High only {high}, overnight {low}. Sunset {sunset}. Warm the car or freeze. Not my problem.",
]

AGGRESSIVE_CLOSERS = [
  "That's the weather. Don't die.",
  "We're done. Drive.",
  "Forecast over. Try not to be an idiot.",
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
      return f"Overnight {low}\u00b0 with more wet bullshit. Roll the windows up, genius."
    return f"Overnight bottoms out around {low}\u00b0. That's all."
  else:
    if precip > 0.1:
      return f"Overnight low near {low}\u00b0 with a chance of more precipitation. Secure any outdoor gear."
    return f"Overnight low around {low}\u00b0. Should be a quiet night for most of us."


def enjoy_your_drive(aggressive: bool = False) -> str:
  return random.choice(ENJOY_UNHINGED if aggressive else ENJOY_NICE)


def pay_attention(aggressive: bool = False) -> str:
  return random.choice(PAY_ATTENTION_UNHINGED if aggressive else PAY_ATTENTION_NICE)
