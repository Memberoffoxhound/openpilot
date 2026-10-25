"""Nudgeless auto lane change: the lane change starts START_DELAY (0.75 s)
after the blinker, never sooner, and blind spot / brake still hold it."""
import sys
import types
from types import SimpleNamespace

import pytest

try:
  from openpilot.common.params import Params  # noqa: F401  (needs the built params library)
  _STUB = None
except (ImportError, OSError):
  _STUB = types.ModuleType("openpilot.common.params")


class FakeParams:
  def __init__(self, *a, **k):
    pass

  def get_bool(self, key, *a, **k):
    return key == "AutoLaneChangeEnabled"


@pytest.fixture
def dh_module(monkeypatch):
  if _STUB is not None:
    _STUB.Params = FakeParams
    monkeypatch.setitem(sys.modules, "openpilot.common.params", _STUB)
    for m in ("openpilot.selfdrive.controls.lib.auto_lane_change", "openpilot.selfdrive.controls.lib.desire_helper"):
      sys.modules.pop(m, None)
  from openpilot.selfdrive.controls.lib import auto_lane_change as alc
  from openpilot.selfdrive.controls.lib import desire_helper as dh
  monkeypatch.setattr(alc, "Params", FakeParams)
  return dh, alc


def cs(left=True, blind=False, brake=False):
  return SimpleNamespace(vEgo=30.0, leftBlinker=left, rightBlinker=False, steeringPressed=False, steeringTorque=0.0,
                         leftBlindspot=blind, rightBlindspot=False, brakePressed=brake)


def run_until_start(dh, alc, frames=60, **kw):
  from openpilot.cereal import log
  h = dh.DesireHelper()
  h.update(cs(left=False), True, 0.0)
  for i in range(frames):
    h.update(cs(**kw), True, 0.0)
    if h.lane_change_state == log.LaneChangeState.laneChangeStarting:
      return i * dh.DT_MDL
  return None


def test_start_delay_is_0_75_s(dh_module):
  dh, alc = dh_module
  assert alc.START_DELAY == 0.75


def test_lane_change_starts_after_0_75_s(dh_module):
  dh, alc = dh_module
  t = run_until_start(dh, alc)
  assert t is not None
  assert 0.75 <= t <= 0.75 + 2 * dh.DT_MDL


def test_blindspot_holds_lane_change(dh_module):
  dh, alc = dh_module
  assert run_until_start(dh, alc, blind=True) is None


def test_brake_cancels_auto_lane_change(dh_module):
  dh, alc = dh_module
  assert run_until_start(dh, alc, brake=True) is None
