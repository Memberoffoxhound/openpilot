import math
import os
import json
import threading
import numpy as np
import time
import wave


from openpilot.cereal import log, messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.hardware import HARDWARE
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import Ratekeeper
from openpilot.common.utils import retry
from openpilot.common.swaglog import cloudlog

from openpilot.system import micd

SAMPLE_RATE = 48000
SAMPLE_BUFFER = 4096 # (approx 100ms)
MAX_VOLUME = 1.0
THEME_RMS = 0.24
THEME_PEAK = 0.85
THEME_KNEE = 0.72
LUDI_PLAY = "/data/ludicrous_play"
BUCKLE_PLAY = "/data/buckle_play"
BUCKLE_MODE = "/data/buckle_sound"
LUDI_WAVS = (
  "/data/ludicrous.wav",
  BASEDIR + "/openpilot/selfdrive/assets/sounds/ludicrous.wav",
)
BUCKLE_WAVS = (
  "/data/buckle.wav",
  BASEDIR + "/openpilot/selfdrive/assets/sounds/buckle.wav",
)
SHOT_PLAY = "/data/screenshot_play"
SHOT_WAVS = (
  "/data/shutter.wav",
  BASEDIR + "/openpilot/selfdrive/assets/sounds/shutter.wav",
)
EIGHTY_WAVS = (
  "/data/88mph.wav",
  BASEDIR + "/openpilot/selfdrive/assets/sounds/88mph.wav",
)
DELOREAN_MODE = "/data/delorean_sound"
DELOREAN_PLAY = "/data/delorean_play"
WXNEWS_PLAY = "/data/wxnews_play"
WXNEWS_WAVS = ("/data/wxnews.wav",)
BUCKLE_GATE = "/data/buckle_gate.json"
BUCKLE_DRIVE_S = 20 * 60
BUCKLE_WAIT_S = 3 * 3600
DELOREAN_HOLD_S = 1.5          # wait for ignition to settle
DELOREAN_OFFROAD_RESET_S = 10.0  # blips shorter than this are the same drive


def _resample_cubic(x: np.ndarray, src: int, dst: int) -> np.ndarray:
  if src == dst or len(x) < 2:
    return x
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


def _dialog_eq(x: np.ndarray) -> np.ndarray:
  # C4 speaker: dump rumble, lift speech, cut the tinny breakup.
  n = len(x)
  spec = np.fft.rfft(x)
  f = np.maximum(np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE), 1.0)
  hp = (f ** 4) / (f ** 4 + 200.0 ** 4)
  pres = 10 ** ((6.0 / 20.0) * np.exp(-0.5 * (np.log(f / 1700.0) * 2.0) ** 2))
  dip = 10 ** ((-3.0 / 20.0) * np.exp(-0.5 * (np.log(f / 4500.0) * 3.0) ** 2))
  hs = 1.0 + (10 ** (-5.5 / 20.0) - 1.0) * (f * f / (f * f + 5500.0 ** 2))
  return np.fft.irfft(spec * (hp * pres * dip * hs), n=n).astype(np.float32)


def _sliding_rms(x: np.ndarray, win: int) -> np.ndarray:
  n = len(x)
  w = max(int(win), 1)
  pad = np.full(w, float(x[0] * x[0]) if n else 0.0, dtype=np.float64)
  x2 = np.concatenate((pad, np.square(x, dtype=np.float64)))
  c = np.cumsum(x2)
  return np.sqrt(np.maximum((c[w:w + n] - c[:n]) / w, 1e-12)).astype(np.float32)


def _agc(x: np.ndarray) -> np.ndarray:
  rms = _sliding_rms(x, int(0.025 * SAMPLE_RATE))
  gain = np.clip(THEME_RMS / np.maximum(rms, 1e-5), 0.40, 8.0)
  return x * gain


def _soft_limit(x: np.ndarray) -> np.ndarray:
  a = np.abs(x)
  span = THEME_PEAK - THEME_KNEE
  shaped = THEME_KNEE + span * np.tanh((a - THEME_KNEE) / span)
  return (np.sign(x) * np.where(a > THEME_KNEE, shaped, a)).astype(np.float32)


def _theme_prep(x: np.ndarray) -> np.ndarray:
  # rfft of a 60s clip stalls the 20 Hz thread; peak-limit long oneshots instead.
  if len(x) < int(0.45 * SAMPLE_RATE) or len(x) > int(8.0 * SAMPLE_RATE):
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > THEME_PEAK:
      x = x * (THEME_PEAK / peak)
    return x.astype(np.float32)
  return _soft_limit(_agc(_dialog_eq(x)))


def load_wav(*paths) -> np.ndarray | None:
  for path in paths:
    try:
      size = os.path.getsize(path)
      with wave.open(path, "r") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        framesize = max(int(ch), 1) * max(int(sw), 1)
        cap = max(0, int(size) // framesize)
        if n < 0 or n > cap:
          cloudlog.warning(f"soundd: wav header nframes={n} capped to {cap} for {path} ({size} bytes)")
          n = cap
        raw = w.readframes(n)
      if sw != 2:
        continue
      x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
      if ch == 2:
        x = x.reshape(-1, 2).mean(axis=1)
      elif ch != 1:
        continue
      x /= 32768.0
      if rate != SAMPLE_RATE:
        x = _resample_cubic(x, rate, SAMPLE_RATE)
      return _theme_prep(x)
    except Exception:
      cloudlog.exception(f"soundd: failed to load {path}")
      continue
  return None


def _flag(path: str) -> bool:
  try:
    return open(path).read().strip() in ("1", "true")
  except Exception:
    return False


def _clear(path: str) -> None:
  try:
    os.unlink(path)
  except Exception:
    pass


MIN_VOLUME = 0.1
ALERT_RAMP_TIME = 4 # seconds to ramp to max volume for warningImmediate
SELFDRIVE_STATE_TIMEOUT = 5 # 5 seconds
FILTER_DT = 1. / (micd.SAMPLE_RATE / micd.FFT_SAMPLES)

AMBIENT_DB = 26 # DB where MIN_VOLUME is applied
DB_SCALE = 30 # AMBIENT_DB + DB_SCALE is where MAX_VOLUME is applied

VOLUME_BASE = 20
if HARDWARE.get_device_type() == "tizi":
  AMBIENT_DB = 30
  VOLUME_BASE = 10

AudibleAlert = log.SelfdriveState.AudibleAlert


sound_list: dict[int, tuple[str, int | None, float]] = {
  # AudibleAlert, file name, play count (none for infinite)
  AudibleAlert.engage: ("engage.wav", 1, MAX_VOLUME),
  AudibleAlert.disengage: ("disengage.wav", 1, MAX_VOLUME),
  AudibleAlert.refuse: ("refuse.wav", 1, MAX_VOLUME),

  AudibleAlert.prompt: ("warning.wav", 1, MAX_VOLUME),
  AudibleAlert.promptRepeat: ("warning.wav", None, MAX_VOLUME),
  AudibleAlert.promptDistracted: ("dm_warning.wav", None, MAX_VOLUME),

  AudibleAlert.preAlert: ("pre_alert.wav", 1, MAX_VOLUME),

  AudibleAlert.warningSoft: ("critical.wav", None, MAX_VOLUME),
  AudibleAlert.warningImmediate: ("dm_critical.wav", None, MAX_VOLUME),
}

def check_selfdrive_timeout_alert(sm):
  ss_missing = time.monotonic() - sm.recv_time['selfdriveState']

  if ss_missing > SELFDRIVE_STATE_TIMEOUT:
    if sm['selfdriveState'].enabled and (ss_missing - SELFDRIVE_STATE_TIMEOUT) < 10:
      return True

  return False


class Soundd:
  def __init__(self):
    self.load_sounds()
    self.oneshots: list[list] = []  # [np.ndarray, index, tag]
    self._queue: list[list] = []
    self._lock = threading.Lock()
    self.prev_unlatched: bool | None = None
    self._play_eighty = False
    self._buckle_armed, self._buckle_t, self._onroad_t0, self._eighty_played = self._load_gate()
    self._started_since = 0.0
    self._offroad_since = 0.0

    self.current_alert = AudibleAlert.none
    self.current_volume = MIN_VOLUME
    self.current_sound_frame = 0

    self.ramp_start_volume = MIN_VOLUME
    self.ramp_start_time = 0.

    self.selfdrive_timeout_alert = False
    self.pending_stop = False

    self.spl_filter_weighted = FirstOrderFilter(0, 2.5, FILTER_DT, initialized=False)

  def _load_gate(self) -> tuple[bool, float, float, bool]:
    try:
      j = json.loads(open(BUCKLE_GATE, encoding="utf-8").read())
      return bool(j.get("armed", True)), float(j.get("t") or 0), float(j.get("onroad_t0") or 0), bool(j.get("eighty_played", False))
    except Exception:
      return True, 0.0, 0.0, False

  def _save_gate(self) -> None:
    try:
      with open(BUCKLE_GATE, "w", encoding="utf-8") as f:
        json.dump({
          "armed": self._buckle_armed,
          "t": self._buckle_t,
          "onroad_t0": self._onroad_t0,
          "eighty_played": self._eighty_played,
        }, f)
    except OSError:
      pass

  def _push(self, tag: str, paths: tuple[str, ...]) -> None:
    # Decode here (20 Hz thread), never in the PortAudio callback. Buffer dies with the oneshot.
    w = load_wav(*paths)
    if w is None:
      return
    with self._lock:
      self._queue.append([w, 0, tag])

  def _tag_busy(self, tag: str) -> bool:
    with self._lock:
      return any(t == tag for _, _, t in self.oneshots) or any(t == tag for _, _, t in self._queue)

  def _drain_flags(self) -> None:
    if _flag(LUDI_PLAY):
      self._push("ludi", LUDI_WAVS)
      _clear(LUDI_PLAY)
    if _flag(BUCKLE_PLAY):
      self._push("buckle", BUCKLE_WAVS)
      _clear(BUCKLE_PLAY)
    if _flag(SHOT_PLAY):
      self._push("shot", SHOT_WAVS)
      _clear(SHOT_PLAY)
    if self._play_eighty or _flag(DELOREAN_PLAY):
      if not self._tag_busy("buckle") and not self._tag_busy("eighty"):
        self._push("eighty", EIGHTY_WAVS)
        self._play_eighty = False
        _clear(DELOREAN_PLAY)
    if _flag(WXNEWS_PLAY):
      if not self._tag_busy("wxnews"):
        self._push("wxnews", WXNEWS_WAVS)
        _clear(WXNEWS_PLAY)

  def load_sounds(self):
    self.loaded_sounds: dict[int, np.ndarray] = {}

    # Stock alerts only. Theme wavs decode in _push when the event fires.
    for sound in sound_list:
      filename, play_count, volume = sound_list[sound]

      with wave.open(BASEDIR + "/openpilot/selfdrive/assets/sounds/" + filename, 'r') as wavefile:
        assert wavefile.getnchannels() == 1
        assert wavefile.getsampwidth() == 2
        assert wavefile.getframerate() == SAMPLE_RATE

        length = wavefile.getnframes()
        self.loaded_sounds[sound] = np.frombuffer(wavefile.readframes(length), dtype=np.int16).astype(np.float32) / (2**16/2)

  def get_sound_data(self, frames): # get "frames" worth of data from the current alert sound, looping when required

    ret = np.zeros(frames, dtype=np.float32)

    if self.current_alert != AudibleAlert.none:
      num_loops = sound_list[self.current_alert][1]
      sound_data = self.loaded_sounds[self.current_alert]
      written_frames = 0

      current_sound_frame = self.current_sound_frame % len(sound_data)
      loops = self.current_sound_frame // len(sound_data)

      while written_frames < frames and (num_loops is None or loops < num_loops):
        available_frames = sound_data.shape[0] - current_sound_frame
        frames_to_write = min(available_frames, frames - written_frames)
        ret[written_frames:written_frames+frames_to_write] = sound_data[current_sound_frame:current_sound_frame+frames_to_write]
        written_frames += frames_to_write
        self.current_sound_frame += frames_to_write
        current_sound_frame = self.current_sound_frame % len(sound_data)
        loops = self.current_sound_frame // len(sound_data)
        if self.pending_stop and current_sound_frame == 0:
          self.current_alert = AudibleAlert.none
          self.pending_stop = False
          break

    out = ret * self.current_volume
    with self._lock:
      if self._queue:
        self.oneshots.extend(self._queue)
        self._queue.clear()
      playing = list(self.oneshots)
    live = []
    sr = float(SAMPLE_RATE)
    for arr, i, tag in playing:
      n = min(frames, len(arr) - i)
      if n > 0:
        dur = len(arr) / sr
        fi, fo = (0.006, 0.02) if dur < 0.45 else (0.012, 0.05)
        idx = np.arange(n, dtype=np.float32) + i
        t = idx / sr
        env = np.ones(n, dtype=np.float32)
        if fi > 0:
          env = np.where(t < fi, np.clip(t / fi, 0.0, 1.0), env)
        if fo > 0:
          env = np.where(t > dur - fo, np.clip((dur - t) / fo, 0.0, 1.0), env)
        out[:n] += arr[i:i + n] * env
        i += n
      if i < len(arr):
        live.append([arr, i, tag])
    with self._lock:
      self.oneshots = live
    return np.clip(out, -1.0, 1.0)

  def callback(self, data_out: np.ndarray, frames: int, time, status) -> None:
    if status:
      cloudlog.warning(f"soundd stream over/underflow: {status}")
    data_out[:frames, 0] = self.get_sound_data(frames)

  def update_alert(self, new_alert):
    current_alert_played_once = self.current_alert == AudibleAlert.none or self.current_sound_frame >= len(self.loaded_sounds[self.current_alert])
    # let looping sounds finish the current loop instead of cutting off mid tone
    if new_alert == AudibleAlert.none and self.current_alert != AudibleAlert.none and sound_list[self.current_alert][1] is None:
      if current_alert_played_once:
        self.pending_stop = True
      else:
        self.current_alert = AudibleAlert.none
        self.current_sound_frame = 0
      return
    self.pending_stop = False
    if self.current_alert != new_alert and (new_alert != AudibleAlert.none or current_alert_played_once):
      if new_alert == AudibleAlert.warningImmediate:
        self.ramp_start_volume = self.current_volume
        self.ramp_start_time = time.monotonic()
      self.current_alert = new_alert
      self.current_sound_frame = 0

  def get_audible_alert(self, sm):
    started = bool(sm['deviceState'].started) if sm.recv_frame['deviceState'] > 0 else False
    if sm.updated['selfdriveState']:
      new_alert = sm['selfdriveState'].alertSound.raw
      self.update_alert(new_alert)
    elif started and check_selfdrive_timeout_alert(sm):
      self.update_alert(AudibleAlert.warningImmediate)
      self.selfdrive_timeout_alert = True
    elif self.selfdrive_timeout_alert or (not started and self.current_alert != AudibleAlert.none):
      self.update_alert(AudibleAlert.none)
      self.selfdrive_timeout_alert = False

  def calculate_volume(self, weighted_db):
    volume = ((weighted_db - AMBIENT_DB) / DB_SCALE) * (MAX_VOLUME - MIN_VOLUME) + MIN_VOLUME
    return math.pow(VOLUME_BASE, (np.clip(volume, MIN_VOLUME, MAX_VOLUME) - 1))

  @retry(attempts=10, delay=3)
  def get_stream(self, sd):
    # reload sounddevice to reinitialize portaudio
    sd._terminate()
    sd._initialize()
    return sd.OutputStream(channels=1, samplerate=SAMPLE_RATE, callback=self.callback, blocksize=SAMPLE_BUFFER)

  def soundd_thread(self):
    # sounddevice must be imported after forking processes
    import sounddevice as sd
    micd.patch_sounddevice(sd)

    sm = messaging.SubMaster(['selfdriveState', 'soundPressure', 'carState', 'deviceState'])

    with self.get_stream(sd) as stream:
      rk = Ratekeeper(20)

      cloudlog.info(f"soundd stream started: {stream.samplerate=} {stream.channels=} {stream.dtype=} {stream.device=}, {stream.blocksize=}")
      while True:
        sm.update(0)

        # freeze volume during alerts to avoid mic feedback increasing volume
        if sm.updated['soundPressure']:
          self.spl_filter_weighted.update(sm["soundPressure"].soundPressureWeightedDb)
          if self.current_alert == AudibleAlert.none:
            self.current_volume = self.calculate_volume(float(self.spl_filter_weighted.x))

        self.get_audible_alert(sm)

        now = time.time()
        started = bool(sm['deviceState'].started) if sm.recv_frame['deviceState'] > 0 else False

        if (not self._buckle_armed) and self._buckle_t and (now - self._buckle_t) >= BUCKLE_WAIT_S:
          self._buckle_armed = True
          self._save_gate()

        if started:
          self._offroad_since = 0.0
          if not self._started_since:
            self._started_since = now
          if not self._onroad_t0:
            self._onroad_t0 = now
            self._save_gate()
          if (now - self._started_since) >= DELOREAN_HOLD_S and _flag(DELOREAN_MODE) and not self._eighty_played:
            self._play_eighty = True
            self._eighty_played = True
            self._save_gate()
        else:
          self._started_since = 0.0
          if self._onroad_t0:
            if not self._offroad_since:
              self._offroad_since = now
            if (now - self._offroad_since) >= DELOREAN_OFFROAD_RESET_S:
              if (now - self._onroad_t0) >= BUCKLE_DRIVE_S:
                self._buckle_armed = True
              self._onroad_t0 = 0.0
              self._eighty_played = False
              self._play_eighty = False
              self._offroad_since = 0.0
              self._save_gate()

        if sm.updated['carState'] and _flag(BUCKLE_MODE):
          unlatched = bool(sm['carState'].seatbeltUnlatched)
          latched_edge = self.prev_unlatched is True and not unlatched
          latched_start = self.prev_unlatched is None and not unlatched
          if (latched_edge or latched_start) and self._buckle_armed:
            self._buckle_armed = False
            self._buckle_t = now
            self._save_gate()
            try:
              open(BUCKLE_PLAY, "w").write("1")
            except OSError:
              pass
          self.prev_unlatched = unlatched

        if self.current_alert != AudibleAlert.warningImmediate:
          self._drain_flags()

        # Ramp up immediate warning sound over 4s
        if self.current_alert == AudibleAlert.warningImmediate:
          elapsed = time.monotonic() - self.ramp_start_time
          ramp_vol = float(np.interp(elapsed, [0, ALERT_RAMP_TIME], [self.ramp_start_volume, MAX_VOLUME]))
          self.current_volume = max(self.current_volume, ramp_vol)

        rk.keep_time()

        assert stream.active


def main():
  s = Soundd()
  s.soundd_thread()


if __name__ == "__main__":
  main()
