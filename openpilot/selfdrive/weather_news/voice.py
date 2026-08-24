#!/usr/bin/env python3
"""On-device TTS for Weather Lady. Renders WAV, then soundd plays it.

Never uses aplay — soundd already owns the C4 speaker. espeak-ng is resolved
in order: system binary, cached extract under /data/weather_news, then a
one-time Debian arm64 bootstrap into that cache.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

from openpilot.common.swaglog import cloudlog

WXNEWS_WAV = Path("/data/wxnews.wav")
WXNEWS_PLAY = Path("/data/wxnews_play")
CACHE = Path("/data/weather_news")
DEB_DIR = CACHE / "debs"
ROOT = CACHE / "root"

# Bullseye arm64 — glibc 2.31, runs on AGNOS 20.04 and newer.
_POOL = "https://deb.debian.org/debian/pool/main"
_DEBS = (
  f"{_POOL}/e/espeak-ng/espeak-ng_1.50+dfsg-7+deb11u1_arm64.deb",
  f"{_POOL}/e/espeak-ng/espeak-ng-data_1.50+dfsg-7+deb11u1_arm64.deb",
  f"{_POOL}/e/espeak-ng/libespeak-ng1_1.50+dfsg-7+deb11u1_arm64.deb",
  f"{_POOL}/p/pcaudiolib/libpcaudio0_1.1-6_arm64.deb",
  f"{_POOL}/s/sonic/libsonic0_0.2.0-10_arm64.deb",
)

_espeak_bin: Optional[str] = None
_espeak_env: dict[str, str] | None = None
_espeak_data: Optional[str] = None


def _which(names: list[str]) -> Optional[str]:
  for n in names:
    p = shutil.which(n)
    if p:
      return p
  return None


def _extract_deb(deb: Path, dest: Path) -> None:
  raw = deb.read_bytes()
  if not raw.startswith(b"!<arch>\n"):
    raise ValueError(f"not an ar archive: {deb}")
  off = 8
  data_blob = None
  while off + 60 <= len(raw):
    hdr = raw[off:off + 60]
    name = hdr[0:16].decode("ascii", "replace").strip()
    try:
      size = int(hdr[48:58].decode("ascii").strip())
    except ValueError:
      break
    off += 60
    blob = raw[off:off + size]
    off += size + (size % 2)
    if name.startswith("data.tar"):
      data_blob = blob
      break
  if data_blob is None:
    raise ValueError(f"no data.tar in {deb}")
  mode = "r:gz"
  if data_blob.startswith(b"\xfd7zXZ") or deb.name.endswith(".xz"):
    mode = "r:xz"
  elif data_blob[:2] == b"\x1f\x8b":
    mode = "r:gz"
  elif data_blob[:2] == b"BZ":
    mode = "r:bz2"
  else:
    # debian data.tar.xz often has xz magic
    if data_blob[:6] == b"\xfd7zXZ\x00":
      mode = "r:xz"
    else:
      mode = "r:*"
  dest.mkdir(parents=True, exist_ok=True)
  with tarfile.open(fileobj=io.BytesIO(data_blob), mode=mode) as tf:
    try:
      tf.extractall(dest, filter="data")
    except TypeError:
      tf.extractall(dest)


def _download(url: str, dest: Path) -> None:
  dest.parent.mkdir(parents=True, exist_ok=True)
  subprocess.run(
    ["curl", "-fsSL", "--retry", "3", "--max-time", "60", "-o", str(dest), url],
    check=True,
  )
  if dest.stat().st_size < 1024:
    raise RuntimeError(f"tiny download {url}")


def _bootstrap_arm64() -> bool:
  if os.uname().machine not in ("aarch64", "arm64"):
    return False
  marker = ROOT / ".ok"
  if marker.exists() and (ROOT / "usr/bin/espeak-ng").exists():
    return True
  cloudlog.info("weather_news: bootstrapping espeak-ng into /data/weather_news")
  DEB_DIR.mkdir(parents=True, exist_ok=True)
  try:
    for url in _DEBS:
      name = url.rsplit("/", 1)[-1]
      deb = DEB_DIR / name
      if not deb.exists():
        _download(url, deb)
      _extract_deb(deb, ROOT)
    bin_path = ROOT / "usr/bin/espeak-ng"
    if not bin_path.exists():
      return False
    bin_path.chmod(0o755)
    marker.write_text("1")
    return True
  except Exception:
    cloudlog.exception("weather_news: espeak bootstrap failed")
    return False


def _lib_paths() -> list[str]:
  out = []
  for p in (
    ROOT / "usr/lib/aarch64-linux-gnu",
    ROOT / "lib/aarch64-linux-gnu",
    ROOT / "usr/lib",
  ):
    if p.is_dir():
      out.append(str(p))
  return out


def _data_path() -> Optional[str]:
  for p in (
    ROOT / "usr/lib/aarch64-linux-gnu/espeak-ng-data",
    ROOT / "usr/share/espeak-ng-data",
    ROOT / "usr/lib/espeak-ng-data",
  ):
    if p.is_dir():
      return str(p)
  return None


def resolve_espeak() -> tuple[Optional[str], dict[str, str], Optional[str]]:
  global _espeak_bin, _espeak_env, _espeak_data
  if _espeak_bin:
    return _espeak_bin, _espeak_env or {}, _espeak_data

  env = os.environ.copy()
  data = None
  system = _which(["espeak-ng", "espeak"])
  if system:
    _espeak_bin, _espeak_env, _espeak_data = system, env, None
    return system, env, None

  cached = ROOT / "usr/bin/espeak-ng"
  if not cached.exists():
    _bootstrap_arm64()
  if cached.exists():
    libs = _lib_paths()
    if libs:
      env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")]).strip(":")
    data = _data_path()
    _espeak_bin, _espeak_env, _espeak_data = str(cached), env, data
    return str(cached), env, data

  return None, env, None


def render_wav(text: str, dest: Path, aggressive: bool) -> bool:
  espeak, env, data = resolve_espeak()
  if not espeak:
    cloudlog.warning("weather_news: no espeak-ng — cannot speak")
    return False

  if aggressive:
    voice, pitch, speed, amp, gap = "en-us+m3", "26", "178", "200", "3"
  else:
    voice, pitch, speed, amp, gap = "en-us+f3", "58", "142", "170", "7"

  cmd = [espeak, "-v", voice, "-p", pitch, "-s", speed, "-a", amp, "-g", gap, "-w", str(dest), text]
  if data:
    cmd[1:1] = ["--path", str(Path(data).parent)]

  try:
    subprocess.run(cmd, check=False, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
  except Exception:
    cloudlog.exception("weather_news: espeak render failed")
    return False
  try:
    return dest.exists() and dest.stat().st_size > 800
  except OSError:
    return False


def concat_wavs(paths: list[Path], dest: Path, gap_s: float = 0.55) -> bool:
  chunks: list[bytes] = []
  rate = nch = sw = None
  for p in paths:
    try:
      with wave.open(str(p), "rb") as w:
        if rate is None:
          rate, nch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        elif (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (rate, nch, sw):
          cloudlog.warning(f"weather_news: skip wav format mismatch {p}")
          continue
        chunks.append(w.readframes(w.getnframes()))
        if gap_s > 0:
          chunks.append(b"\x00" * int(rate * gap_s) * nch * sw)
    except Exception:
      cloudlog.exception(f"weather_news: bad wav {p}")
  if not chunks or rate is None:
    return False
  dest.parent.mkdir(parents=True, exist_ok=True)
  tmp = dest.with_suffix(".tmp")
  with wave.open(str(tmp), "wb") as o:
    o.setnchannels(nch)
    o.setsampwidth(sw)
    o.setframerate(rate)
    o.writeframes(b"".join(chunks))
  tmp.replace(dest)
  return dest.exists() and dest.stat().st_size > 800


def queue_soundd(wav: Path) -> bool:
  """Copy into the soundd oneshot slot. soundd owns ALSA."""
  try:
    WXNEWS_WAV.parent.mkdir(parents=True, exist_ok=True)
    if wav.resolve() != WXNEWS_WAV:
      shutil.copyfile(wav, WXNEWS_WAV)
    WXNEWS_PLAY.write_text("1")
    # Give soundd a moment to pick it up; don't fail if an alert is holding drain.
    for _ in range(20):
      time.sleep(0.1)
      if not WXNEWS_PLAY.exists():
        break
    return WXNEWS_WAV.exists() and WXNEWS_WAV.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: queue_soundd failed")
    return False


def speak_lines(lines: list[str], aggressive: bool) -> bool:
  """Render each line, concat, hand to soundd. Returns True if a wav was queued."""
  text_lines = [ln.strip() for ln in lines if ln and ln.strip()]
  if not text_lines:
    return False
  tag = "ARA/AGGRESSIVE" if aggressive else "NICE"
  joined = " ".join(text_lines)
  cloudlog.info(f"weather_news [{tag}]: {joined[:160]}...")
  print(f"\n===== WEATHER/NEWS [{tag}] =====\n{joined}\n===== END =====\n")

  tmp = Path(tempfile.mkdtemp(prefix="wxnews_"))
  try:
    parts: list[Path] = []
    for i, line in enumerate(text_lines):
      part = tmp / f"{i:02d}.wav"
      if render_wav(line, part, aggressive):
        parts.append(part)
    if not parts:
      return False
    out = tmp / "cycle.wav"
    if not concat_wavs(parts, out):
      return False
    return queue_soundd(out)
  finally:
    shutil.rmtree(tmp, ignore_errors=True)
