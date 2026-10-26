"""Tesla park-offroad: go offroad when the car sits in Park, back onroad on D/R.

Behind the ParkOffroad toggle (default off). With it on:
  * after this ignition cycle has seen R or D, Park held PARK_HOLD_S with
    openpilot not engaged sets ParkOffroadActive, and hardwared adds a
    "not_parked" onroad condition. The device goes offroad, so pandad puts the
    panda in NO_OUTPUT (relay open, nothing sent) exactly as with ignition off.
  * Once latched, only R or D brings the device back onroad, through a
    normal offroad -> onroad transition (a new route). N keeps it offroad (car
    wash). Tesla keeps power state DRIVE in Park, so ignitionCan staying on, or
    dropping out and returning, never restarts onroad while latched.
  * ignition (Tesla's ignitionCan, 0x221 DRIVE) otherwise starts and stops
    onroad exactly as before: ignition on in Park goes onroad as today
    (park-offroad only arms after the first R/D), ignition off while driving
    is stock, and a real ignition cycle (off >= IGN_OFF_CLEAR_S) clears the
    latch. With the toggle off, nothing changes.
  * Summon / Autopark (DI_state.DI_autoparkState active) never brings the
    device back onroad: the car moves itself between R and D with the relay
    open, and Tesla keeps it that way.
  * if gear frames stop arriving while parked offroad with ignition on
    (CAN_TIMEOUT_S), the latch clears and park-offroad stays disarmed until the
    next ignition cycle: stock ignition behavior, never stuck offroad.

It only ever removes an onroad condition: it can make the device offroad
(relay open), never onroad, and it sends nothing on CAN. Panda safety is
untouched.

Signals, bus 0 (party), both checksummed (sum of address bytes + data[1:]):
  0x118 DI_systemStatus, 100 Hz: DI_gear bits 21..23 = (dat[2] >> 5) & 7,
        1 P, 2 R, 3 N, 4 D, 0 invalid, 7 SNA
  0x286 DI_state, 10 Hz: DI_autoparkState bits 25..28 = (dat[3] >> 1) & 0xF
The panda forwards bus 0 to the host in every safety mode (the fixtures here
were logged in ELM327 with the relay open). Offroad it is NO_OUTPUT with the
relay open; see PORTING.md for the device check.

Kept free of openpilot imports at the top level so it unit-tests without a
build. Params are read tolerantly (raw file fallback for a stale library).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import NamedTuple

PARAM_ENABLED = "ParkOffroad"           # Settings toggle (PERSISTENT, default 0)
PARAM_ACTIVE = "ParkOffroadActive"      # parked offroad right now (CLEAR_ON_MANAGER_START only: manager's
                                        # ignition-on clear would drop the latch on an ignitionCan blip)

PARK_HOLD_S = 3.0        # Park held this long, not engaged, before going offroad
RETURN_SAMPLES = 2       # consecutive R/D samples before coming back onroad (~0.1 s at 20 Hz)
CAN_TIMEOUT_S = 2.0      # parked offroad with no valid gear frame this long: give up until ignition cycles
AUTOPARK_HOLD_S = 1.5    # DI_state is 10 Hz; an active reading counts this long
PANDA_TIMEOUT_S = 2.0    # parkd: pandaStates older than this reads as ignition off
IGN_OFF_CLEAR_S = 5.0    # latched: ignition must stay off this long to count as a real ignition cycle

ADDR_DI_SYSTEM_STATUS = 0x118
ADDR_DI_STATE = 0x286
PARTY_BUS = 0

GEAR_P, GEAR_R, GEAR_N, GEAR_D = 1, 2, 3, 4
VALID_GEARS = frozenset({GEAR_P, GEAR_R, GEAR_N, GEAR_D})
RETURN_GEARS = frozenset({GEAR_R, GEAR_D})
AUTOPARK_ACTIVE_STATES = frozenset({2, 3, 4, 5, 7, 9})   # same set as tesla_step_aside


def _checksum_ok(addr: int, dat: bytes) -> bool:
  return len(dat) == 8 and ((addr & 0xFF) + ((addr >> 8) & 0xFF) + sum(dat[1:])) & 0xFF == dat[0]


def decode_gear(addr: int, bus: int, dat: bytes) -> int | None:
  """DI_gear from a bus-0 0x118 frame; None for other frames, bad checksums, invalid/SNA."""
  if addr != ADDR_DI_SYSTEM_STATUS or bus != PARTY_BUS or not _checksum_ok(addr, dat):
    return None
  gear = (dat[2] >> 5) & 0x7
  return gear if gear in VALID_GEARS else None


def decode_autopark(addr: int, bus: int, dat: bytes) -> int | None:
  if addr != ADDR_DI_STATE or bus != PARTY_BUS or not _checksum_ok(addr, dat):
    return None
  return (dat[3] >> 1) & 0xF


def sample(frames) -> tuple[int | None, int | None]:
  """(gear, autopark) from one can packet's (address, bus, data) frames; first valid of each."""
  gear = autopark = None
  for addr, bus, dat in frames:
    if bus != PARTY_BUS:
      continue
    if gear is None and addr == ADDR_DI_SYSTEM_STATUS:
      gear = decode_gear(addr, bus, dat)
    elif autopark is None and addr == ADDR_DI_STATE:
      autopark = decode_autopark(addr, bus, dat)
  return gear, autopark


class ParkSource(NamedTuple):
  """Swap-in park detection: which CAN addresses to read, and (frames) -> (gear, autopark)."""
  addrs: frozenset
  sample: Callable


# brand -> source. Another brand only needs its own decoder here; the state machine,
# hardwared hook and UI are brand-free.
PARK_SOURCES: dict[str, ParkSource] = {
  "tesla": ParkSource(frozenset({ADDR_DI_SYSTEM_STATUS, ADDR_DI_STATE}), sample),
}


class ParkOffroad:
  """Pure state machine. update() returns True while the device should be offroad for Park."""

  def __init__(self, parked: bool = False) -> None:
    # a restart while parked keeps the device offroad until R/D (or ignition off)
    self.parked = parked
    self.armed = parked
    self.unavailable = False
    self._p_since: float | None = None
    self._return_n = 0
    self._last_gear_t: float | None = None
    self._autopark_t: float | None = None
    # a latch restored after a parkd restart was taken with ignition on
    self._ignition_prev = parked
    self._ign_off_t: float | None = None

  def _reset(self) -> None:
    self.parked = False
    self.armed = False
    self.unavailable = False
    self._p_since = None
    self._return_n = 0
    self._last_gear_t = None
    self._autopark_t = None

  def autopark_active(self, now: float) -> bool:
    return self._autopark_t is not None and now - self._autopark_t <= AUTOPARK_HOLD_S

  def update(self, now: float, gear: int | None, ignition: bool, engaged: bool,
             autopark: int | None = None, enabled: bool = True) -> bool:
    if not enabled:
      self._reset()
      self._ign_off_t = None
      self._ignition_prev = False
      return False
    if not ignition:
      if self.parked:
        # Latched: only a real ignition cycle clears it. Tesla keeps power state DRIVE in Park, so a
        # short ignitionCan dropout (panda's 2 s 0x221 timeout, a bus hiccup) must not end the latch and
        # let the returning ignition start onroad. Offroad either way while ignition is off.
        if self._ign_off_t is None:
          self._ign_off_t = now
        if now - self._ign_off_t >= IGN_OFF_CLEAR_S:
          self._reset()
          self._ign_off_t = None
      else:
        self._reset()
      self._ignition_prev = False
      return self.parked
    if self._ign_off_t is not None:
      # ignition back within IGN_OFF_CLEAR_S: still latched; give the gear frames a fresh timeout
      self._ign_off_t = None
      self._last_gear_t = now
      self._ignition_prev = True
    elif not self._ignition_prev:
      # ignition on (or toggle on): plain ignition behavior until the car leaves Park
      self._reset()
      self._ignition_prev = True
    if self.parked and self._last_gear_t is None:
      self._last_gear_t = now          # latch restored after a restart

    if autopark is not None and autopark in AUTOPARK_ACTIVE_STATES:
      self._autopark_t = now

    if gear is not None:
      self._last_gear_t = now

    if gear in RETURN_GEARS:
      self._p_since = None
      if self.parked:
        if self.autopark_active(now):
          self._return_n = 0          # Summon moving the car: stay offroad, relay open
        else:
          self._return_n += 1
          if self._return_n >= RETURN_SAMPLES:
            self.parked = False
            self._return_n = 0
      self.armed = True
    elif gear == GEAR_P:
      self._return_n = 0
      if self._p_since is None:
        self._p_since = now
      if (self.armed and not self.parked and not self.unavailable and not engaged
          and now - self._p_since >= PARK_HOLD_S):
        self.parked = True
    elif gear == GEAR_N:
      self._return_n = 0
      self._p_since = None

    if self.parked and (self._last_gear_t is None or now - self._last_gear_t > CAN_TIMEOUT_S):
      # no gear frames offroad: never strand the device offroad with ignition on
      self.parked = False
      self.armed = False
      self.unavailable = True

    return self.parked


# -- params, tolerant of a params library older than these keys --------------

def _raw_path(params, key: str) -> str:
  return os.path.join(params.get_param_path(), key)


def get_bool(params, key: str, default: bool = False) -> bool:
  try:
    params.check_key(key)
  except Exception:
    try:
      with open(_raw_path(params, key), "rb") as f:
        return f.read().strip() in (b"1", b"true", b"True")
    except OSError:
      return default
  try:
    raw = params.get(key, return_default=True)
  except Exception:
    return default
  return default if raw is None else bool(raw)


def put_bool(params, key: str, value: bool, block: bool = False) -> None:
  try:
    params.put_bool(key, value, block=block)
  except Exception:
    path = _raw_path(params, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as f:
      f.write(b"1" if value else b"0")
    os.replace(tmp, path)


def enabled(params) -> bool:
  return get_bool(params, PARAM_ENABLED, False)


# -- hooks ---------------------------------------------------------------------

def not_parked(params) -> bool:
  """hardwared onroad condition. True (no effect) unless the toggle is on and parkd says parked."""
  try:
    return not (enabled(params) and get_bool(params, PARAM_ACTIVE, False))
  except Exception:
    return True


class OffroadTimer:
  """hardwared: restart the offroad (shutdown) timer at ignition off after a park-offroad.

  Parked offroad, hardwared's off_ts starts when the car is put in Park with
  ignition still on. Without this, a long sit in the car would count toward
  the shutdown delays once ignition goes off. With it, shutdown timing after
  ignition off is the same as without park-offroad.
  """

  def __init__(self) -> None:
    self._parked_off = False
    self._ignition_prev = False

  def update(self, not_parked_ok: bool, started: bool, ignition: bool, off_ts: float | None, now: float) -> float | None:
    self._parked_off = (self._parked_off or not not_parked_ok) and not started
    if self._parked_off and self._ignition_prev and not ignition and off_ts is not None:
      off_ts = now
      self._parked_off = False
    self._ignition_prev = ignition
    return off_ts


def should_run(started: bool, params, CP) -> bool:
  """process_config: parkd runs onroad and offroad while the toggle is on."""
  try:
    return enabled(params)
  except Exception:
    return False


def _brand(params) -> str:
  try:
    from opendbc.car.structs import car
    raw = params.get("CarParamsPersistent")
    if not raw:
      return ""
    with car.CarParams.from_bytes(raw) as cp:
      return str(cp.brand)
  except Exception:
    return ""


def main() -> None:
  import time
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params
  from openpilot.common.realtime import Ratekeeper
  from openpilot.common.swaglog import cloudlog

  params = Params()
  # gear frames mean something else on other brands: idle unless the last car has a park source
  source = PARK_SOURCES.get(_brand(params))
  if source is None:
    put_bool(params, PARAM_ACTIVE, False)
    while source is None:
      time.sleep(5.0)
      source = PARK_SOURCES.get(_brand(params))

  can_sock = messaging.sub_sock("can", conflate=True, timeout=0)
  sm = messaging.SubMaster(["pandaStates", "selfdriveState"])
  ctrl = ParkOffroad(parked=get_bool(params, PARAM_ACTIVE, False))
  published = ctrl.parked
  rk = Ratekeeper(20, print_delay_threshold=None)
  on, on_t, sync_t = True, 0.0, 0.0
  try:
    while True:
      sm.update(0)
      gear = autopark = None
      msg = messaging.recv_one_or_none(can_sock)
      if msg is not None:
        gear, autopark = source.sample((f.address, f.src, bytes(f.dat)) for f in msg.can if f.address in source.addrs)
      now = time.monotonic()
      # last pandaStates within PANDA_TIMEOUT_S (hardwared's own ignition source), not sm.alive:
      # a scheduling hiccup must not read as ignition off
      ignition = (sm.recv_frame["pandaStates"] > 0 and now - sm.recv_time["pandaStates"] < PANDA_TIMEOUT_S and
                  any(ps.ignitionLine or ps.ignitionCan for ps in sm["pandaStates"]))
      engaged = (sm.recv_frame["selfdriveState"] > 0 and now - sm.recv_time["selfdriveState"] < 1.0 and
                 sm["selfdriveState"].enabled)
      if now - on_t > 1.0:
        on, on_t = enabled(params), now
      parked = ctrl.update(now, gear, ignition, engaged, autopark, on)
      if parked != published:
        put_bool(params, PARAM_ACTIVE, parked, block=True)
        cloudlog.event("park_offroad", parked=parked, unavailable=ctrl.unavailable, gear=gear)
        published = parked
        sync_t = now
      elif now - sync_t > 1.0:
        # re-assert the latch if anything else cleared the param; reads only, writes on mismatch
        sync_t = now
        if get_bool(params, PARAM_ACTIVE, False) != parked:
          put_bool(params, PARAM_ACTIVE, parked, block=True)
      rk.keep_time()
  finally:
    put_bool(params, PARAM_ACTIVE, False)


if __name__ == "__main__":
  main()
