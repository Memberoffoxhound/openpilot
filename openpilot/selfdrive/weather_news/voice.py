#!/usr/bin/env python3
"""Render a wav with espeak-ng, then hand it to soundd. soundd owns the speaker."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import wave
from pathlib import Path

from openpilot.common.swaglog import cloudlog

WXNEWS_WAV = Path("/data/wxnews.wav")
WXNEWS_PLAY = Path("/data/wxnews_play")
ROOT = Path("/data/weather_news/root")
DEB_DIR = Path("/data/weather_news/debs")

# bullseye arm64 / glibc 2.31 — runs on AGNOS. one-shot extract into /data.
_POOL = "https://deb.debian.org/debian/pool/main"
_DEBS = (
  f"{_POOL}/e/espeak-ng/espeak-ng_1.50+dfsg-7+deb11u1_arm64.deb",
  f"{_POOL}/e/espeak-ng/espeak-ng-data_1.50+dfsg-7+deb11u1_arm64.deb",
  f"{_POOL}/e/espeak-ng/libespeak-ng1_1.50+dfsg-7+deb11u1_arm64.deb",
  f"{_POOL}/p/pcaudiolib/libpcaudio0_1.1-6_arm64.deb",
  f"{_POOL}/s/sonic/libsonic0_0.2.0-10_arm64.deb",
)

_espeak: tuple[str, dict[str, str], str | None] | None = None


def _extract_deb(deb: Path, dest: Path) -> None:
  raw = deb.read_bytes()
  if not raw.startswith(b"!<arch>\n"):
    raise ValueError(f"not an ar archive: {deb}")
  off, blob = 8, None
  while off + 60 <= len(raw):
    hdr = raw[off:off + 60]
    name = hdr[0:16].decode("ascii", "replace").strip()
    try:
      size = int(hdr[48:58].decode("ascii").strip())
    except ValueError:
      break
    off += 60
    if name.startswith("data.tar"):
      blob = raw[off:off + size]
      break
    off += size + (size % 2)
  if blob is None:
    raise ValueError(f"no data.tar in {deb}")
  dest.mkdir(parents=True, exist_ok=True)
  with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
    try:
      tf.extractall(dest, filter="data")
    except TypeError:
      tf.extractall(dest)


def _bootstrap() -> None:
  if os.uname().machine not in ("aarch64", "arm64"):
    return
  if (ROOT / "usr/bin/espeak-ng").exists():
    return
  cloudlog.info("weather_news: extracting espeak-ng into /data/weather_news")
  DEB_DIR.mkdir(parents=True, exist_ok=True)
  for url in _DEBS:
    deb = DEB_DIR / url.rsplit("/", 1)[-1]
    if not deb.exists():
      subprocess.run(["curl", "-fsSL", "--retry", "3", "--max-time", "60", "-o", str(deb), url], check=True)
    _extract_deb(deb, ROOT)
  bin_path = ROOT / "usr/bin/espeak-ng"
  if bin_path.exists():
    bin_path.chmod(0o755)


def _resolve() -> tuple[str, dict[str, str], str | None] | None:
  global _espeak
  if _espeak:
    return _espeak

  env = os.environ.copy()
  system = shutil.which("espeak-ng") or shutil.which("espeak")
  if system:
    _espeak = (system, env, None)
    return _espeak

  try:
    _bootstrap()
  except Exception:
    cloudlog.exception("weather_news: espeak bootstrap failed")
    return None

  cached = ROOT / "usr/bin/espeak-ng"
  if not cached.exists():
    return None
  libs = [str(p) for p in (ROOT / "usr/lib/aarch64-linux-gnu", ROOT / "lib/aarch64-linux-gnu") if p.is_dir()]
  if libs:
    env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")]).strip(":")
  data = None
  for p in (ROOT / "usr/lib/aarch64-linux-gnu/espeak-ng-data", ROOT / "usr/share/espeak-ng-data"):
    if p.is_dir():
      data = str(p)
      break
  _espeak = (str(cached), env, data)
  return _espeak


def render_wav(text: str, dest: Path, aggressive: bool) -> bool:
  got = _resolve()
  if not got:
    cloudlog.warning("weather_news: no espeak-ng")
    return False
  espeak, env, data = got
  if aggressive:
    voice, pitch, speed, amp, gap = "en-us+m3", "26", "178", "200", "3"
  else:
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
