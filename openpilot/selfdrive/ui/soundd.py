import math
import os
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
from openpilot.selfdrive.ui.layouts.settings.common import buckle_once

SAMPLE_RATE = 48000
SAMPLE_BUFFER = 4096 # (approx 100ms)
MAX_VOLUME = 1.0
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


def load_wav(*paths) -> np.ndarray | None:
  for path in paths:
    try:
      with wave.open(path, "r") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
      if sw != 2:
        continue
      x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
      if ch == 2:
        x = x.reshape(-1, 2).mean(axis=1)
      elif ch != 1:
        continue
      x /= 32768.0
      if rate != SAMPLE_RATE and len(x) > 1:
        n_out = int(round(len(x) * SAMPLE_RATE / float(rate)))
        x = np.interp(np.linspace(0, 1, n_out, endpoint=False), np.linspace(0, 1, len(x), endpoint=False), x).astype(np.float32)
      peak = float(np.max(np.abs(x))) if len(x) else 0.0
      if peak > 1e-4:
        x = x * (0.98 / peak)
      return x
    except Exception:
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
    self.oneshots: list[list] = []  # [np.ndarray, index]
    self.prev_unlatched: bool | None = None

    self.current_alert = AudibleAlert.none
    self.current_volume = MIN_VOLUME
    self.current_sound_frame = 0

    self.ramp_start_volume = MIN_VOLUME
    self.ramp_start_time = 0.

    self.selfdrive_timeout_alert = False
    self.pending_stop = False

    self.spl_filter_weighted = FirstOrderFilter(0, 2.5, FILTER_DT, initialized=False)

  def load_sounds(self):
    self.loaded_sounds: dict[int, np.ndarray] = {}

    # Load all sounds
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
    if self.current_alert != AudibleAlert.warningImmediate:
      if _flag(LUDI_PLAY):
        w = load_wav(*LUDI_WAVS)
        if w is not None:
          self.oneshots.append([w, 0])
        _clear(LUDI_PLAY)
      if _flag(BUCKLE_PLAY):
        w = load_wav(*BUCKLE_WAVS)
        if w is not None:
          self.oneshots.append([w, 0])
        _clear(BUCKLE_PLAY)
      if _flag(SHOT_PLAY):
        w = load_wav(*SHOT_WAVS)
        if w is not None:
          self.oneshots.append([w, 0])
        _clear(SHOT_PLAY)
    live = []
    sr = float(SAMPLE_RATE)
    for arr, i in self.oneshots:
      n = min(frames, len(arr) - i)
      if n > 0:
        dur = len(arr) / sr
        fi, fo = (0.005, 0.03) if dur < 0.45 else (0.20, 0.35)
        # per-sample fade in/out
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
        live.append([arr, i])
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
    if sm.updated['selfdriveState']:
      new_alert = sm['selfdriveState'].alertSound.raw
      self.update_alert(new_alert)
    elif check_selfdrive_timeout_alert(sm):
      self.update_alert(AudibleAlert.warningImmediate)
      self.selfdrive_timeout_alert = True
    elif self.selfdrive_timeout_alert:
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

    sm = messaging.SubMaster(['selfdriveState', 'soundPressure', 'carState'])

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

        if sm.updated['carState'] and _flag(BUCKLE_MODE):
          unlatched = bool(sm['carState'].seatbeltUnlatched)
          if self.prev_unlatched is True and unlatched is False and buckle_once():
            with open(BUCKLE_PLAY, "w") as f:
              f.write("1")
          self.prev_unlatched = unlatched

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
