"""SpaceXAI (xAI) Grok chat + Ara TTS. Key lives in params, never in the repo."""

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
MODEL = "grok-4.6"
VOICE_ID = "ara"
TIMEOUT_CHAT = 45
TIMEOUT_TTS = 90

NICE_SYS = (
  "You are Ara, the Grok voice, in Nice mode. Write a spoken daily briefing a driver hears "
  "through a car speaker. 50 to 80 seconds when read aloud. Warm, PG, first person. "
  "Cover in order: local forecast; Aptera Motors if an Aptera headline is present (skip if the list is empty); "
  "one CNN world story if present; then Tesla/SpaceX/xAI bites. "
  "No markdown, no lists, no URLs, no stage directions. Plain sentences. "
  "End by telling them to enjoy the drive and keep their eyes on the road."
)

UNHINGED_SYS = (
  "You are Ara, Tesla Grok Unhinged. Write a spoken daily briefing a driver hears through a car speaker. "
  "50 to 80 seconds. NSFW, vulgar, unfiltered — same energy as Tesla Grok Unhinged. Roast the weather "
  "and the headlines. Cover in order: forecast; Aptera Motors if a headline is present (skip if empty); "
  "one CNN world story if present; then Tesla/SpaceX/xAI. No markdown, no lists, no URLs. "
  "You may insert TTS tags like [laugh], [pause], [sigh]. "
  "End by telling them not to crash and to keep their eyes on the road."
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


def test_key(key: str | None = None) -> tuple[bool, str]:
  key = (key or grok_cfg.api_key()).strip()
  if not key:
    return False, "no API key"
  try:
    r = requests.get("https://api.x.ai/v1/tts/voices", headers=_headers(key), timeout=12)
    if r.status_code == 401:
      return False, "unauthorized"
    if r.status_code == 200:
      return True, "ok"
    return False, f"http {r.status_code}"
  except Exception as e:
    return False, str(e)[:80]


def write_script(weather: dict[str, Any] | None, news: list[dict], *, unhinged: bool,
                 location_name: str = "your area") -> str | None:
  key = grok_cfg.api_key()
  if not key:
    return None

  def titles(source: str, n: int) -> list[str]:
    out = []
    for item in news:
      if item.get("source") != source:
        continue
      t = (item.get("title") or "").strip()
      if t:
        out.append(t)
      if len(out) >= n:
        break
    return out

  user = {
    "location": location_name,
    "weather": weather or {},
    "aptera": titles("aptera", 2),
    "world": titles("cnn", 1),
    "headlines": titles("elon", 3),
  }
  try:
    r = requests.post(
      CHAT_URL,
      headers=_headers(key),
      json={
        "model": MODEL,
        "temperature": 1.0 if unhinged else 0.6,
        "messages": [
          {"role": "system", "content": UNHINGED_SYS if unhinged else NICE_SYS},
          {"role": "user", "content": json.dumps(user)},
        ],
      },
      timeout=TIMEOUT_CHAT,
    )
    r.raise_for_status()
    text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""
    text = " ".join(text.strip().split())
    return text or None
  except Exception:
    cloudlog.exception("weather_news: grok chat failed")
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
  key = grok_cfg.api_key()
  if not key or not text.strip():
    return False
  payload = {
    "text": text.strip(),
    "voice_id": VOICE_ID,
    "language": "en",
    "speed": 1.05 if unhinged else 1.0,
    "output_format": {"codec": "wav", "sample_rate": 24000},
  }
  try:
    r = requests.post(TTS_URL, headers=_headers(key), json=payload, timeout=TIMEOUT_TTS)
    r.raise_for_status()
    data = r.content
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
    cloudlog.exception("weather_news: grok tts failed")
    return False
