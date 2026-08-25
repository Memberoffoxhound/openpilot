"""Grok Ara TTS. Queues /data/wxnews.wav for soundd. No on-device synthesizers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.weather_news import grok as grok_api

WXNEWS_WAV = Path("/data/wxnews.wav")
WXNEWS_PLAY = Path("/data/wxnews_play")


def speak_lines(lines: list[str], aggressive: bool, on_status=None, voice: str | None = None) -> bool:
  text = " ".join(ln.strip() for ln in lines if ln and ln.strip())
  if not text:
    return False
  tag = "unhinged" if aggressive else "nice"
  cloudlog.info(f"weather_news [{tag}/ara]: {text[:160]}")
  tmp = Path(tempfile.mkdtemp(prefix="wxnews_"))
  try:
    wav = tmp / "cycle.wav"
    if on_status:
      on_status("speaking")
    if not grok_api.tts_wav(text, wav, unhinged=aggressive):
      return False
    if on_status:
      on_status("playing")
    WXNEWS_WAV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wav, WXNEWS_WAV)
    WXNEWS_PLAY.write_text("1")
    return WXNEWS_WAV.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: queue failed")
    return False
  finally:
    shutil.rmtree(tmp, ignore_errors=True)
