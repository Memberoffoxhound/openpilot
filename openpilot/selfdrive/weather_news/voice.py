#!/usr/bin/env python3
"""Render a wav, then hand it to soundd. soundd owns the speaker.

Piper (neural, lessac) is the voice. espeak-ng is a last-ditch fallback.
Binary + model land in /data/weather_news on first use (~90 MB, once).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from openpilot.common.swaglog import cloudlog

WXNEWS_WAV = Path("/data/wxnews.wav")
WXNEWS_PLAY = Path("/data/wxnews_play")
CACHE = Path("/data/weather_news")
PIPER_DIR = CACHE / "piper"
PIPER_BIN = PIPER_DIR / "piper"
VOICE_DIR = CACHE / "voices"

# rhasspy 2023.11.14-2 — static aarch64, glibc 2.31. C4 is AGNOS.
PIPER_TGZ_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
# one female US voice. Unhinged is the language, not a different person.
VOICE_ID = "en_US-lessac-medium"
VOICE_ONNX = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
VOICE_JSON = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

# leftover espeak from the previous drop — used only if piper cannot run
ESPEAK_ROOT = CACHE / "root"

_espeak: tuple[str, dict[str, str], str | None] | None = None


def _curl(url: str, dest: Path, min_bytes: int = 1024) -> None:
  dest.parent.mkdir(parents=True, exist_ok=True)
  part = dest.with_name(dest.name + ".part")
  subprocess.run(
    ["curl", "-fsSL", "--retry", "3", "--max-time", "180", "-o", str(part), url],
    check=True,
  )
  if not part.exists() or part.stat().st_size < min_bytes:
    part.unlink(missing_ok=True)
    raise RuntimeError(f"tiny download {url}")
  part.replace(dest)


def _ensure_piper() -> Path | None:
  if PIPER_BIN.is_file() and os.access(PIPER_BIN, os.X_OK):
    return PIPER_BIN
  if os.uname().machine not in ("aarch64", "arm64"):
    which = shutil.which("piper")
    return Path(which) if which else None
  cloudlog.info("weather_news: fetching piper (~25 MB, once)")
  tgz = CACHE / "piper_linux_aarch64.tar.gz"
  if not tgz.exists() or tgz.stat().st_size < 1_000_000:
    _curl(PIPER_TGZ_URL, tgz, min_bytes=1_000_000)
  CACHE.mkdir(parents=True, exist_ok=True)
  with tarfile.open(tgz, "r:gz") as tf:
    try:
      tf.extractall(CACHE, filter="data")
    except TypeError:
      tf.extractall(CACHE)
  if PIPER_BIN.is_file():
    PIPER_BIN.chmod(0o755)
    return PIPER_BIN
  return None


def _ensure_voice() -> Path | None:
  onnx = VOICE_DIR / f"{VOICE_ID}.onnx"
  js = VOICE_DIR / f"{VOICE_ID}.onnx.json"
  if not onnx.exists() or onnx.stat().st_size < 1_000_000:
    cloudlog.info("weather_news: fetching lessac voice (~60 MB, once)")
    _curl(VOICE_ONNX, onnx, min_bytes=1_000_000)
  if not js.exists():
    _curl(VOICE_JSON, js, min_bytes=64)
  return onnx if onnx.exists() and onnx.stat().st_size > 1_000_000 else None


def _render_piper(text: str, dest: Path, aggressive: bool) -> bool:
  try:
    binary = _ensure_piper()
    model = _ensure_voice()
  except Exception:
    cloudlog.exception("weather_news: piper bootstrap failed")
    return False
  if not binary or not model:
    return False

  env = os.environ.copy()
  lib = str(binary.parent)
  env["LD_LIBRARY_PATH"] = lib + ((":" + env["LD_LIBRARY_PATH"]) if env.get("LD_LIBRARY_PATH") else "")

  # same woman, same speed. Unhinged is the script, not the cadence.
  cmd = [
    str(binary), "--model", str(model), "--output_file", str(dest),
    "--length-scale", "1.0", "--sentence-silence", "0.35",
  ]
  try:
    subprocess.run(
      cmd, input=text.encode(), check=False, env=env,
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
      preexec_fn=lambda: os.nice(10),
    )
    return dest.exists() and dest.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: piper render failed")
    return False


def _ensure_espeak() -> tuple[str, dict[str, str], str | None] | None:
  global _espeak
  if _espeak:
    return _espeak
  env = os.environ.copy()
  system = shutil.which("espeak-ng") or shutil.which("espeak")
  if system:
    _espeak = (system, env, None)
    return _espeak
  cached = ESPEAK_ROOT / "usr/bin/espeak-ng"
  if cached.exists():
    libs = [str(p) for p in (ESPEAK_ROOT / "usr/lib/aarch64-linux-gnu", ESPEAK_ROOT / "lib/aarch64-linux-gnu") if p.is_dir()]
    if libs:
      env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")]).strip(":")
    data = None
    for p in (ESPEAK_ROOT / "usr/lib/aarch64-linux-gnu/espeak-ng-data", ESPEAK_ROOT / "usr/share/espeak-ng-data"):
      if p.is_dir():
        data = str(p)
        break
    _espeak = (str(cached), env, data)
    return _espeak
  return None


def _render_espeak(text: str, dest: Path, aggressive: bool) -> bool:
  got = _ensure_espeak()
  if not got:
    return False
  espeak, env, data = got
  # same female voice and speed as Nice; fallback only
  voice, pitch, speed, amp, gap = "en-us+f3", "58", "142", "170", "7"
  cmd = [espeak, "-v", voice, "-p", pitch, "-s", speed, "-a", amp, "-g", gap, "-w", str(dest), text]
  if data:
    cmd[1:1] = ["--path", str(Path(data).parent)]
  try:
    subprocess.run(cmd, check=False, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    return dest.exists() and dest.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: espeak failed")
    return False


def render_wav(text: str, dest: Path, aggressive: bool) -> bool:
  if _render_piper(text, dest, aggressive):
    return True
  cloudlog.warning("weather_news: piper unavailable, espeak fallback")
  return _render_espeak(text, dest, aggressive)


def speak_lines(lines: list[str], aggressive: bool) -> bool:
  text = " ".join(ln.strip() for ln in lines if ln and ln.strip())
  if not text:
    return False
  tag = "aggressive" if aggressive else "nice"
  cloudlog.info(f"weather_news [{tag}]: {text[:160]}")

  tmp = Path(tempfile.mkdtemp(prefix="wxnews_"))
  try:
    wav = tmp / "cycle.wav"
    if not render_wav(text, wav, aggressive):
      return False
    WXNEWS_WAV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wav, WXNEWS_WAV)
    WXNEWS_PLAY.write_text("1")
    return WXNEWS_WAV.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: queue failed")
    return False
  finally:
    shutil.rmtree(tmp, ignore_errors=True)
