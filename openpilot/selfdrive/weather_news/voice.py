"""Grok Ara TTS. Enhance + 48 kHz queue for soundd. No on-device synthesizers."""

from __future__ import annotations

import shutil
import tempfile
import wave
from pathlib import Path

import numpy as np

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.weather_news import config as grok_cfg
from openpilot.selfdrive.weather_news import grok as grok_api

WXNEWS_WAV = Path("/data/wxnews.wav")
WXNEWS_PLAY = Path("/data/wxnews_play")
TARGET_RATE = 48000

# Standard: clean living-room. Boosted: louder for road noise without C4 crackle.
_PROFILES = {
  False: dict(rms=0.22, peak=0.84, knee=0.80, hp=70.0, shelf_db=1.6, shelf_hz=240.0,
              mud_db=0.0, mud_hz=320.0, pres_db=2.0, pres_hz=1600.0,
              dess_db=-2.8, dess_hz=5800.0, hs_db=-1.8, hs_hz=7500.0,
              win_s=0.080, thresh=0.13, ratio=1.7, makeup_cap=2.0),
  True: dict(rms=0.44, peak=0.97, knee=0.91, hp=90.0, shelf_db=0.8, shelf_hz=200.0,
             mud_db=-2.0, mud_hz=300.0, pres_db=3.0, pres_hz=1350.0,
             dess_db=-5.5, dess_hz=5400.0, hs_db=-4.0, hs_hz=6500.0,
             win_s=0.100, thresh=0.09, ratio=2.35, makeup_cap=4.0),
}


def _resample_cubic(x: np.ndarray, src: int, dst: int) -> np.ndarray:
  if src == dst or len(x) < 2:
    return x.astype(np.float32)
  n_out = int(round(len(x) * dst / float(src)))
  if len(x) < 4:
    return np.interp(np.linspace(0, 1, n_out, endpoint=False),
                     np.linspace(0, 1, len(x), endpoint=False), x).astype(np.float32)
  t = np.linspace(0, len(x) - 1, n_out, endpoint=False)
  i = np.floor(t).astype(np.int32)
  f = (t - i).astype(np.float32)
  xp = np.pad(x.astype(np.float32), 2, mode="edge")
  i = i + 2
  p0, p1, p2, p3 = xp[i - 1], xp[i], xp[i + 1], xp[i + 2]
  f2 = f * f
  f3 = f2 * f
  return (0.5 * ((2.0 * p1) + (-p0 + p2) * f +
                 (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * f2 +
                 (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * f3)).astype(np.float32)


def _eq_gain(n: int, rate: int, p: dict) -> np.ndarray:
  f = np.maximum(np.fft.rfftfreq(n, 1.0 / rate), 1.0)
  hp = (f ** 4) / (f ** 4 + p["hp"] ** 4)
  shelf = 1.0 + (10 ** (p["shelf_db"] / 20.0) - 1.0) * (p["shelf_hz"] ** 2) / (f * f + p["shelf_hz"] ** 2)
  mud = 10 ** ((p["mud_db"] / 20.0) * np.exp(-0.5 * (np.log(f / p["mud_hz"]) * 1.6) ** 2))
  pres = 10 ** ((p["pres_db"] / 20.0) * np.exp(-0.5 * (np.log(f / p["pres_hz"]) * 1.45) ** 2))
  dess = 10 ** ((p["dess_db"] / 20.0) * np.exp(-0.5 * (np.log(f / p["dess_hz"]) * 1.7) ** 2))
  hs = 1.0 + (10 ** (p["hs_db"] / 20.0) - 1.0) * (f * f / (f * f + p["hs_hz"] ** 2))
  return (hp * shelf * mud * pres * dess * hs).astype(np.float32)


def _eq_ola(x: np.ndarray, rate: int, p: dict) -> np.ndarray:
  """Overlap-add EQ in 4096-sample hops so a 120s briefing never does one giant rfft."""
  hop = 4096
  n = len(x)
  if n < 32:
    return x
  win = np.hanning(hop * 2).astype(np.float32)
  gain = _eq_gain(hop * 2, rate, p)
  acc = np.zeros(n + hop * 2, dtype=np.float32)
  wacc = np.zeros_like(acc)
  pad = np.pad(x.astype(np.float32), hop, mode="edge")
  i = 0
  while i < n:
    sl = pad[i:i + hop * 2]
    if len(sl) < hop * 2:
      sl = np.pad(sl, (0, hop * 2 - len(sl)))
    spec = np.fft.rfft(sl * win)
    y = np.fft.irfft(spec * gain, n=hop * 2).astype(np.float32)
    acc[i:i + hop * 2] += y * win
    wacc[i:i + hop * 2] += win * win
    i += hop
  den = np.maximum(wacc[hop:hop + n], 1e-6)
  return (acc[hop:hop + n] / den).astype(np.float32)


def _sliding_rms(x: np.ndarray, win: int) -> np.ndarray:
  n = len(x)
  w = max(int(win), 1)
  pad = np.full(w, float(x[0] * x[0]) if n else 0.0, dtype=np.float64)
  x2 = np.concatenate((pad, np.square(x, dtype=np.float64)))
  c = np.cumsum(x2)
  return np.sqrt(np.maximum((c[w:w + n] - c[:n]) / w, 1e-12)).astype(np.float32)


def _compress(x: np.ndarray, rate: int, p: dict) -> np.ndarray:
  # Fast peak-stop first so later RMS makeup can actually get loud without clipping.
  env = _sliding_rms(x, int(0.016 * rate))
  stop = max(p["thresh"] * 1.7, 0.10)
  y = x * np.minimum(1.0, stop / np.maximum(env, 1e-5))
  rms = _sliding_rms(y, int(p["win_s"] * rate))
  over = np.maximum(rms / p["thresh"], 1.0)
  y = y * (over ** (1.0 / p["ratio"] - 1.0))
  g = float(np.sqrt(np.mean(np.square(y))) or 1e-5)
  makeup = float(np.clip(p["rms"] / g, 1.0, p["makeup_cap"]))
  return y * makeup


def _soft_limit(x: np.ndarray, p: dict) -> np.ndarray:
  a = np.abs(x)
  span = max(p["peak"] - p["knee"], 1e-4)
  shaped = p["knee"] + span * np.tanh((a - p["knee"]) / span)
  y = (np.sign(x) * np.where(a > p["knee"], shaped, a)).astype(np.float32)
  peak = float(np.max(np.abs(y))) if len(y) else 0.0
  if peak > p["peak"]:
    y = y * (p["peak"] / peak)
  return y


def enhance_wav(src: Path, dest: Path, boosted: bool = True) -> bool:
  """Voice-only 48 kHz WAV. Boosted is louder for road noise; both stay under the C4 breakup zone."""
  p = _PROFILES[bool(boosted)]
  try:
    with wave.open(str(src), "r") as w:
      ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
      raw = w.readframes(n)
    if sw != 2 or n < 400:
      return False
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch == 2:
      x = x.reshape(-1, 2).mean(axis=1)
    elif ch != 1:
      return False
    if rate != TARGET_RATE:
      x = _resample_cubic(x, rate, TARGET_RATE)
    x = _eq_ola(x, TARGET_RATE, p)
    x = _compress(x, TARGET_RATE, p)
    x = _soft_limit(x, p)
    if boosted:
      rms = float(np.sqrt(np.mean(np.square(x))) or 1e-5)
      peak = float(np.max(np.abs(x)) or 1e-5)
      if rms < 0.36 and peak > 1e-4:
        extra = min(0.42 / rms, 0.95 / peak, 1.7)
        if extra > 1.02:
          x = _soft_limit(x * extra, p)
    fi = int(0.014 * TARGET_RATE)
    fo = int(0.045 * TARGET_RATE)
    if fi > 0 and len(x) > fi:
      x[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)
    if fo > 0 and len(x) > fo:
      x[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)
    pcm = np.clip(x * 32767.0, -32767, 32767).astype(np.int16)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as out:
      out.setnchannels(1)
      out.setsampwidth(2)
      out.setframerate(TARGET_RATE)
      out.writeframes(pcm.tobytes())
    return dest.exists() and dest.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: enhance failed")
    return False


def speak_lines(lines: list[str], aggressive: bool, on_status=None, voice: str | None = None) -> bool:
  text = " ".join(ln.strip() for ln in lines if ln and ln.strip())
  if not text:
    return False
  boosted = grok_cfg.playback_boosted()
  tag = "unhinged" if aggressive else "nice"
  mix = "boosted" if boosted else "standard"
  cloudlog.info(f"weather_news [{tag}/ara/{mix}]: {text[:160]}")
  tmp = Path(tempfile.mkdtemp(prefix="wxnews_"))
  try:
    raw = tmp / "raw.wav"
    wav = tmp / "cycle.wav"
    if on_status:
      on_status("speaking")
    if not grok_api.tts_wav(text, raw, unhinged=aggressive):
      return False
    if not enhance_wav(raw, wav, boosted=boosted):
      cloudlog.warning("weather_news: enhance missed, queueing raw tts")
      wav = raw
    if on_status:
      on_status("playing")
    WXNEWS_WAV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wav, WXNEWS_WAV)
    WXNEWS_PLAY.write_text("1")
    kb = WXNEWS_WAV.stat().st_size / 1024.0
    cloudlog.info(f"weather_news: queued {kb:.0f} kB {TARGET_RATE} Hz wav {mix}")
    return WXNEWS_WAV.stat().st_size > 800
  except Exception:
    cloudlog.exception("weather_news: queue failed")
    return False
  finally:
    shutil.rmtree(tmp, ignore_errors=True)
