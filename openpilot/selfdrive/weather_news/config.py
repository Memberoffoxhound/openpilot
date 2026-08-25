"""Grok voice config. Params if the key is compiled in; else /data/params/d files."""

from __future__ import annotations

from pathlib import Path

from openpilot.common.params import Params

PARAM_DIR = Path("/data/params/d")
VOICE_KEY = "GrokVoiceEnabled"
API_KEY = "XaiApiKey"


def _params() -> Params:
  return Params()


def voice_enabled() -> bool:
  try:
    return bool(_params().get_bool(VOICE_KEY))
  except Exception:
    f = PARAM_DIR / VOICE_KEY
    return f.exists() and f.read_text().strip().lower() in ("1", "true", "on", "yes")


def set_voice_enabled(on: bool) -> None:
  PARAM_DIR.mkdir(parents=True, exist_ok=True)
  try:
    _params().put_bool(VOICE_KEY, bool(on), block=True)
  except Exception:
    (PARAM_DIR / VOICE_KEY).write_text("1" if on else "0")


def api_key() -> str:
  try:
    v = _params().get(API_KEY)
    if v:
      return str(v).strip()
  except Exception:
    pass
  f = PARAM_DIR / API_KEY
  if f.exists():
    return f.read_text().strip()
  return ""


def set_api_key(key: str) -> None:
  key = (key or "").strip()
  PARAM_DIR.mkdir(parents=True, exist_ok=True)
  try:
    if key:
      _params().put(API_KEY, key, block=True)
    else:
      _params().remove(API_KEY)
  except Exception:
    path = PARAM_DIR / API_KEY
    if key:
      path.write_text(key)
    elif path.exists():
      path.unlink()


def configured() -> bool:
  return bool(api_key())


def ready() -> bool:
  return voice_enabled() and configured()


def masked_key() -> str:
  k = api_key()
  if len(k) < 8:
    return ""
  return k[:4] + "…" + k[-4:]
