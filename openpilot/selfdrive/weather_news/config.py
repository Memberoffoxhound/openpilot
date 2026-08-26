"""Grok voice config. Params if the key is compiled in; else /data/params/d files."""

from __future__ import annotations

from pathlib import Path

from openpilot.common.params import Params

PARAM_DIR = Path("/data/params/d")
VOICE_KEY = "GrokVoiceEnabled"
API_KEY = "XaiApiKey"
TOPICS_KEY = "WeatherNewsTopics"
ONDEMAND_KEY = "WeatherNewsOnDemand"
DURATION_KEY = "WeatherNewsDuration"
WIFI_KEY = "WeatherNewsWifiOnly"
PROVIDER_KEY = "GrokProvider"
OPENAI_KEY = "OpenaiApiKey"
GROQ_KEY = "GroqApiKey"
GEMINI_KEY = "GeminiApiKey"
EVERY_DRIVE_KEY = "WeatherNewsEveryDrive"
PLAYBACK_KEY = "WeatherNewsPlayback"
PLAYBACK_STANDARD = 0
PLAYBACK_BOOSTED = 1
PROVIDERS = ("xai", "openai", "groq", "gemini")
PROVIDER_NAMES = {"xai": "Grok", "openai": "OpenAI", "groq": "Groq", "gemini": "Gemini"}
DEFAULT_TOPICS = "npr"
TOPIC_SUGGESTIONS = (
  "npr", "cnn", "comma", "reddit", "reddit:commaai", "reddit:openpilot",
  "x", "Aptera Motors", "Tesla", "SpaceX", "xAI", "openpilot", "Neuralink",
)
DURATIONS = (60, 90, 120)


def _params() -> Params:
  return Params()


def _as_str(v) -> str:
  if v is None:
    return ""
  if isinstance(v, bytes):
    return v.decode(errors="replace").strip()
  return str(v).strip()


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
    s = _as_str(v) if v else ""
    if s:
      return s
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


def _key_file(name: str) -> str:
  try:
    v = _params().get(name)
    s = _as_str(v) if v else ""
    if s:
      return s
  except Exception:
    pass
  f = PARAM_DIR / name
  return f.read_text().strip() if f.exists() else ""


def _set_key(name: str, key: str) -> None:
  key = (key or "").strip()
  PARAM_DIR.mkdir(parents=True, exist_ok=True)
  try:
    if key:
      _params().put(name, key, block=True)
    else:
      _params().remove(name)
  except Exception:
    path = PARAM_DIR / name
    if key:
      path.write_text(key)
    elif path.exists():
      path.unlink()


def openai_key() -> str:
  return _key_file(OPENAI_KEY)


def set_openai_key(key: str) -> None:
  _set_key(OPENAI_KEY, key)


def groq_key() -> str:
  return _key_file(GROQ_KEY)


def set_groq_key(key: str) -> None:
  _set_key(GROQ_KEY, key)


def gemini_key() -> str:
  return _key_file(GEMINI_KEY)


def set_gemini_key(key: str) -> None:
  _set_key(GEMINI_KEY, key)


def provider() -> str:
  p = _key_file(PROVIDER_KEY).lower() or "xai"
  return p if p in PROVIDERS else "xai"


def set_provider(name: str) -> None:
  p = (name or "xai").strip().lower()
  if p not in PROVIDERS:
    p = "xai"
  try:
    _params().put(PROVIDER_KEY, p, block=True)
  except Exception:
    PARAM_DIR.mkdir(parents=True, exist_ok=True)
    (PARAM_DIR / PROVIDER_KEY).write_text(p)


def display_name(p: str | None = None) -> str:
  return PROVIDER_NAMES.get(p or provider(), "Grok")


def configured() -> bool:
  p = provider()
  if p == "openai":
    return bool(openai_key())
  if p == "groq":
    return bool(groq_key())
  if p == "gemini":
    return bool(gemini_key())
  return bool(api_key())


def ready() -> bool:
  return voice_enabled() and configured()


def active_key() -> str:
  p = provider()
  if p == "openai":
    return openai_key()
  if p == "groq":
    return groq_key()
  if p == "gemini":
    return gemini_key()
  return api_key()


def masked_key() -> str:
  k = active_key()
  if len(k) < 8:
    return ""
  return k[:4] + "…" + k[-4:]


def parse_topics(text: str) -> list[str]:
  out: list[str] = []
  for line in (text or "").replace(",", "\n").splitlines():
    t = line.strip()
    if t and not t.startswith("#"):
      out.append(t)
  return out or [DEFAULT_TOPICS]


def topics_text() -> str:
  try:
    v = _params().get(TOPICS_KEY)
    s = _as_str(v) if v else ""
    if s:
      return s
  except Exception:
    pass
  f = PARAM_DIR / TOPICS_KEY
  if f.exists():
    return f.read_text().strip()
  return DEFAULT_TOPICS


def topics() -> list[str]:
  return parse_topics(topics_text())


def duration() -> int:
  try:
    v = int(_as_str(_params().get(DURATION_KEY) or "60") or 60)
  except Exception:
    f = PARAM_DIR / DURATION_KEY
    try:
      v = int(f.read_text().strip()) if f.exists() else 60
    except Exception:
      v = 60
  return v if v in DURATIONS else 60


def set_duration(sec: int) -> None:
  v = int(sec) if int(sec) in DURATIONS else 60
  try:
    _params().put(DURATION_KEY, str(v), block=True)
  except Exception:
    PARAM_DIR.mkdir(parents=True, exist_ok=True)
    (PARAM_DIR / DURATION_KEY).write_text(str(v))


def wifi_only() -> bool:
  try:
    return bool(_params().get_bool(WIFI_KEY))
  except Exception:
    f = PARAM_DIR / WIFI_KEY
    return f.exists() and f.read_text().strip().lower() in ("1", "true", "on", "yes")


def set_wifi_only(on: bool) -> None:
  try:
    _params().put_bool(WIFI_KEY, bool(on), block=True)
  except Exception:
    PARAM_DIR.mkdir(parents=True, exist_ok=True)
    (PARAM_DIR / WIFI_KEY).write_text("1" if on else "0")


def every_drive() -> bool:
  try:
    return bool(_params().get_bool(EVERY_DRIVE_KEY))
  except Exception:
    f = PARAM_DIR / EVERY_DRIVE_KEY
    return f.exists() and f.read_text().strip().lower() in ("1", "true", "on", "yes")


def set_every_drive(on: bool) -> None:
  try:
    _params().put_bool(EVERY_DRIVE_KEY, bool(on), block=True)
  except Exception:
    PARAM_DIR.mkdir(parents=True, exist_ok=True)
    (PARAM_DIR / EVERY_DRIVE_KEY).write_text("1" if on else "0")


def playback() -> int:
  try:
    v = _params().get(PLAYBACK_KEY, return_default=True)
    n = int(v if v is not None else PLAYBACK_BOOSTED)
  except Exception:
    f = PARAM_DIR / PLAYBACK_KEY
    try:
      n = int(f.read_text().strip()) if f.exists() else PLAYBACK_BOOSTED
    except Exception:
      n = PLAYBACK_BOOSTED
  return PLAYBACK_BOOSTED if n == PLAYBACK_BOOSTED else PLAYBACK_STANDARD


def playback_boosted() -> bool:
  return playback() == PLAYBACK_BOOSTED


def set_playback(mode: int) -> None:
  v = PLAYBACK_BOOSTED if int(mode) == PLAYBACK_BOOSTED else PLAYBACK_STANDARD
  try:
    _params().put(PLAYBACK_KEY, v, block=True)
  except Exception:
    PARAM_DIR.mkdir(parents=True, exist_ok=True)
    (PARAM_DIR / PLAYBACK_KEY).write_text(str(v))


def set_topics(text: str) -> None:
  lines = parse_topics(text)[:6]
  value = "\n".join(lines)
  PARAM_DIR.mkdir(parents=True, exist_ok=True)
  try:
    _params().put(TOPICS_KEY, value, block=True)
  except Exception:
    (PARAM_DIR / TOPICS_KEY).write_text(value)


def ondemand() -> bool:
  try:
    return bool(_params().get_bool(ONDEMAND_KEY))
  except Exception:
    f = PARAM_DIR / ONDEMAND_KEY
    return f.exists() and f.read_text().strip().lower() in ("1", "true", "on", "yes")


def request_ondemand() -> None:
  PARAM_DIR.mkdir(parents=True, exist_ok=True)
  try:
    _params().put_bool(ONDEMAND_KEY, True, block=True)
  except Exception:
    (PARAM_DIR / ONDEMAND_KEY).write_text("1")


def clear_ondemand() -> None:
  try:
    _params().put_bool(ONDEMAND_KEY, False, block=True)
  except Exception:
    f = PARAM_DIR / ONDEMAND_KEY
    if f.exists():
      f.write_text("0")
