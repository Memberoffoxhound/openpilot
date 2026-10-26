"""Park-offroad (park_offroad.py): DI_gear decoding on real CAN fixtures, the
Park hold / D-R return state machine, ignition, Summon, CAN loss, and the
hardwared / manager / params hooks."""
import gzip
import re
from pathlib import Path

import pytest

from openpilot.selfdrive.car import park_offroad as po
from openpilot.selfdrive.car import tesla_step_aside as tsa

FIXTURES = Path(__file__).parent / "fixtures"
OP = Path(__file__).resolve().parents[3]


def load(name):
  with gzip.open(FIXTURES / name, "rt") as f:
    return [(int(t), int(a), int(b), bytes.fromhex(d)) for t, a, b, d in (ln.strip().split(",") for ln in f)]


def packets(frames, every=5):
  """10 ms can packets, keeping one in `every` (parkd reads a conflated socket at 20 Hz)."""
  out, cur, cur_t = [], [], None
  for t, a, b, d in frames:
    if cur_t is None:
      cur_t = t
    if t - cur_t >= 10_000_000:
      out.append((cur_t / 1e9, cur))
      cur, cur_t = [], t
    cur.append((a, b, d))
  if cur:
    out.append((cur_t / 1e9, cur))
  return out[::every]


def frame_118(gear, counter=0):
  dat = bytearray(8)
  dat[1] = counter & 0xF
  dat[2] = (gear & 7) << 5
  dat[0] = (0x18 + 0x01 + sum(dat[1:])) & 0xFF
  return (0x118, 0, bytes(dat))


def frame_286(autopark):
  dat = bytearray(8)
  dat[3] = (autopark & 0xF) << 1
  dat[0] = (0x86 + 0x02 + sum(dat[1:])) & 0xFF
  return (0x286, 0, bytes(dat))


def run(ctrl, t0, seconds, gear, ignition=True, engaged=False, autopark=None, dt=0.05):
  """Feed synthetic 20 Hz samples; returns (end time, parked at end, first time parked flipped)."""
  t, flip, start = t0, None, ctrl.parked
  while t < t0 + seconds - 1e-9:
    frames = [frame_118(gear)] if gear is not None else []
    if autopark is not None:
      frames.append(frame_286(autopark))
    g, ap = po.sample(frames)
    parked = ctrl.update(t, g, ignition, engaged, ap)
    if flip is None and parked != start:
      flip = t - t0
    t += dt
  return t, ctrl.parked, flip


def drive_then_park(ctrl, t=0.0):
  t, _, _ = run(ctrl, t, 1.0, po.GEAR_P)      # ignition on in P: today's onroad
  t, _, _ = run(ctrl, t, 5.0, po.GEAR_D)      # drive
  return t


# -- decoding ------------------------------------------------------------------

@pytest.mark.parametrize("name,expect", [
  ("tesla_tacc_route02_start.csv.gz", [po.GEAR_P, po.GEAR_R]),      # garage: P, then reversing out
  ("tesla_fsd_route0d_start.csv.gz", [po.GEAR_P, po.GEAR_R]),
  ("tesla_tacc_route02_cancel_blip.csv.gz", [po.GEAR_D]),
])
def test_decode_gear_on_fixtures(name, expect):
  gears = [g for _, a, b, d in load(name) if (g := po.decode_gear(a, b, d)) is not None]
  runs = [g for i, g in enumerate(gears) if i == 0 or gears[i - 1] != g]
  assert runs == expect
  # bus 2 (AP side) carries 0x118 too; only bus 0 counts
  assert all(po.decode_gear(a, 2, d) is None for _, a, b, d in load(name) if a == 0x118)


def test_decode_matches_dbc_and_step_aside():
  assert po.decode_gear(*frame_118(po.GEAR_P)) == 1 and tsa.is_park(1)
  assert po.decode_gear(*frame_118(0)) is None and po.decode_gear(*frame_118(7)) is None   # invalid / SNA
  a, b, d = frame_118(po.GEAR_D)
  assert po.decode_gear(a, b, bytes([d[0] ^ 1]) + d[1:]) is None                           # bad checksum
  assert po.decode_autopark(*frame_286(3)) == 3
  assert po.AUTOPARK_ACTIVE_STATES == tsa.AUTOPARK_ACTIVE_STATES


def test_fixture_autopark_idle():
  aps = {po.decode_autopark(a, b, d) for _, a, b, d in load("tesla_tacc_route02_start.csv.gz") if a == 0x286 and b == 0}
  assert aps <= {0, 1}   # UNAVAILABLE / STANDBY: no Summon in the logs


# -- Park hold / return ----------------------------------------------------------

def test_ignition_on_in_park_stays_onroad_until_the_car_leaves_park():
  ctrl = po.ParkOffroad()
  _, parked, _ = run(ctrl, 0.0, 30.0, po.GEAR_P)
  assert not parked and not ctrl.armed


def test_park_held_3s_goes_offroad():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, flip = run(ctrl, t, 2.9, po.GEAR_P)
  assert not parked
  _, parked, _ = run(ctrl, t, 0.2, po.GEAR_P)
  assert parked


def test_park_hold_timing():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  _, parked, flip = run(ctrl, t, 5.0, po.GEAR_P)
  assert parked and po.PARK_HOLD_S <= flip <= po.PARK_HOLD_S + 0.1


def test_engaged_never_parks():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 10.0, po.GEAR_P, engaged=True)
  assert not parked
  _, parked, _ = run(ctrl, t, 3.1, po.GEAR_P)   # hold counts from Park, not from disengage
  assert parked


def test_neutral_resets_the_hold_and_keeps_offroad():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 2.0, po.GEAR_P)
  t, _, _ = run(ctrl, t, 0.5, po.GEAR_N)
  t, parked, _ = run(ctrl, t, 2.0, po.GEAR_P)
  assert not parked
  t, parked, _ = run(ctrl, t, 1.5, po.GEAR_P)
  assert parked
  _, parked, _ = run(ctrl, t, 5.0, po.GEAR_N)    # car wash
  assert parked


@pytest.mark.parametrize("gear", [po.GEAR_D, po.GEAR_R])
def test_d_or_r_returns_onroad_promptly(gear):
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 4.0, po.GEAR_P)
  assert parked
  _, parked, flip = run(ctrl, t, 1.0, gear)
  assert not parked and flip <= 0.1


def test_single_glitch_sample_does_not_return():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 4.0, po.GEAR_P)
  t, _, _ = run(ctrl, t, 0.05, po.GEAR_D)
  _, parked, _ = run(ctrl, t, 1.0, po.GEAR_P)
  assert parked


@pytest.mark.parametrize("name,return_gear", [
  ("tesla_tacc_route02_start.csv.gz", po.GEAR_R),          # backing out of the garage
  ("tesla_fsd_route0d_start.csv.gz", po.GEAR_R),
  ("tesla_tacc_route02_cancel_blip.csv.gz", po.GEAR_D),
])
def test_real_can_returns_onroad(name, return_gear):
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl, -10.0)
  run(ctrl, t, 4.0, po.GEAR_P)
  assert ctrl.parked
  flips = []
  for ts, frames in packets(load(name)):
    g, ap = po.sample(frames)
    if not ctrl.update(ts, g, True, False, ap) and not flips:
      flips.append((ts, g))
  assert flips and flips[0][1] == return_gear


def test_real_can_park_then_hold():
  """route02_start: P for one frame, then R. Never parks in a fresh ignition cycle; armed after R."""
  ctrl = po.ParkOffroad()
  for ts, frames in packets(load("tesla_tacc_route02_start.csv.gz"), every=1):
    g, ap = po.sample(frames)
    ctrl.update(ts, g, True, False, ap)
  assert not ctrl.parked and ctrl.armed


# -- ignition ----------------------------------------------------------------------

def test_real_ignition_cycle_clears_latch_and_next_ignition_is_todays_behavior():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 4.0, po.GEAR_P)
  assert parked
  t, parked, _ = run(ctrl, t, po.IGN_OFF_CLEAR_S + 1.0, None, ignition=False)   # car asleep: CAN stops too
  assert not parked and not ctrl.armed
  _, parked, _ = run(ctrl, t, 20.0, po.GEAR_P)      # ignition back on in Park: onroad, as today
  assert not parked


def test_ignition_can_blip_never_ends_the_latch():
  """Tesla stays in power state DRIVE in Park: an ignitionCan dropout + return must not go onroad."""
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 4.0, po.GEAR_P)
  assert parked
  for off_s in (0.1, 2.5, po.IGN_OFF_CLEAR_S - 0.2):
    t, parked, _ = run(ctrl, t, off_s, None, ignition=False)
    assert parked
    t, parked, _ = run(ctrl, t, 3.0, po.GEAR_P)
    assert parked
  _, parked, flip = run(ctrl, t, 1.0, po.GEAR_D)       # only R/D returns
  assert not parked and flip <= 0.1


def test_ignition_drop_when_not_parked_is_stock():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 0.5, po.GEAR_D, ignition=False)
  assert not parked and not ctrl.armed
  _, parked, _ = run(ctrl, t, 10.0, po.GEAR_P)
  assert not parked


def test_ignition_drop_while_driving_and_toggle_off():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 4.0, po.GEAR_P)
  assert not ctrl.update(t, po.GEAR_P, True, False, enabled=False)
  assert not ctrl.update(t + 0.05, po.GEAR_P, True, False)   # toggle back on: fresh cycle, not armed


# -- Summon / step aside -------------------------------------------------------------

def test_summon_keeps_offroad_then_driver_returns():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 4.0, po.GEAR_P)
  for gear in (po.GEAR_D, po.GEAR_R, po.GEAR_D):
    t, parked, _ = run(ctrl, t, 3.0, gear, autopark=3)      # ACTIVE: the car moves itself
    assert parked
  t, parked, _ = run(ctrl, t, 3.0, po.GEAR_P, autopark=4)   # COMPLETE, back in P
  assert parked
  t, parked, _ = run(ctrl, t, 3.0, po.GEAR_P, autopark=1)
  _, parked, _ = run(ctrl, t, 0.5, po.GEAR_D, autopark=1)   # driver shifts to D
  assert not parked


def test_autopark_hold_bridges_10hz_di_state():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 4.0, po.GEAR_P)
  ctrl.update(t, po.GEAR_P, True, False, 3)
  # D samples without a DI_state frame for 1 s: still Summon
  _, parked, _ = run(ctrl, t + 0.05, 1.0, po.GEAR_D)
  assert parked


def test_step_aside_flag_is_independent(tmp_path):
  """Stepped aside (FSD) or not, park-offroad only reads gear: both leave the relay open."""
  params = FakeParams(tmp_path, {"ParkOffroad": True, "ParkOffroadState": po.PARKED, "TeslaSteppedAside": True})
  assert po.not_parked(params) is False
  params.d["TeslaSteppedAside"] = False
  assert po.not_parked(params) is False


# -- CAN loss --------------------------------------------------------------------------

def test_no_gear_frames_offroad_falls_back_to_ignition():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 4.0, po.GEAR_P)
  assert parked
  t, parked, flip = run(ctrl, t, 3.0, None)
  assert not parked and ctrl.unavailable and po.CAN_TIMEOUT_S - 0.1 < flip <= po.CAN_TIMEOUT_S + 0.1
  t, _, _ = run(ctrl, t, 2.0, po.GEAR_D)
  _, parked, _ = run(ctrl, t, 10.0, po.GEAR_P)
  assert not parked     # disarmed until ignition cycles: no on/off loop


def test_state_parking_then_parked():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  assert ctrl.state == po.NONE
  t, _, _ = run(ctrl, t, 0.1, po.GEAR_P)
  assert ctrl.state == po.PARKING            # first Park sample: the card can go up now
  t, _, _ = run(ctrl, t, 0.5, None)          # a missed 0x118 sample doesn't flap it
  assert ctrl.state == po.PARKING
  t, _, _ = run(ctrl, t, 2.5, po.GEAR_P)
  assert ctrl.state == po.PARKED
  run(ctrl, t, 0.2, po.GEAR_D)
  assert ctrl.state == po.NONE


def test_parking_cancelled_by_leaving_park_or_engaging():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 1.0, po.GEAR_P)
  assert ctrl.state == po.PARKING
  t, _, _ = run(ctrl, t, 0.1, po.GEAR_D)
  assert ctrl.state == po.NONE
  run(ctrl, t, 1.0, po.GEAR_P, engaged=True)
  assert ctrl.state == po.NONE


def test_parking_needs_fresh_gear_frames():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, _, _ = run(ctrl, t, 1.0, po.GEAR_P)
  _, parked, _ = run(ctrl, t, po.CAN_TIMEOUT_S + 0.2, None)
  assert ctrl.state == po.NONE and not parked


# -- first run: what a fresh parkd does on its first ignition cycle -------------------

def test_first_run_cold_start_in_park_is_stock():
  ctrl = po.ParkOffroad()
  _, parked, _ = run(ctrl, 0.0, 10.0, po.GEAR_P)
  assert not parked and ctrl.state == po.NONE      # never seen R/D: onroad as today


def test_first_run_cold_start_in_drive_arms():
  ctrl = po.ParkOffroad()
  t, _, _ = run(ctrl, 0.0, 2.0, po.GEAR_D)
  _, parked, flip = run(ctrl, t, 4.0, po.GEAR_P)
  assert parked and abs(flip - po.PARK_HOLD_S) < 0.1


def test_first_run_no_gear_data_is_stock():
  ctrl = po.ParkOffroad()
  _, parked, _ = run(ctrl, 0.0, 10.0, None)
  assert not parked and ctrl.state == po.NONE


def test_first_run_toggle_off_is_stock():
  ctrl = po.ParkOffroad()
  t = 0.0
  for gear in (po.GEAR_D, po.GEAR_P):
    for _ in range(100):
      assert ctrl.update(t, gear, True, False, None, enabled=False) is False
      t += 0.05
  assert ctrl.state == po.NONE


def test_first_run_ignition_off_clears_hold():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 4.0, po.GEAR_P)
  assert parked
  t, parked, _ = run(ctrl, t, po.IGN_OFF_CLEAR_S + 0.5, po.GEAR_P, ignition=False)
  assert not parked
  _, parked, _ = run(ctrl, t, 5.0, po.GEAR_P)
  assert not parked                                 # fresh cycle in P: stock until R/D


def test_first_run_n_stays_offroad_r_returns():
  ctrl = po.ParkOffroad()
  t = drive_then_park(ctrl)
  t, parked, _ = run(ctrl, t, 4.0, po.GEAR_P)
  t, parked, _ = run(ctrl, t, 3.0, po.GEAR_N)
  assert parked
  _, parked, _ = run(ctrl, t, 0.2, po.GEAR_R)
  assert not parked


# -- hooks ---------------------------------------------------------------------------

class FakeParams:
  def __init__(self, root, d):
    self.root, self.d = root, dict(d)

  def get_param_path(self):
    return str(self.root)

  def check_key(self, key):
    return key

  def get(self, key, return_default=False):
    return self.d.get(key)

  def put_bool(self, key, value, block=False):
    self.d[key] = value

  def put(self, key, value, block=False):
    self.d[key] = value


def test_not_parked_hook(tmp_path):
  p = FakeParams(tmp_path, {})
  assert po.not_parked(p)
  p.d.update(ParkOffroadState=po.PARKED)
  assert po.not_parked(p)              # toggle off: no effect even if a stale state remains
  p.d.update(ParkOffroad=True)
  assert not po.not_parked(p)
  p.d.update(ParkOffroadState=po.PARKING)
  assert po.not_parked(p)              # parking is still onroad
  p.d.update(ParkOffroadState=None)
  assert po.not_parked(p) and po.get_state(p) == po.NONE   # key absent: stock
  assert po.should_run(False, p, None) and po.should_run(True, p, None)


def test_stale_params_library_reads_raw_file(tmp_path):
  class Stale(FakeParams):
    def check_key(self, key):
      raise KeyError(key)

    def put_bool(self, key, value, block=False):
      raise KeyError(key)

    def put(self, key, value, block=False):
      raise KeyError(key)
  p = Stale(tmp_path, {})
  assert po.not_parked(p)
  po.put_bool(p, "ParkOffroad", True)
  po.put_state(p, po.PARKED)
  assert (tmp_path / "ParkOffroad").read_bytes() == b"1"
  assert (tmp_path / "ParkOffroadState").read_bytes() == b"2"
  assert not po.not_parked(p)


def test_offroad_timer_restarts_at_ignition_off():
  tm = po.OffroadTimer()
  off = tm.update(True, True, True, None, 0.0)               # onroad
  off = tm.update(False, False, True, 10.0, 10.0)            # parked offroad, ignition on
  off = tm.update(False, False, True, off, 600.0)
  assert off == 10.0
  off = tm.update(False, False, False, off, 900.0)           # ignition off: timer restarts
  assert off == 900.0
  assert tm.update(True, False, False, off, 950.0) == 900.0


def test_offroad_timer_untouched_without_park():
  tm = po.OffroadTimer()
  tm.update(True, True, True, None, 0.0)
  assert tm.update(True, False, False, 5.0, 5.0) == 5.0      # plain ignition off: as today


def test_hardwared_and_manager_hooks():
  hw = (OP / "system/hardware/hardwared.py").read_text()
  assert 'onroad_conditions["not_parked"] = park_offroad.not_parked(params)' in hw
  assert "park_timer.update(" in hw
  pc = (OP / "system/manager/process_config.py").read_text()
  assert re.search(r'RestartingPythonProcess\("parkd", "openpilot.selfdrive.car.park_offroad", park_offroad.should_run', pc)


def test_params_keys():
  keys = (OP / "common/params_keys.h").read_text()
  assert '{"ParkOffroad", {PERSISTENT, BOOL, "0"}}' in keys
  assert '{"ParkOffroadState", {CLEAR_ON_MANAGER_START, INT, "0"}}' in keys
  assert '{"DriveSummary", {PERSISTENT, BOOL, "0"}}' in keys
  assert '{"DriveSummaryLast", {PERSISTENT, JSON}}' in keys
  assert "BACKUP" not in keys


def test_brand_gate_reads_car_params_persistent(tmp_path):
  from opendbc.car.structs import car
  cp = car.CarParams.new_message()
  cp.brand = "tesla"
  p = FakeParams(tmp_path, {"CarParamsPersistent": cp.to_bytes()})
  assert po._brand(p) == "tesla"
  cp = car.CarParams.new_message()
  cp.brand = "toyota"
  p.d["CarParamsPersistent"] = cp.to_bytes()
  assert "toyota" not in po.PARK_SOURCES and po.PARK_SOURCES["tesla"].sample is po.sample
  assert po._brand(p) == "toyota"
  p.d["CarParamsPersistent"] = None
  assert po._brand(p) == ""


# -- smoke test: parkd main() end to end, with hardwared / manager / loggerd simulated ---------------

class StopLoop(Exception):
  pass


def test_parkd_main_loop_smoke(monkeypatch, tmp_path):
  """Runs park_offroad.main() against fake msgq sockets. The "world" step mirrors hardwared
  (onroad = ignition and not_parked(params)) and manager/loggerd (each offroad -> onroad edge starts
  a new route), so it checks what the device does, not just the state machine."""
  import sys
  import types
  from types import SimpleNamespace
  from opendbc.car.structs import car

  clock = SimpleNamespace(t=1000.0)
  cp = car.CarParams.new_message()
  cp.brand = "tesla"
  params = FakeParams(tmp_path, {"ParkOffroad": True, "CarParamsPersistent": cp.to_bytes()})

  # scenario: (start s, gear or None for no frames, ignition)
  script = [(0, po.GEAR_P, True), (2, po.GEAR_D, True), (10, po.GEAR_P, True),
            (16, po.GEAR_P, False), (17, po.GEAR_P, True),                 # ignitionCan blip while latched
            (20, po.GEAR_R, True), (21, po.GEAR_D, True), (25, po.GEAR_P, True),
            (30, None, True),                                              # gear frames lost while latched
            (33, po.GEAR_P, True),
            (40, None, False), (48, po.GEAR_P, True), (55, po.GEAR_D, True), (58, po.GEAR_P, True)]
  END = 65.0

  def now_rel():
    return clock.t - 1000.0

  def state():
    cur = script[0]
    for row in script:
      if now_rel() >= row[0]:
        cur = row
    return cur[1], cur[2]

  world = SimpleNamespace(started=False, route=0, log=[], states=[])

  class Sock:
    pass

  def recv_one_or_none(sock):
    gear, _ = state()
    if gear is None:
      return None
    return SimpleNamespace(can=[SimpleNamespace(address=a, src=b, dat=d) for a, b, d in (frame_118(gear), frame_286(1))])

  class SubMaster:
    def __init__(self, services):
      self.recv_frame = dict.fromkeys(services, 0)
      self.recv_time = dict.fromkeys(services, 0.0)
      self.data = {"pandaStates": [], "selfdriveState": SimpleNamespace(enabled=False)}

    def update(self, timeout=0):
      _, ign = state()
      self.data["pandaStates"] = [SimpleNamespace(ignitionLine=False, ignitionCan=ign)]
      self.recv_frame["pandaStates"] += 1
      self.recv_time["pandaStates"] = clock.t

    def __getitem__(self, k):
      return self.data[k]

  class Ratekeeper:
    def __init__(self, *a, **k):
      pass

    def keep_time(self):
      clock.t += 0.05
      _, ign = state()
      started = ign and po.not_parked(params)          # hardwared's onroad decision, our condition included
      if started and not world.started:
        world.route += 1                               # manager starts loggerd: a new route
      world.started = started
      world.log.append((round(now_rel(), 2), started, world.route))
      world.states.append(po.get_state(params))
      if now_rel() >= END:
        raise StopLoop

  messaging = types.ModuleType("openpilot.cereal.messaging")
  messaging.sub_sock = lambda *a, **k: Sock()
  messaging.recv_one_or_none = recv_one_or_none
  messaging.SubMaster = SubMaster
  params_mod = types.ModuleType("openpilot.common.params")
  params_mod.Params = lambda: params
  realtime = types.ModuleType("openpilot.common.realtime")
  realtime.Ratekeeper = Ratekeeper
  monkeypatch.setitem(sys.modules, "openpilot.cereal.messaging", messaging)
  import openpilot.cereal
  monkeypatch.setattr(openpilot.cereal, "messaging", messaging, raising=False)
  monkeypatch.setitem(sys.modules, "openpilot.common.params", params_mod)
  monkeypatch.setitem(sys.modules, "openpilot.common.realtime", realtime)
  import time as _time
  monkeypatch.setattr(_time, "monotonic", lambda: clock.t)

  with pytest.raises(StopLoop):
    po.main()

  def at(sec):
    return next((st, r) for t, st, r in world.log if t >= sec)

  assert at(1.0) == (True, 1)            # ignition on in Park: onroad as today
  assert at(12.9) == (True, 1)           # Park held < 3 s
  assert at(13.3) == (False, 1)          # Park held 3 s: normal offroad transition (route 1 ends)
  assert at(16.5) == (False, 1)          # ignition off blip
  assert at(19.9) == (False, 1)          # ignition back (power state DRIVE): still offroad, no new route
  assert at(20.3) == (True, 2)           # R: onroad again as a NEW route
  assert at(28.3) == (False, 2)          # parked again
  assert at(31.9) == (False, 2)
  assert at(32.3) == (True, 3)           # gear frames lost 2 s: stock ignition behavior (onroad)
  assert at(39.9) == (True, 3)           # disarmed until a real ignition cycle: no on/off loop
  assert at(40.2)[0] is False            # ignition off: offroad
  assert at(48.5) == (True, 4)           # real ignition cycle (8 s off) cleared everything: onroad as today
  assert at(57.9) == (True, 4)
  assert at(61.3) == (False, 4)          # armed again after D: Park held 3 s -> offroad
  assert params.d["ParkOffroadState"] == po.NONE   # main() clears the latch on exit
  assert world.states[0] == po.NONE and po.PARKING in world.states and po.PARKED in world.states
  assert max(r for _, _, r in world.log) == 4


UIDIR = OP / "selfdrive/ui"


def test_toggles_set_both_params():
  for path in (UIDIR / "layouts/settings/toggles.py", UIDIR / "mici/layouts/settings/toggles.py"):
    src = path.read_text()
    assert "park_offroad.PARAM_ENABLED, on" in src and "drive_summary.PARAM_ENABLED, on" in src
    assert "ParkOffroadConfirmPage" in src or "ConfirmDialog(content" in src
