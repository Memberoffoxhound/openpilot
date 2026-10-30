"""One drive, recorded frame by frame: distance, engaged distance, best stretch, a status timeline.

Pure: no openpilot imports. Constant memory: N_BUCKETS time buckets that merge pairwise (bucket
length doubles) as the drive grows. Engaged % is by distance.
Colors are comma connect's route timeline palette, except override: yellow instead of grey.
"""
from __future__ import annotations

N_BUCKETS = 160
BUCKET_S0 = 2.0              # first bucket length; doubles as the drive grows
MERGE_S = 3.0                # offroad shorter than this (onroad cycles) continues the same drive
MOVING_V = 0.15              # m/s: slower counts as stopped

STANDBY, MANUAL, ENGAGED, OVERRIDE, PROMPT, CRITICAL = range(6)
CODES = "smeopc"
COLORS = {                       # comma connect theme.js / colors.js
  ENGAGED: (0x17, 0x86, 0x45),   # engagedGreen
  MANUAL: (0x17, 0x58, 0x86),    # drivingBlue
  OVERRIDE: (0xe3, 0xd7, 0x56),  # yellow500 (connect uses engagedGrey)
  PROMPT: (0xda, 0x6f, 0x25),    # alertOrange, userPrompt
  CRITICAL: (0xc9, 0x22, 0x31),  # alertRed, critical
  STANDBY: (0x91, 0x9b, 0x95),   # engagedGrey: stopped, not engaged
}

# cereal enum names, so this module needs no cereal import
_OVERRIDE_STATES = ("preEnabled", "overriding")


def classify(enabled: bool, state: str, alert_status: str, gas_pressed: bool, v_ego: float) -> int:
  if alert_status == "critical":
    return CRITICAL
  if alert_status == "userPrompt":
    return PROMPT
  if enabled and (state in _OVERRIDE_STATES or gas_pressed):
    return OVERRIDE
  if enabled:
    return ENGAGED
  return STANDBY if v_ego < MOVING_V else MANUAL


class Timeline:
  def __init__(self, n: int = N_BUCKETS, bucket_s: float = BUCKET_S0) -> None:
    self.n = n
    self.bucket_s = bucket_s
    self.t = 0.0
    self.buckets = [[0.0] * 6 for _ in range(n)]

  def _compact(self) -> None:
    half = self.n // 2
    for i in range(half):
      a, b = self.buckets[2 * i], self.buckets[2 * i + 1]
      self.buckets[i] = [x + y for x, y in zip(a, b, strict=True)]
    for i in range(half, self.n):
      self.buckets[i] = [0.0] * 6
    self.bucket_s *= 2.0

  def add(self, status: int, dt: float) -> None:
    while dt > 0:
      idx = int(self.t // self.bucket_s)
      if idx >= self.n:
        self._compact()
        continue
      step = min(dt, (idx + 1) * self.bucket_s - self.t)
      step = max(step, 1e-9)
      self.buckets[idx][status] += step
      self.t += step
      dt -= step

  @staticmethod
  def dominant(b: list[float]) -> int:
    if b[CRITICAL] > 0:
      return CRITICAL
    if b[PROMPT] > 0:
      return PROMPT
    return max((STANDBY, MANUAL, ENGAGED, OVERRIDE), key=lambda s: (b[s], s))

  def codes(self) -> str:
    used = min(self.n, int(-(-self.t // self.bucket_s))) if self.t > 0 else 0
    return "".join(CODES[self.dominant(self.buckets[i])] for i in range(used))


class DriveRecorder:
  def __init__(self) -> None:
    self.active = False
    self._reset()

  def _reset(self) -> None:
    self.m = self.e = 0.0
    self.dur = 0.0
    self.cur_m = self.best_m = 0.0
    self.timeline = Timeline()
    self.drive_id = ""
    self.start_wall = 0.0
    self._t: float | None = None
    self._off_since: float | None = None
    self._off_wall = 0.0
    self.last_v = 0.0               # vEgo on the last onroad frame: a trip ends stopped
    self.shown = False              # its card was up

  def update(self, started: bool, now: float, wall: float, v_ego: float, enabled: bool,
             state: str = "", alert_status: str = "normal", gas_pressed: bool = False,
             drive_id: str = "") -> dict | None:
    """Feed one frame. Returns the finished drive once offroad has lasted MERGE_S; shorter gaps
    (an onroad cycle is ~1 s) continue the same drive."""
    if started:
      if not self.active:
        self._reset()
        self.active = True
        self.start_wall = wall
        self.drive_id = drive_id or f"t{int(wall)}"
      elif self._off_since is not None:
        self._off_since = None        # back within MERGE_S: same drive, the gap itself doesn't count
        self._t = now
      elif drive_id and self.drive_id.startswith("t"):
        self.drive_id = drive_id    # CurrentRoute shows up a moment after onroad
      dt = 0.0 if self._t is None else min(1.0, max(0.0, now - self._t))
      self._t = now
      self.last_v = v_ego
      d = v_ego * dt if v_ego > MOVING_V else 0.0
      self.m += d
      self.dur += dt
      if enabled:
        self.e += d
        self.cur_m += d
        self.best_m = max(self.best_m, self.cur_m)
      else:
        self.cur_m = 0.0
      if dt > 0:
        self.timeline.add(classify(enabled, state, alert_status, gas_pressed, v_ego), dt)
      return None
    if self.active:
      if self._off_since is None:
        self._off_since, self._off_wall = now, wall
      if now - self._off_since >= MERGE_S:
        self.active = False
        self._off_since = None
        return self.summary(self._off_wall)
    return None

  def summary(self, end_wall: float) -> dict:
    return {
      "id": self.drive_id, "start": self.start_wall, "end": end_wall, "dur": round(self.dur, 1),
      "m": round(self.m, 1), "e": round(self.e, 1), "best_m": round(self.best_m, 1),
      "tl": self.timeline.codes(), "shown": self.shown
    }
