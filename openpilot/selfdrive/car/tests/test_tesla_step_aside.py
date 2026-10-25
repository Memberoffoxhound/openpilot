"""Tesla step-aside: the detector, the onroad-cycle state machine, the params
fallback, and replays of the routes that motivated it.

Fixtures (tests/fixtures/*.csv.gz) are the frames of 0x39B DAS_status,
0x488 DAS_steeringControl, 0x286 DI_state, 0x2B9 DAS_control and 0x118
DI_systemStatus (buses 0 and 2) cut from public routes of 3e2de7ed673817c2:
  - 0000000d--38fdfd7b2f seg 0, t 0-3 s: FSD driving from power-on, relay open
  - 00000002--1695634c6e seg 0, t 0-9.5 s: TACC selected, parked, relay open
  - 00000002--1695634c6e seg 4: 20 s around a 0.4 s DAS_accState 13 blip
    (scroll-wheel cancel) while driving on openpilot
Set TESLA_STEP_ASIDE_RLOG_DIRS to directories of full rlog.zst files to also
replay whole TACC segments and the full FSD segment.
"""
import glob
import gzip
import os
from pathlib import Path

import pytest

from openpilot.selfdrive.car import tesla_step_aside as tsa

FIXTURES = Path(__file__).parent / "fixtures"


# -- detector -----------------------------------------------------------------

def sig(ap=1, steer=0, autopark=0, acc=0):
  return tsa.StockSignals(ap_state=ap, steer_type=steer, autopark_state=autopark, acc_state=acc)


@pytest.mark.parametrize("ap", [3, 4, 5, 6, 8])
def test_active_autopilot_states(ap):
  d = tsa.StockDetector()
  assert d.update(sig(ap=ap), 0.0) and d.active


@pytest.mark.parametrize("ap", [0, 1, 9, 14, 15])
def test_idle_autopilot_states_do_not_own(ap):
  d = tsa.StockDetector()
  assert not d.update(sig(ap=ap), 0.0)


def test_fsd_steering_type_is_active():
  d = tsa.StockDetector()
  assert d.update(sig(steer=4), 0.0) and d.active
  assert not d.update(sig(steer=2), 0.1)  # stock LKAS is not Tesla driving


@pytest.mark.parametrize("state", sorted(tsa.AUTOPARK_ACTIVE_STATES))
def test_autopark_states_are_active(state):
  d = tsa.StockDetector()
  assert d.update(sig(autopark=state), 0.0)


@pytest.mark.parametrize("state", [0, 1, 6, 8])
def test_autopark_idle_states(state):
  d = tsa.StockDetector()
  assert not d.update(sig(autopark=state), 0.0)


def test_cancel_silent_run_selects_after_1p5s():
  d = tsa.StockDetector()
  t = 0.0
  while t < 1.45:
    assert not d.update(sig(acc=13), t)
    t += 0.04
  assert d.update(sig(acc=13), 1.5) and d.selected and not d.active


def test_scroll_wheel_cancel_blip_does_not_select():
  d = tsa.StockDetector()
  t = 0.0
  for _ in range(5):  # 0.42 s of 13, then ACC_ON, five times
    for _ in range(11):
      assert not d.update(sig(acc=13), t)
      t += 0.04
    assert not d.update(sig(acc=4), t)
    t += 0.04


def test_available_flicker_holds_selection():
  d = tsa.StockDetector()
  assert d.update(sig(ap=2), 0.0) and d.selected
  assert d.update(sig(ap=1), 1.0)       # flickers back to UNAVAILABLE
  assert d.update(sig(ap=1), 2.0)
  assert not d.update(sig(ap=1), 2.1)   # AVAILABLE gone for > 2 s


# -- controller ---------------------------------------------------------------

def test_enter_needs_debounce_and_openpilot_disengaged():
  c = tsa.StepAsideController(stepped_aside=False, start_t=0.0)
  assert c.update(True, False, False, False, 1.0) is None
  assert c.update(True, False, False, False, 1.1) is None
  assert c.update(True, False, False, False, 1.25) == tsa.ENTER
  assert c.update(True, False, False, False, 1.3) is None  # asks once


def test_never_enter_while_openpilot_engaged():
  c = tsa.StepAsideController(stepped_aside=False, start_t=0.0)
  for t in (1.0, 2.0, 3.0):
    assert c.update(True, True, False, True, t) is None
  # owned the whole time, so the first disengaged step enters
  assert c.update(True, False, False, True, 3.1) == tsa.ENTER


def test_enter_debounce_resets_when_stock_lets_go():
  c = tsa.StepAsideController(stepped_aside=False, start_t=0.0)
  assert c.update(True, False, False, False, 1.0) is None
  assert c.update(False, False, False, False, 1.1) is None
  assert c.update(True, False, False, False, 1.15) is None
  assert c.update(True, False, False, False, 1.3) is None
  assert c.update(True, False, False, False, 1.4) == tsa.ENTER


def test_return_needs_3s_clear_and_park_or_cruise_off():
  c = tsa.StepAsideController(stepped_aside=True, start_t=0.0)
  # still owned: never
  for t in (5.0, 10.0):
    assert c.update(True, False, True, False, t) is None
  # clear from 10.5, in Drive with cruise on: never
  for t in (10.5, 12.0, 14.0, 20.0):
    assert c.update(False, False, False, True, t) is None
  # cruise off -> back (clear for >= 3 s already)
  assert c.update(False, False, False, False, 20.1) == tsa.RETURN


def test_return_in_park():
  c = tsa.StepAsideController(stepped_aside=True, start_t=0.0)
  assert c.update(False, False, True, True, 6.0) is None
  assert c.update(False, False, True, True, 8.9) is None
  assert c.update(False, False, True, True, 9.0) == tsa.RETURN


def test_return_never_before_min_stepped():
  c = tsa.StepAsideController(stepped_aside=True, start_t=0.0)
  assert c.update(False, False, True, False, 0.0) is None
  assert c.update(False, False, True, False, 3.5) is None
  assert c.update(False, False, True, False, 4.9) is None
  assert c.update(False, False, True, False, 5.0) == tsa.RETURN


def test_owned_again_restarts_return_timer():
  c = tsa.StepAsideController(stepped_aside=True, start_t=0.0)
  assert c.update(False, False, True, False, 6.0) is None
  assert c.update(True, False, True, False, 8.0) is None
  assert c.update(False, False, True, False, 8.1) is None
  assert c.update(False, False, True, False, 11.0) is None
  assert c.update(False, False, True, False, 11.1) == tsa.RETURN


def test_is_park():
  assert tsa.is_park("park") and tsa.is_park(1)
  assert not tsa.is_park("drive") and not tsa.is_park(4) and not tsa.is_park("unknown")


# -- params -------------------------------------------------------------------

class FakeParams:
  """Params with a key list; unknown keys raise like a stale params library."""
  def __init__(self, root, keys=(tsa.PARAM_ENABLED, tsa.PARAM_STEPPED, "OnroadCycleRequested")):
    self.root, self.keys, self.store = str(root), set(keys), {}
    self.defaults = {tsa.PARAM_ENABLED: True}

  def check_key(self, key):
    if key not in self.keys:
      raise KeyError(key)
    return key

  def get(self, key, return_default=False):
    self.check_key(key)
    if key in self.store:
      return self.store[key]
    return self.defaults.get(key) if return_default else None

  def put_bool(self, key, val, block=False):
    self.check_key(key)
    self.store[key] = bool(val)

  def get_param_path(self, key=""):
    return os.path.join(self.root, key)


def test_param_defaults(tmp_path):
  p = FakeParams(tmp_path)
  assert tsa.enabled(p) is True
  assert tsa.stepped_aside(p) is False
  tsa.put_bool(p, tsa.PARAM_ENABLED, False)
  assert tsa.enabled(p) is False


def test_params_fallback_when_keys_unknown(tmp_path):
  p = FakeParams(tmp_path, keys=())
  assert tsa.enabled(p) is True           # default on
  assert tsa.stepped_aside(p) is False
  tsa.put_bool(p, tsa.PARAM_STEPPED, True)
  assert (tmp_path / tsa.PARAM_STEPPED).read_bytes() == b"1"
  assert tsa.stepped_aside(p) is True
  tsa.put_bool(p, tsa.PARAM_ENABLED, False)
  assert tsa.enabled(p) is False


def test_module_is_stdlib_only():
  import subprocess
  import sys
  root = Path(__file__).resolve().parents[4]
  heavy = "('numpy', 'capnp', 'opendbc', 'openpilot.common.params')"
  code = f"import sys; import openpilot.selfdrive.car.tesla_step_aside; print([m for m in {heavy} if m in sys.modules])"
  assert subprocess.check_output([sys.executable, "-c", code], cwd=root, text=True).strip() == "[]"


# -- replays through Tesla's real CarInterface --------------------------------

def make_ci(flags=None):
  from opendbc.car.tesla.interface import CarInterface
  CP = CarInterface.get_non_essential_params("TESLA_MODEL_3")
  if flags is not None:
    CP.flags = flags
  return CarInterface(CP)


def load_fixture(name):
  frames = []
  with gzip.open(FIXTURES / name, "rt") as f:
    for line in f:
      t, addr, src, dat = line.strip().split(",")
      frames.append((int(t), int(addr), int(src), bytes.fromhex(dat)))
  return frames


def packets_10ms(frames):
  """Group frames into 10 ms can packets, the way card drains them."""
  out, cur, cur_t = [], [], None
  for t, addr, src, dat in frames:
    if cur_t is None:
      cur_t = t
    if t - cur_t >= 10_000_000:
      out.append((cur_t, cur))
      cur, cur_t = [], t
    cur.append((addr, dat, src))
  if cur:
    out.append((cur_t, cur))
  return out


class Replay:
  def __init__(self, packets):
    self.packets = packets
    self.i = 0
    self.now = packets[0][0] / 1e9

  def recv(self):
    if self.i >= len(self.packets):
      self.now += 0.01
      return []
    t, frames = self.packets[self.i]
    self.i += 1
    self.now = t / 1e9
    return [(t, frames)]

  def clock(self):
    return self.now


def run_startup(packets, tmp_path):
  CI = make_ci()
  p = FakeParams(tmp_path)
  r = Replay(packets)
  sa = tsa.TeslaStepAside(CI, p, r.clock())
  stepped = sa.observe_startup(r.recv, r.clock)
  return sa, r, p, stepped


def test_replay_fsd_route_steps_aside_at_startup(tmp_path):
  # route 0000000d: FSD drove from power-on; the relay closed at t 9.79 s and FSD died
  sa, r, p, stepped = run_startup(packets_10ms(load_fixture("tesla_fsd_route0d_start.csv.gz")), tmp_path)
  assert stepped and sa.detector.active
  assert r.now - r.packets[0][0] / 1e9 < 1.0, "should decide within the first second, long before 9.79 s"
  sa.start(r.clock())
  assert p.store[tsa.PARAM_STEPPED] is True


def test_replay_tacc_parked_start_stays_normal(tmp_path):
  sa, r, p, stepped = run_startup(packets_10ms(load_fixture("tesla_tacc_route02_start.csv.gz")), tmp_path)
  assert not stepped
  assert r.now - r.packets[0][0] / 1e9 >= tsa.STARTUP_OBSERVE_S
  sa.start(r.clock())
  assert p.store[tsa.PARAM_STEPPED] is False


def test_replay_tacc_cancel_blip_never_enters(tmp_path):
  CI = make_ci()
  p = FakeParams(tmp_path)
  packets = packets_10ms(load_fixture("tesla_tacc_route02_cancel_blip.csv.gz"))
  sa = tsa.TeslaStepAside(CI, p, packets[0][0] / 1e9)
  sa.start(packets[0][0] / 1e9)
  saw13 = False
  for t, frames in packets:
    CS = CI.update([(t, frames)])
    assert sa.update(CS, False, t / 1e9) is None
    saw13 |= sa.detector.silent_since is not None
  assert saw13, "fixture should contain the scroll-wheel cancel blip"
  assert p.store.get("OnroadCycleRequested") is None


def _rlog_frames(path):
  import zstandard
  from openpilot.cereal import log
  data = zstandard.ZstdDecompressor().stream_reader(open(path, "rb")).read()
  for e in log.Event.read_multiple_bytes(data):
    if e.which() == "can":
      yield e.logMonoTime, [(m.address, bytes(m.dat), m.src) for m in e.can]


RLOG_DIRS = [d for d in os.environ.get("TESLA_STEP_ASIDE_RLOG_DIRS", "").split(os.pathsep) if d]


@pytest.mark.skipif(not RLOG_DIRS, reason="set TESLA_STEP_ASIDE_RLOG_DIRS to replay full rlogs")
def test_replay_full_rlogs(tmp_path):
  """Directories named after the route: *0000000d* must step aside at startup;
  every other segment is TACC selected and must never own the car."""
  checked = 0
  for d in RLOG_DIRS:
    for path in sorted(glob.glob(os.path.join(d, "*.zst"))):
      fsd = "0000000d" in path
      CI = make_ci()
      p = FakeParams(tmp_path / str(checked))
      det = tsa.StockDetector()
      owned_t = None
      t0 = None
      for t, frames in _rlog_frames(path):
        t0 = t0 or t
        CI.update([(t, frames)])
        if det.update(tsa.read_signals(CI.can_parsers), t / 1e9) and owned_t is None:
          owned_t = (t - t0) / 1e9
      if fsd:
        assert owned_t is not None and owned_t < 1.0, path
      else:
        assert owned_t is None, f"{path}: owned at {owned_t}"
      del p
      checked += 1
  assert checked > 0


def test_card_path_against_real_tesla_interface():
  """card builds TeslaStepAside from the real opendbc CarInterface and reads its
  parsers. Catches opendbc API drift (e.g. a TeslaFlags member the merge dropped)."""
  from opendbc.car.tesla.interface import CarInterface
  from openpilot.common.params import Params
  CP = CarInterface.get_non_essential_params("TESLA_MODEL_3")
  sa = tsa.TeslaStepAside(CarInterface(CP), Params(), 0.0)
  assert sa.observe(0.1) in (True, False)
  assert tsa.read_signals(sa.CI.can_parsers).steer_type == 0


def test_card_uses_only_existing_tesla_flags():
  import re
  from opendbc.car.tesla.values import TeslaFlags
  src = (Path(__file__).parents[1] / "card.py").read_text()
  for name in re.findall(r"TeslaFlags\.(\w+)", src):
    assert hasattr(TeslaFlags, name), name
