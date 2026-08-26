"""SpaceXAI (xAI) Grok chat + Ara TTS. Gemini/OpenAI/Groq chat. Key lives in params, never in the repo."""

from __future__ import annotations

import json
import socket
import subprocess
import wave
from pathlib import Path
from typing import Any

import requests

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.weather_news import config as grok_cfg

CHAT_URL = "https://api.x.ai/v1/chat/completions"
TTS_URL = "https://api.x.ai/v1/tts"
MODEL = "grok-4-fast"
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
VOICE_ID = "ara"
TIMEOUT_CHAT = 60
TIMEOUT_TTS = 90

_last_bytes = {"chat": 0, "tts": 0}


def last_bytes() -> dict[str, int]:
  return dict(_last_bytes)


def _note_bytes(kind: str, n: int) -> None:
  _last_bytes[kind] = max(0, int(n))

def _brief_sys(unhinged: bool, window: str = "", *, world_breaking: bool = True) -> str:
  sec = grok_cfg.duration()
  who = grok_cfg.display_name()
  slot = {
    "morning": "This is the morning briefing.",
    "afternoon": "This is the afternoon briefing.",
    "evening": "This is the evening briefing (after 7pm).",
  }.get(window, "This is a current briefing.")
  loc = (
    "The user JSON has the driver's current latitude, longitude, local time (`as_of`), and a place name when known. "
    "Identify the city or area from those coordinates and use that location. Do not read the numbers aloud. "
    "Weather must be current to this minute and place — lead with conditions right now, then the rest of this window. "
    f"{slot} Do not recap other time windows from today. Skip empty lists."
  )
  news = (
    "News must be live as of `as_of`. "
    + ("First a short WORLD BREAKING section: what actually changed in the last few hours. Then the driver's interest topics. "
       if world_breaking else
       "Cover the driver's interest topics. ")
    + "Prefer items with the newest `pub` / smallest `age_s`. "
    "Skip anything in `already_told` unless there is a new development since then. "
    "Do not spend time on day-old running stories. Do not pad. "
    "You may add a widely confirmed breaking event from this exact moment that is not in RSS yet — "
    "no fake numbers, quotes, death tolls, or URLs. Do not invent a story that did not happen. "
    "Cover fresh items; do not read the same recap as the last drive."
  )
  if unhinged:
    voice = "You are Ara, Tesla Grok Unhinged." if grok_cfg.provider() == "xai" else (
      f"You are {who}, TeslaPilot Unhinged."
    )
    return (
      f"{voice} Write a spoken briefing a driver hears through a car speaker. "
      f"{sec} seconds. NSFW, vulgar, unfiltered. Roast the weather and the headlines. "
      "Never sexual. Never slurs. Never tell them to crash. "
      f"{loc} {news} "
      "No markdown, no lists, no URLs. "
      "You may insert TTS tags like [laugh], [pause], [sigh]. "
      "End by telling them not to crash and to keep their eyes on the road."
    )
  voice = "You are Ara, the Grok voice, in Nice mode." if grok_cfg.provider() == "xai" else (
    f"You are {who}, TeslaPilot copilot in Nice mode."
  )
  return (
    f"{voice} Write a spoken briefing a driver hears "
    f"through a car speaker. {sec} seconds when read aloud. Warm, PG, first person. "
    f"{loc} {news} "
    "No markdown, no lists, no URLs. "
    "Plain sentences. End by telling them to enjoy the drive and keep their eyes on the road."
  )


def lan_ip() -> str:
  wifi, other = [], []
  try:
    out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], text=True, timeout=2)
  except Exception:
    out = ""
  for line in out.splitlines():
    parts = line.split()
    if len(parts) < 4:
      continue
    iface, cidr = parts[1], parts[3]
    ip = cidr.split("/")[0]
    if ip.startswith("127.") or ip.startswith("169.254."):
      continue
    if "wlan" in iface or iface.startswith("wl") or iface == "en0":
      wifi.append(ip)
    else:
      other.append(ip)
  if wifi:
    return wifi[0]
  rest = [i for i in other if not i.startswith("192.168.43.")]
  if rest:
    return rest[0]
  if other:
    return other[0]
  try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.2)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    if ip and not ip.startswith("127."):
      return ip
  except Exception:
    pass
  return "192.168.43.1"


def console_url(path: str = "/grok") -> str:
  if not path.startswith("/"):
    path = "/" + path
  return f"http://{lan_ip()}:8088{path}"


def _headers(key: str) -> dict[str, str]:
  return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def test_key(key: str | None = None, provider: str | None = None) -> tuple[bool, str]:
  p = (provider or grok_cfg.provider() or "xai").strip().lower()
  if p == "openai":
    key = (key or grok_cfg.openai_key()).strip()
    url = "https://api.openai.com/v1/models"
    headers = _headers(key)
  elif p == "groq":
    key = (key or grok_cfg.groq_key()).strip()
    url = "https://api.groq.com/openai/v1/models"
    headers = _headers(key)
  elif p == "gemini":
    key = (key or grok_cfg.gemini_key()).strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
    headers = {"x-goog-api-key": key}
  else:
    key = (key or grok_cfg.api_key()).strip()
    url = "https://api.x.ai/v1/tts/voices"
    headers = _headers(key)
  if not key:
    return False, f"no {p} API key"
  try:
    r = requests.get(url, headers=headers, timeout=12)
    if r.status_code in (401, 403):
      return False, "unauthorized"
    if r.status_code in (200, 203):
      return True, "ok"
    return False, f"http {r.status_code}"
  except Exception as e:
    return False, str(e)[:80]


def write_script(weather: dict[str, Any] | None, news: list[dict], *, unhinged: bool,
                 location_name: str = "your area", lat: float | None = None,
                 lon: float | None = None, local_time: str = "", window: str = "",
                 breaking: list[dict] | None = None, already_told: list[str] | None = None) -> str | None:
  if not grok_cfg.configured():
    return None

  def _slim(rows: list[dict], n: int) -> list[dict]:
    out = []
    for item in rows:
      t = (item.get("title") or "").strip()
      if not t:
        continue
      row = {"source": item.get("source") or "news", "title": t}
      if item.get("pub"):
        row["pub"] = item["pub"]
      if item.get("age_s") is not None:
        row["age_s"] = item["age_s"]
      if item.get("desc"):
        row["blurb"] = str(item["desc"])[:160]
      out.append(row)
      if len(out) >= n:
        break
    return out

  use_breaking = bool(breaking) and grok_cfg.world_breaking()
  user = {
    "request_location": True,
    "as_of": local_time,
    "location": {
      "name": location_name,
      "latitude": None if lat is None else round(float(lat), 5),
      "longitude": None if lon is None else round(float(lon), 5),
      "local_time": local_time,
      "window": window or "current",
    },
    "weather": weather or {},
    "topics": grok_cfg.topics(),
    "world_breaking": _slim(breaking or [], 5) if use_breaking else [],
    "interests": _slim(news, 8),
    "already_told": [t for t in (already_told or []) if t][:16],
  }
  return _chat(
    _brief_sys(unhinged, window=window, world_breaking=use_breaking),
    json.dumps(user),
    temperature=1.0 if unhinged else 0.75,
  )


def write_preview(*, unhinged: bool) -> str | None:
  who = grok_cfg.display_name()
  if grok_cfg.provider() == "xai":
    sys = (
      "You are Ara. Unhinged. One or two spoken sentences, 8 to 12 seconds. NSFW ok. "
      "Confirm this is the Unhinged voice. No news, no weather, no lists."
      if unhinged else
      "You are Ara. Nice mode. One or two spoken sentences, 8 to 12 seconds, PG. "
      "Confirm this is the Nice voice. No news, no weather, no lists."
    )
  else:
    sys = (
      f"You are {who}. Unhinged. One or two spoken sentences, 8 to 12 seconds. NSFW ok, never sexual. "
      f"Confirm this is the Unhinged {who} voice. No news, no weather, no lists."
      if unhinged else
      f"You are {who}. Nice mode. One or two spoken sentences, 8 to 12 seconds, PG. "
      f"Confirm this is the Nice {who} voice. No news, no weather, no lists."
    )
  return _chat(sys, "Preview tap. Speak now.", temperature=1.0 if unhinged else 0.5)


def _chat_endpoint() -> tuple[str, str, str]:
  p = grok_cfg.provider()
  if p == "openai":
    return "https://api.openai.com/v1/chat/completions", grok_cfg.openai_key(), "gpt-4o-mini"
  if p == "groq":
    return "https://api.groq.com/openai/v1/chat/completions", grok_cfg.groq_key(), "llama-3.3-70b-versatile"
  return CHAT_URL, grok_cfg.api_key(), MODEL


def _chat_gemini(system: str, user: str, *, temperature: float) -> str | None:
  key = grok_cfg.gemini_key()
  if not key:
    return None
  last_err = ""
  for _ in range(2):
    try:
      r = requests.post(
        GEMINI_URL,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        json={
          "systemInstruction": {"parts": [{"text": system}]},
          "contents": [{"role": "user", "parts": [{"text": user}]}],
          "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 800,
          },
        },
        timeout=TIMEOUT_CHAT,
      )
      _note_bytes("chat", len(system) + len(user) + 180 + len(r.content))
      if r.status_code != 200:
        last_err = f"http {r.status_code} {r.text[:160]}"
        cloudlog.warning(f"weather_news: gemini chat {last_err}")
        continue
      parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
      text = " ".join((p.get("text") or "") for p in parts if p.get("text") and not p.get("thought"))
      text = " ".join(text.strip().split())
      if text:
        return text
      last_err = "empty"
    except Exception:
      cloudlog.exception("weather_news: gemini chat failed")
      last_err = "exception"
  cloudlog.warning(f"weather_news: gemini chat gave up ({last_err})")
  return None


def _chat(system: str, user: str, *, temperature: float) -> str | None:
  if grok_cfg.provider() == "gemini":
    return _chat_gemini(system, user, temperature=temperature)
  url, key, model = _chat_endpoint()
  if not key:
    return None
  last_err = ""
  for _ in range(2):
    try:
      r = requests.post(
        url,
        headers=_headers(key),
        json={
          "model": model,
          "temperature": temperature,
          "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
          ],
        },
        timeout=TIMEOUT_CHAT,
      )
      _note_bytes("chat", len(system) + len(user) + 180 + len(r.content))
      if r.status_code != 200:
        last_err = f"http {r.status_code} {r.text[:160]}"
        cloudlog.warning(f"weather_news: grok chat {last_err}")
        continue
      text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""
      text = " ".join(text.strip().split())
      if text:
        return text
      last_err = "empty"
    except Exception:
      cloudlog.exception("weather_news: grok chat failed")
      last_err = "exception"
  cloudlog.warning(f"weather_news: grok chat gave up ({last_err})")
  return None


def _write_wav(dest: Path, pcm: bytes, rate: int = 24000, width: int = 2, ch: int = 1) -> None:
  dest.parent.mkdir(parents=True, exist_ok=True)
  with wave.open(str(dest), "wb") as w:
    w.setnchannels(ch)
    w.setsampwidth(width)
    w.setframerate(rate)
    w.writeframes(pcm)


def _pcm_from_riff(data: bytes) -> tuple[bytes, int, int, int] | None:
  """PCM from WAV. xAI streaming WAVs lie about data-chunk size — trust remaining bytes."""
  if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
    return None
  i = 12
  rate, width, ch = 24000, 2, 1
  pcm: bytes | None = None
  while i + 8 <= len(data):
    cid = data[i:i + 4]
    claimed = int.from_bytes(data[i + 4:i + 8], "little")
    avail = len(data) - (i + 8)
    size = claimed if 0 <= claimed <= avail else avail
    body = data[i + 8:i + 8 + size]
    if cid == b"fmt " and len(body) >= 16:
      ch = int.from_bytes(body[2:4], "little") or 1
      rate = int.from_bytes(body[4:8], "little") or 24000
      bits = int.from_bytes(body[14:16], "little") or 16
      width = max(1, bits // 8)
    elif cid == b"data":
      pcm = body
      break
    if claimed < 0 or claimed > avail:
      break
    i += 8 + claimed + (claimed % 2)
  if not pcm or len(pcm) < 800:
    return None
  return pcm, rate, width, ch


def tts_wav(text: str, dest: Path, *, unhinged: bool = False) -> bool:
  text = text.strip()
  if not text:
    return False
  p = grok_cfg.provider()
  use_openai = p == "openai" or (p in ("groq", "gemini") and not grok_cfg.api_key())
  try:
    if use_openai:
      key = grok_cfg.openai_key()
      if not key:
        return False
      r = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "tts-1", "voice": "alloy", "input": text, "response_format": "wav", "speed": 1.05 if unhinged else 1.0},
        timeout=TIMEOUT_TTS,
      )
      r.raise_for_status()
      data = r.content
    else:
      key = grok_cfg.api_key()
      if not key:
        return False
      r = requests.post(
        TTS_URL, headers=_headers(key),
        json={
          "text": text, "voice_id": VOICE_ID, "language": "en",
          "speed": 1.05 if unhinged else 1.0,
          "output_format": {"codec": "wav", "sample_rate": 24000},
        },
        timeout=TIMEOUT_TTS,
      )
    r.raise_for_status()
    data = r.content
    _note_bytes("tts", len(data) + 256)
    if len(data) < 800:
      return False
    if data[:4] == b"RIFF":
      parsed = _pcm_from_riff(data)
      if parsed is None:
        return False
      pcm, rate, width, ch = parsed
      _write_wav(dest, pcm, rate=rate, width=width, ch=ch)
    else:
      _write_wav(dest, data, rate=24000)
    return dest.exists() and dest.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: tts failed")
    return False
