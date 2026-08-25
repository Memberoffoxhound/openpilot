#!/usr/bin/env python3
"""Render a wav, then hand it to soundd. soundd owns the speaker.

gps / high = Piper lessac (medium / high).
human = Kokoro via sherpa-onnx.
espeak-ng is last-ditch fallback.
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
SHERPA_DIR = CACHE / "sherpa"
KOKORO_DIR = CACHE / "kokoro"

PIPER_TGZ_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
PIPER_MODELS = {
  "gps": (
    "en_US-lessac-medium",
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
  ),
  "high": (
    "en_US-lessac-high",
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/high/en_US-lessac-high.onnx",
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/high/en_US-lessac-high.onnx.json",
  ),
}
SHERPA_TGZ_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.6/sherpa-onnx-v1.13.6-linux-aarch64-shared-cpu.tar.bz2"
KOKORO_TGZ_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_0.tar.bz2"

ESPEAK_ROOT = CACHE / "root"

_espeak: tuple[str, dict[str, str], str | None] | None = None


def _curl(url: str, dest: Path, min_bytes: int = 1024, timeout: int = 600) -> None:
  dest.parent.mkdir(parents=True, exist_ok=True)
  part = dest.with_name(dest.name + ".part")
  subprocess.run(
    ["curl", "-fsSL", "--retry", "3", "--max-time", str(timeout), "-o", str(part), url],
    check=True,
  )
  if not part.exists() or part.stat().st_size < min_bytes:
    part.unlink(missing_ok=True)
    raise RuntimeError(f"tiny download {url}")
  part.replace(dest)


def _extract(archive: Path, dest: Path) -> None:
  dest.mkdir(parents=True, exist_ok=True)
  mode = "r:bz2" if archive.suffix == ".bz2" or archive.name.endswith(".tar.bz2") else "r:gz"
  with tarfile.open(archive, mode) as tf:
    try:
      tf.extractall(dest, filter="data")
    except TypeError:
      tf.extractall(dest)


def _ensure_piper(on_status=None) -> Path | None:
  if PIPER_BIN.is_file() and os.access(PIPER_BIN, os.X_OK):
    return PIPER_BIN
  if os.uname().machine not in ("aarch64", "arm64"):
    which = shutil.which("piper")
    return Path(which) if which else None
  if on_status:
    on_status("downloading voice")
  cloudlog.info("weather_news: fetching piper (~25 MB, once)")
  tgz = CACHE / "piper_linux_aarch64.tar.gz"
  if not tgz.exists() or tgz.stat().st_size < 1_000_000:
    _curl(PIPER_TGZ_URL, tgz, min_bytes=1_000_000)
  _extract(tgz, CACHE)
  if PIPER_BIN.is_file():
    PIPER_BIN.chmod(0o755)
    return PIPER_BIN
  return None


def _piper_onnx(vid: str) -> Path:
  name = PIPER_MODELS[vid][0]
  return VOICE_DIR / f"{name}.onnx"


def _ensure_piper_model(vid: str, on_status=None) -> Path | None:
  name, onnx_url, json_url = PIPER_MODELS[vid]
  onnx = VOICE_DIR / f"{name}.onnx"
  js = VOICE_DIR / f"{name}.onnx.json"
  if not onnx.exists() or onnx.stat().st_size < 1_000_000:
    if on_status:
      on_status("downloading voice")
    cloudlog.info(f"weather_news: fetching {name}")
    _curl(onnx_url, onnx, min_bytes=1_000_000)
  if not js.exists():
    _curl(json_url, js, min_bytes=64)
  return onnx if onnx.exists() and onnx.stat().st_size > 1_000_000 else None


def _sherpa_bin() -> Path | None:
  for p in SHERPA_DIR.rglob("sherpa-onnx-offline-tts"):
    if p.is_file() and os.access(p, os.X_OK):
      return p
  return None


def _kokoro_files() -> tuple[Path, Path, Path, Path, Path | None] | None:
  model = next(KOKORO_DIR.rglob("model.onnx"), None) or next(KOKORO_DIR.rglob("*.onnx"), None)
  voices = next(KOKORO_DIR.rglob("voices.bin"), None)
  tokens = next(KOKORO_DIR.rglob("tokens.txt"), None)
  data = next((p for p in KOKORO_DIR.rglob("espeak-ng-data") if p.is_dir()), None)
  lexicon = next(KOKORO_DIR.rglob("lexicon-us-en.txt"), None) or next(KOKORO_DIR.rglob("lexicon*.txt"), None)
  if model and voices and tokens and data and model.stat().st_size > 1_000_000:
    return model, voices, tokens, data, lexicon
  return None


def _ensure_sherpa(on_status=None) -> Path | None:
  got = _sherpa_bin()
  if got:
    return got
  if os.uname().machine not in ("aarch64", "arm64"):
    which = shutil.which("sherpa-onnx-offline-tts")
    return Path(which) if which else None
  if on_status:
    on_status("downloading voice")
  tgz = CACHE / "sherpa-aarch64.tar.bz2"
  if not tgz.exists() or tgz.stat().st_size < 1_000_000:
    cloudlog.info("weather_news: fetching sherpa (~26 MB, once)")
    _curl(SHERPA_TGZ_URL, tgz, min_bytes=1_000_000)
  if on_status:
    on_status("installing")
  _extract(tgz, SHERPA_DIR)
  got = _sherpa_bin()
  if got:
    got.chmod(0o755)
  return got


def _ensure_kokoro(on_status=None) -> tuple[Path, Path, Path, Path, Path | None] | None:
  got = _kokoro_files()
  if got:
    return got
  if on_status:
    on_status("downloading voice")
  tgz = CACHE / "kokoro-int8.tar.bz2"
  if not tgz.exists() or tgz.stat().st_size < 1_000_000:
    cloudlog.info("weather_news: fetching kokoro (~126 MB, once)")
    _curl(KOKORO_TGZ_URL, tgz, min_bytes=1_000_000, timeout=600)
  if on_status:
    on_status("installing")
  _extract(tgz, KOKORO_DIR)
  return _kokoro_files()


def ready(vid: str) -> bool:
  if vid in PIPER_MODELS:
    onnx = _piper_onnx(vid)
    return PIPER_BIN.is_file() and onnx.is_file() and onnx.stat().st_size > 1_000_000
  if vid == "human":
    return _sherpa_bin() is not None and _kokoro_files() is not None
  return False


def ensure(vid: str, on_status=None) -> bool:
  try:
    if vid in PIPER_MODELS:
      return bool(_ensure_piper(on_status) and _ensure_piper_model(vid, on_status))
    if vid == "human":
      return bool(_ensure_sherpa(on_status) and _ensure_kokoro(on_status))
  except Exception:
    cloudlog.exception(f"weather_news: ensure {vid} failed")
  return False


def _render_piper(text: str, dest: Path, vid: str, on_status=None) -> bool:
  try:
    binary = _ensure_piper(on_status)
    model = _ensure_piper_model(vid, on_status)
  except Exception:
    cloudlog.exception("weather_news: piper bootstrap failed")
    return False
  if not binary or not model:
    return False
  if on_status:
    on_status("rendering")
  env = os.environ.copy()
  lib = str(binary.parent)
  env["LD_LIBRARY_PATH"] = lib + ((":" + env["LD_LIBRARY_PATH"]) if env.get("LD_LIBRARY_PATH") else "")
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


def _render_kokoro(text: str, dest: Path, on_status=None) -> bool:
  try:
    binary = _ensure_sherpa(on_status)
    files = _ensure_kokoro(on_status)
  except Exception:
    cloudlog.exception("weather_news: kokoro bootstrap failed")
    return False
  if not binary or not files:
    return False
  model, voices, tokens, data, lexicon = files
  if on_status:
    on_status("rendering")
  env = os.environ.copy()
  lib_dirs = [str(binary.parent), str(binary.parent.parent / "lib")]
  env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + [env.get("LD_LIBRARY_PATH", "")]).strip(":")
  cmd = [
    str(binary),
    f"--kokoro-model={model}",
    f"--kokoro-voices={voices}",
    f"--kokoro-tokens={tokens}",
    f"--kokoro-data-dir={data}",
    "--num-threads=2",
    "--sid=2",
    f"--output-filename={dest}",
  ]
  if lexicon:
    cmd.insert(-2, f"--kokoro-lexicon={lexicon}")
  cmd.append(text)
  try:
    subprocess.run(
      cmd, check=False, env=env,
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
      preexec_fn=lambda: os.nice(10),
    )
    return dest.exists() and dest.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: kokoro render failed")
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


def _render_espeak(text: str, dest: Path) -> bool:
  got = _ensure_espeak()
  if not got:
    return False
  espeak, env, data = got
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


def render_wav(text: str, dest: Path, voice: str = "high", on_status=None) -> bool:
  if voice == "human":
    if _render_kokoro(text, dest, on_status):
      return True
    cloudlog.warning("weather_news: kokoro unavailable, piper high fallback")
    voice = "high"
  if voice not in PIPER_MODELS:
    voice = "high"
  if _render_piper(text, dest, voice, on_status):
    return True
  cloudlog.warning("weather_news: piper unavailable, espeak fallback")
  if on_status:
    on_status("rendering")
  return _render_espeak(text, dest)


def speak_lines(lines: list[str], aggressive: bool, on_status=None, voice: str = "high") -> bool:
  text = " ".join(ln.strip() for ln in lines if ln and ln.strip())
  if not text:
    return False
  tag = "aggressive" if aggressive else "nice"
  cloudlog.info(f"weather_news [{tag}/{voice}]: {text[:160]}")

  tmp = Path(tempfile.mkdtemp(prefix="wxnews_"))
  try:
    wav = tmp / "cycle.wav"
    if not render_wav(text, wav, voice, on_status):
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
