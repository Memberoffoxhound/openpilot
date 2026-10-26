"""Drive summary: per-drive stats and an engagement timeline, for any car.

tick(ui_state) once per UI frame records while onroad and saves DriveSummaryLast when offroad
lasts MERGE_S, whatever the cause. Constant memory: N_BUCKETS time buckets that merge pairwise
(bucket length doubles) as the drive grows. Engaged % is by distance.

Colors are comma connect's route timeline palette, except override: yellow instead of grey.
Params are read tolerantly: a params library without these keys just loses the feature.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta

PARAM_ENABLED = "DriveSummary"
PARAM_LAST = "DriveSummaryLast"

N_BUCKETS = 160
BUCKET_S0 = 2.0              # first bucket length; doubles as the drive grows
MIN_SHOW_M = 160.9           # 0.1 mi: shorter drives never show the card
MIN_SHOW_S = 30.0
SHOW_S = 10.0                # seconds the card holds the onroad page before the scroll to home
MERGE_S = 3.0                # offroad shorter than this (onroad cycles) continues the same drive
DAYS_KEEP = 14
MOVING_V = 0.15              # m/s, same cutoff as the home trip meter

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
      "tl": self.timeline.codes()
    }


# -- stored data: last drive + DAYS_KEEP days of totals (fallback for Today/Week) --

def wall_now() -> float:
  return datetime.now().timestamp()


def day_key(wall: float) -> str:
  return datetime.fromtimestamp(wall).date().isoformat()


def add_drive(data: dict | None, drive: dict) -> dict:
  data = dict(data or {})
  days = dict(data.get("days") or {})
  k = day_key(drive.get("end") or wall_now())
  m0, e0 = (days.get(k) or [0.0, 0.0])[:2]
  days[k] = [round(m0 + float(drive.get("m") or 0), 1), round(e0 + float(drive.get("e") or 0), 1)]
  for old in sorted(days)[:-DAYS_KEEP]:
    days.pop(old, None)
  data["days"] = days
  data["record_m"] = round(max(own_record_m(data), float(drive.get("best_m") or 0)), 1)
  data["last"] = drive
  return data


def engaged_pct(eng: float, meters: float) -> int:
  return int(round(100.0 * eng / meters)) if meters > 1 else 0


def today_week(data: dict | None, today: date | None = None) -> dict:
  """Today/Week totals from the stored days (weeks start Sunday, like the home row)."""
  today = today or date.today()
  days = (data or {}).get("days") or {}
  sunday = today - timedelta(days=(today.weekday() + 1) % 7)
  out = {"today_m": 0.0, "today_e": 0.0, "week_m": 0.0, "week_e": 0.0}
  for k, v in days.items():
    try:
      d = date.fromisoformat(k)
      m, e = float(v[0]), float(v[1])
    except (ValueError, TypeError, IndexError):
      continue
    if d == today:
      out["today_m"] += m
      out["today_e"] += e
    if sunday <= d <= today:
      out["week_m"] += m
      out["week_e"] += e
  return out


def day_streak(data: dict | None, today: date | None = None) -> int:
  """Consecutive days (ending today, or yesterday if nothing yet today) with > 1 m engaged."""
  today = today or date.today()
  days = (data or {}).get("days") or {}

  def engaged(d: date) -> bool:
    try:
      return float((days.get(d.isoformat()) or [0, 0])[1]) > 1
    except (TypeError, ValueError, IndexError):
      return False

  cur = today if engaged(today) else today - timedelta(days=1)
  n = 0
  while engaged(cur) and n < 4000:
    n += 1
    cur -= timedelta(days=1)
  return n


def eligible(drive: dict | None) -> bool:
  """Long enough for a card: >= 0.1 mi and >= 30 s."""
  return bool(drive) and float(drive.get("m") or 0) >= MIN_SHOW_M and float(drive.get("dur") or 0) >= MIN_SHOW_S


def due_summary(params, rec: DriveRecorder | None = None) -> dict | None:
  """The trip that just ended, if the card is due (toggle on, recorded, stopped, long enough)."""
  rec = recorder if rec is None else rec
  if not enabled(params) or not rec.active or rec.last_v > MOVING_V:
    return None
  drive = rec.summary(wall_now())
  return drive if eligible(drive) else None


# -- card formatting (pure, shared with the widgets) ---------

def fmt_dist(meters: float, metric: bool) -> tuple[str, str]:
  d = meters / 1000.0 if metric else meters / 1609.344
  return (f"{d:.1f}" if d < 9.95 else f"{int(round(d))}"), ("km" if metric else "mi")


def card_columns(drive: dict, streak_days: int, metric: bool) -> list[tuple[str, str, str]]:
  """(value, unit, label) columns; the last (best stretch) is dropped by the card if it doesn't fit."""
  m, e, best = float(drive.get("m") or 0), float(drive.get("e") or 0), float(drive.get("best_m") or 0)
  dv, du = fmt_dist(m, metric)
  bv, bu = fmt_dist(best, metric)
  return [(dv, du, "driven"), (str(engaged_pct(e, m)), "%", "engaged"),
          (str(int(streak_days)), "", "day streak"), (bv, bu, "best stretch")]


COL_GAP = 10                 # card: minimum space between neighboring stat columns


def column_slots(cols, avail: float, value_w, label_w, gap: float = COL_GAP) -> list[tuple[float, float, float]]:
  """[(center x, value width, label width)] in equal slots of avail / n. Trailing columns drop
  (never below 3) while neighbors would come closer than gap or an edge column would overflow."""
  widths = [(value_w(v, u), label_w(lbl)) for v, u, lbl in cols]

  def fits(n: int) -> bool:
    slot = avail / n
    ws = [max(vw, lw) for vw, lw in widths[:n]]
    return (all((a + b) / 2 + gap <= slot for a, b in zip(ws, ws[1:], strict=False)) and
            ws[0] <= slot and ws[-1] <= slot)

  n = len(cols)
  while n > 3 and not fits(n):
    n -= 1
  slot = avail / max(1, n)
  return [(slot * (i + 0.5), vw, lw) for i, (vw, lw) in enumerate(widths[:n])]


def timeline_runs(codes: str) -> list[tuple[int, int, int]]:
  """Run-length (status, start, length) over the bucket codes."""
  runs: list[tuple[int, int, int]] = []
  for i, ch in enumerate(codes):
    st = CODES.find(ch)
    st = MANUAL if st < 0 else st
    if runs and runs[-1][0] == st:
      runs[-1] = (st, runs[-1][1], runs[-1][2] + 1)
    else:
      runs.append((st, i, 1))
  return runs


def own_record_m(data: dict | None) -> float:
  """Longest best stretch of all saved drives."""
  try:
    return float((data or {}).get("record_m") or 0.0)
  except (TypeError, ValueError):
    return 0.0


COMMA_GREEN = (0x17, 0x86, 0x45)   # comma connect's engagedGreen, same as the timeline's engaged color


def accent_rgb() -> tuple[int, int, int]:
  """Swap-in: the fork's theme color, else comma green."""
  try:
    from openpilot.selfdrive.ui.layouts.settings.common import theme_rgb
    r, g, b = theme_rgb()
    return int(r), int(g), int(b)
  except Exception:
    return COMMA_GREEN


# -- params, tolerant of a params library older than these keys --------------

def _raw_path(params, key: str) -> str:
  return os.path.join(params.get_param_path(), key)


def _known(params, key: str) -> bool:
  try:
    params.check_key(key)
    return True
  except Exception:
    return False


def get_bool(params, key: str, default: bool = False) -> bool:
  try:
    if _known(params, key):
      raw = params.get(key, return_default=True)
      return default if raw is None else bool(raw)
    with open(_raw_path(params, key), "rb") as f:
      return f.read().strip() in (b"1", b"true", b"True")
  except Exception:
    return default


def put_bool(params, key: str, value: bool) -> None:
  if _known(params, key):
    params.put_bool(key, value)
    return
  _raw_write(params, key, b"1" if value else b"0")


def get_json(params, key: str) -> dict | None:
  try:
    if _known(params, key):
      raw = params.get(key)
    else:
      with open(_raw_path(params, key), "rb") as f:
        raw = f.read()
    if isinstance(raw, (bytes, str)):
      raw = json.loads(raw)
    return raw if isinstance(raw, dict) else None
  except Exception:
    return None


def put_json(params, key: str, value: dict) -> None:
  if _known(params, key):
    params.put(key, value)
    return
  _raw_write(params, key, json.dumps(value).encode())


def _raw_write(params, key: str, data: bytes) -> None:
  path = _raw_path(params, key)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  tmp = f"{path}.tmp{os.getpid()}"
  with open(tmp, "wb") as f:
    f.write(data)
  os.replace(tmp, path)


# -- UI hook ---------------------------------------------------------------------

recorder = DriveRecorder()
_enabled_cache = (0.0, False)
_route_t = 0.0
_logged = False


def enabled(params) -> bool:
  global _enabled_cache
  now = time.monotonic()
  if now - _enabled_cache[0] > 2.0:
    _enabled_cache = (now, get_bool(params, PARAM_ENABLED, False))
  return _enabled_cache[1]


def tick(ui_state) -> None:
  global _route_t, _logged
  params = ui_state.params
  try:
    if not enabled(params) and not recorder.active:
      return
    sm = ui_state.sm
    started = bool(ui_state.started)
    v = enabled_ = gas = False
    state, alert = "", "normal"
    if started:
      cs = sm["carState"]
      v = max(0.0, float(cs.vEgo))
      gas = bool(cs.gasPressed)
      if sm.recv_frame["selfdriveState"] >= ui_state.started_frame:
        ss = sm["selfdriveState"]
        enabled_ = bool(ss.enabled)
        state, alert = str(ss.state), str(ss.alertStatus)
    route = ""
    now = time.monotonic()
    if started and (not recorder.active or recorder.drive_id.startswith("t")) and now - _route_t > 1.0:
      _route_t = now
      route = params.get("CurrentRoute") or ""
      if isinstance(route, bytes):
        route = route.decode(errors="replace")
    done = recorder.update(started, now, wall_now(), float(v), enabled_, state, alert, gas, str(route))
    if done is not None:
      put_json(params, PARAM_LAST, add_drive(get_json(params, PARAM_LAST), done))
  except Exception:
    if not _logged:
      _logged = True
      from openpilot.common.swaglog import cloudlog
      cloudlog.exception("drive_summary tick")
