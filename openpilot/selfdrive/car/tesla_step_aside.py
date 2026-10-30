"""Tesla step-aside: let Tesla's own Autosteer / FSD / Summon drive, untouched.

When Tesla's Self-Driving selection is Autosteer or FSD (anything but TACC),
or stock Autopilot / FSD / Autopark is active, openpilot goes passive: card
publishes CarParams with passive=True and safetyModel noOutput, so the panda
never closes the harness relay and Tesla's frames pass through unchanged. The
UI shows "Tesla FSD/Autopilot active" for ~5 s, then turns the display off
(touch wakes it). When Tesla is back on TACC and idle, openpilot comes back
through an onroad cycle (OnroadCycleRequested), with no reboot.

Why at startup, before CarParams: on route 3e2de7ed673817c2/0000000d the car
was driving itself on FSD from power-on. The panda stayed in ELM327 (relay
open) until card + selfdrived had started, ~9.8 s later. Then it switched to
tesla safety mode, which blocks AP's DAS_steeringControl (type 4 = FSD) and
puts openpilot's own frames on the car's bus. FSD stopped 2.4 s later. The
relay is open during fingerprinting, and the AP's frames (bus 2) are on CAN,
so card can see Tesla in charge before it ever asks for tesla safety mode.

Signals (all read from the AP side, bus 2, except DI_state, bus 0):
  active (verified on the route above):
    DAS_status.DAS_autopilotState in 3-6 (ACTIVE_*), 8 (ABORTING)
    DAS_steeringControl.DAS_steeringControlType == 4 (FSD)
    DI_state.DI_autoparkState in 2/3/4/5/7/9 (not verified on HW4: no Summon log)
  selected but idle (heuristic, from one FSD route vs. 31 TACC segments):
    DAS_control.DAS_accState == 13 (ACC_CANCEL_GENERIC_SILENT) for >= 1.5 s.
      FSD selected: 13 for the whole route, including parked after FSD stopped.
      TACC selected: 0 (ACC_CANCEL_GENERIC) idle, 4 (ACC_ON) cruising; 13 only
      in <= 0.41 s blips (the scroll-wheel cancel).
    DAS_status.DAS_autopilotState == 2 (AVAILABLE), held 2 s: seen with FSD
      selected while parked; never seen in 31 TACC segments (always 1).
  DAS_settings.DAS_autosteerEnabled is not used: it read 0 throughout FSD, and
  DAS_settings was byte-identical between the FSD and TACC routes.

Kept free of openpilot and opendbc imports at the top level so it unit-tests
without a build. Params keys are read tolerantly: a prebuilt params library
older than these keys falls back to the raw params file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

PARAM_ENABLED = "TeslaStepAside"       # Settings toggle, default on
PARAM_STEPPED = "TeslaSteppedAside"    # this onroad session is stepped aside

AP_STATE_AVAILABLE = 2
AP_ACTIVE_STATES = frozenset({3, 4, 5, 6, 8})   # ACTIVE_NOMINAL/RESTRICTED/NAV/FSD, ABORTING
STEER_TYPE_FSD = 4
AUTOPARK_ACTIVE_STATES = frozenset({2, 3, 4, 5, 7, 9})
ACC_STATE_CANCEL_SILENT = 13

SELECTED_SILENT_RUN_S = 1.5   # TACC scroll-wheel cancel blips are <= 0.41 s
AVAILABLE_HOLD_S = 2.0        # AVAILABLE flickers with UNAVAILABLE while parked
ENTER_DEBOUNCE_S = 0.2        # stock must own the car this long before a mid-run cycle
RETURN_CLEAR_S = 3.0          # stock idle and on TACC this long before coming back
MIN_STEPPED_S = 5.0           # never cycle back sooner than this after stepping aside
STARTUP_OBSERVE_S = 2.0       # card watches CAN this long before publishing CarParams
ALERT_S = 5.0                 # UI keeps the display on this long after stepping aside


@dataclass(frozen=True)
class StockSignals:
  ap_state: int = 0
  steer_type: int = 0
  autopark_state: int = 0
  acc_state: int = 0


def read_signals(can_parsers) -> StockSignals:
  """The stock signals from Tesla's CarInterface parsers (opendbc Bus keys
  'party' and 'ap_party'). Every message read here is one carstate reads, so
  the parsers already track them."""
  party = can_parsers["party"] if "party" in can_parsers else _by_value(can_parsers, "party")
  ap = can_parsers["ap_party"] if "ap_party" in can_parsers else _by_value(can_parsers, "ap_party")
  # comma's 3-bit DAS_steeringControlType (opendbc tesla.dbc); legacy 2-bit cars are not supported
  return StockSignals(
    ap_state=int(ap.vl["DAS_status"]["DAS_autopilotState"]),
    steer_type=int(ap.vl["DAS_steeringControl"]["DAS_steeringControlType"]),
    autopark_state=int(party.vl["DI_state"]["DI_autoparkState"]),
    acc_state=int(ap.vl["DAS_control"]["DAS_accState"]),
  )


def _by_value(can_parsers, name):
  for k, v in can_parsers.items():
    if getattr(k, "value", k) == name:
      return v
  raise KeyError(name)


class StockDetector:
  """Is Tesla's own driver assist active, or selected (Autosteer / FSD)?"""

  def __init__(self) -> None:
    self.silent_since: float | None = None
    self.available_t: float | None = None
    self.active = False
    self.selected = False

  def update(self, s: StockSignals, now: float) -> bool:
    self.active = (s.ap_state in AP_ACTIVE_STATES or s.steer_type == STEER_TYPE_FSD or
                   s.autopark_state in AUTOPARK_ACTIVE_STATES)

    if s.acc_state == ACC_STATE_CANCEL_SILENT:
      if self.silent_since is None:
        self.silent_since = now
    else:
      self.silent_since = None
    if s.ap_state == AP_STATE_AVAILABLE:
      self.available_t = now

    selected_silent = self.silent_since is not None and now - self.silent_since >= SELECTED_SILENT_RUN_S
    selected_available = self.available_t is not None and now - self.available_t <= AVAILABLE_HOLD_S
    self.selected = selected_silent or selected_available
    return self.owns

  @property
  def owns(self) -> bool:
    return self.active or self.selected


ENTER = "enter"
RETURN = "return"


class StepAsideController:
  """When to cycle onroad into or out of step-aside.

  Into it (not stepped aside yet): Tesla owns the car for ENTER_DEBOUNCE_S and
  openpilot is not engaged. With the relay closed, the panda already blocks
  stock steering, so the car is not moving under stock control.
  Out of it: Tesla has been neither active nor selected for RETURN_CLEAR_S,
  and the car is in Park or cruise is off; never within MIN_STEPPED_S.
  Each request is made once; the onroad cycle restarts card."""

  def __init__(self, stepped_aside: bool, start_t: float) -> None:
    self.stepped_aside = stepped_aside
    self.start_t = start_t
    self.owns_since: float | None = None
    self.clear_since: float | None = None
    self.requested: str | None = None

  def update(self, owns: bool, op_enabled: bool, park: bool, cruise_enabled: bool, now: float) -> str | None:
    if self.requested is not None:
      return None

    if owns:
      self.clear_since = None
      if self.owns_since is None:
        self.owns_since = now
    else:
      self.owns_since = None
      if self.clear_since is None:
        self.clear_since = now

    if self.stepped_aside:
      if (not owns and now - self.start_t >= MIN_STEPPED_S and now - self.clear_since >= RETURN_CLEAR_S and
          (park or not cruise_enabled)):
        self.requested = RETURN
    elif owns and not op_enabled and now - self.owns_since >= ENTER_DEBOUNCE_S:
      self.requested = ENTER
    return self.requested


# -- params, tolerant of a params library older than these keys --------------

def _raw_path(params, key: str) -> str:
  return os.path.join(params.get_param_path(), key)


def get_bool(params, key: str, default: bool) -> bool:
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
  return get_bool(params, PARAM_ENABLED, True)


def stepped_aside(params) -> bool:
  return get_bool(params, PARAM_STEPPED, False)


def is_park(gear) -> bool:
  # capnp CarState reads the enum by name; opendbc's GearShifter.park is 1
  return str(gear) == "park" or (isinstance(gear, int) and gear == 1)


class TeslaStepAside:
  """card's handle: startup detection, then the onroad-cycle requests."""

  def __init__(self, CI, params, now: float) -> None:
    self.CI = CI
    self.params = params
    self.detector = StockDetector()
    self.stepped_aside = stepped_aside(params)   # sticky across an onroad cycle we asked for
    self.startup_owned = False
    self.controller: StepAsideController | None = None

  def observe(self, now: float) -> bool:
    return self.detector.update(read_signals(self.CI.can_parsers), now)

  def observe_startup(self, recv, clock, duration: float = STARTUP_OBSERVE_S) -> bool:
    """Feed CAN through CI.update for `duration` s before CarParams goes out.
    recv() returns can_capnp_to_list-style packets; clock() is monotonic s."""
    t0 = clock()
    while True:
      now = clock()
      packets = recv()
      if packets:
        self.CI.update(packets)
        if self.observe(now):
          self.startup_owned = True
          if self.detector.active:
            break   # active is unambiguous; no need to wait out the window
      if now - t0 >= duration:
        break
    if self.startup_owned:
      self.stepped_aside = True
    return self.stepped_aside

  def start(self, now: float) -> None:
    """Call once CarParams is decided; arms the onroad-cycle controller."""
    put_bool(self.params, PARAM_STEPPED, self.stepped_aside, block=True)
    self.controller = StepAsideController(self.stepped_aside, now)

  def update(self, CS, op_enabled: bool, now: float) -> str | None:
    owns = self.observe(now)
    park = is_park(CS.gearShifter)
    action = self.controller.update(owns, op_enabled, park, CS.cruiseState.enabled, now)
    if action == ENTER:
      put_bool(self.params, PARAM_STEPPED, True, block=True)
      put_bool(self.params, "OnroadCycleRequested", True, block=True)
    elif action == RETURN:
      put_bool(self.params, PARAM_STEPPED, False, block=True)
      put_bool(self.params, "OnroadCycleRequested", True, block=True)
    return action
