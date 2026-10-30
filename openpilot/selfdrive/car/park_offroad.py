"""Tesla park-offroad (ParkOffroad toggle, default off): offroad in Park, back onroad on R/D.

  * One output, ParkOffroadState: NONE, PARKING (in Park, armed, not engaged: offroad in
    PARK_HOLD_S unless it leaves Park) or PARKED. hardwared's "not_parked" condition takes the device
    offroad the normal way on PARKED (NO_OUTPUT, relay open); the UI reads the same param.
    It can only make the device offroad, never onroad, and sends nothing.
  * Arms once this ignition cycle has seen R or D.
  * Latched, only R or D returns onroad (a new route); N stays offroad. Tesla keeps ignitionCan on
    in Park, so ignition staying on or blipping never restarts onroad. Only ignition off for
    IGN_OFF_CLEAR_S clears the latch.
  * Summon/Autopark (DI_autoparkState active) never returns onroad.
  * No gear frames for CAN_TIMEOUT_S while latched: clear and stay disarmed until the next
    ignition cycle, so it's never stuck offroad.

Bus 0, checksum = sum of address bytes + data[1:]:
  0x118 DI_systemStatus 100 Hz: DI_gear = (dat[2] >> 5) & 7  (1 P, 2 R, 3 N, 4 D, 0 invalid, 7 SNA)
  0x286 DI_state 10 Hz: DI_autoparkState = (dat[3] >> 1) & 0xF
The panda forwards bus 0 in every safety mode, including NO_OUTPUT.

No openpilot imports at the top level, so it unit-tests without a build.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from openpilot.common.params_compat import get, get_bool, put, put_bool as put_bool

PARAM_ENABLED = "ParkOffroad"           # Settings toggle (PERSISTENT, default 0)
PARAM_STATE = "ParkOffroadState"        # parkd's output (CLEAR_ON_MANAGER_START only: manager's
                                        # ignition-on clear would drop the latch on an ignitionCan blip)
NONE, PARKING, PARKED = 0, 1, 2

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
    gear = decode_gear(addr, bus, dat) if gear is None else gear
    autopark = decode_autopark(addr, bus, dat) if autopark is None else autopark
  return gear, autopark


class ParkSource(NamedTuple):
  addrs: frozenset
  sample: Callable    # (frames) -> (gear, autopark)


# another brand only needs its own decoder here; the rest is brand-free
PARK_SOURCES: dict[str, ParkSource] = {
  "tesla": ParkSource(frozenset({ADDR_DI_SYSTEM_STATUS, ADDR_DI_STATE}), sample),
}


class ParkOffroad:
  """Pure state machine. update() returns True while the device should be offroad for Park."""

  def __init__(self) -> None:
    self._reset()
    self._ignition_prev = False
    self._ign_off_t: float | None = None

  def _reset(self) -> None:
    self.parked = False
    self.armed = False
    self.unavailable = False
    self._parking = False
    self._p_since: float | None = None
    self._return_n = 0
    self._last_gear_t: float | None = None
    self._autopark_t: float | None = None

  @property
  def state(self) -> int:
    if self.parked:
      return PARKED
    return PARKING if self._parking else NONE

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
    elif gear == GEAR_N:
      self._return_n = 0
      self._p_since = None

    fresh = self._last_gear_t is not None and now - self._last_gear_t <= CAN_TIMEOUT_S
    self._parking = fresh and self._p_since is not None and self.armed and not self.parked and not self.unavailable and not engaged
    if self._parking and now - self._p_since >= PARK_HOLD_S:
      self.parked, self._parking = True, False

    if self.parked and (self._last_gear_t is None or now - self._last_gear_t > CAN_TIMEOUT_S):
      # no gear frames offroad: never strand the device offroad with ignition on
      self.parked = False
      self.armed = False
      self.unavailable = True

    return self.parked


def get_state(params) -> int:
  try:
    return int(get(params, PARAM_STATE) or NONE)
  except (TypeError, ValueError):
    return NONE


def put_state(params, state: int, block: bool = False) -> None:
  put(params, PARAM_STATE, int(state), b"%d" % state, block)


def enabled(params) -> bool:
  return get_bool(params, PARAM_ENABLED, False)


# -- hooks ---------------------------------------------------------------------

def not_parked(params) -> bool:
  """hardwared onroad condition. True (no effect) unless the toggle is on and parkd says parked."""
  return not (enabled(params) and get_state(params) == PARKED)


class OffroadTimer:
  """hardwared: after a park-offroad, restart off_ts at ignition off, so time sat in Park
  doesn't count toward the shutdown delays."""

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
  return enabled(params)


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
  put_state(params, NONE, block=True)    # valid from the first loop, whatever a previous run left
  # gear frames mean something else on other brands: idle unless the last car has a park source
  source = PARK_SOURCES.get(_brand(params))
  while source is None:
    time.sleep(5.0)
    source = PARK_SOURCES.get(_brand(params))

  can_sock = messaging.sub_sock("can", conflate=True, timeout=0)
  sm = messaging.SubMaster(["pandaStates", "selfdriveState"])
  ctrl = ParkOffroad()
  published = NONE
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
      ctrl.update(now, gear, ignition, engaged, autopark, on)
      state = ctrl.state
      if state != published:
        put_state(params, state, block=True)
        cloudlog.event("park_offroad", state=state, unavailable=ctrl.unavailable, gear=gear)
        published, sync_t = state, now
      elif now - sync_t > 1.0:
        sync_t = now
        if get_state(params) != state:   # someone else wrote it: re-assert
          put_state(params, state, block=True)
      rk.keep_time()
  finally:
    put_state(params, NONE)


if __name__ == "__main__":
  main()
