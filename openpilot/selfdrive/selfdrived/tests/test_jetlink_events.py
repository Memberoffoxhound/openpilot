"""selfdrived's Jetlink swap events (jetlink_events.py) over jetlink's own
SwapEvents, fed the joining model's state as modeld's runtime record says it."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.cereal import log
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.selfdrived import jetlink_events as je

EventName = log.OnroadEvent.EventName
HERE = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  return tmp_path / 'd'


class SM(dict):
  def __init__(self, big=False):
    super().__init__(modelV2=SimpleNamespace(big=big))
    self.seen = self.alive = self.valid = {'modelV2': True}


class Events(list):
  def add(self, name):
    self.append(name)


def test_link_off_is_inert_and_never_imports_jetlink(monkeypatch):
  monkeypatch.setattr(ja, 'hooks', lambda: pytest.fail('jetlink imported with the link off'))
  ev = je.JetlinkEvents()
  assert ev.swap is None and not ev.settling
  events = Events()
  ev.update(SM(), True, events)
  assert events == []
  assert je.JetlinkEvents.OPTIONAL_PROCESSES == {'jetlinkd'}


@pytest.fixture
def tracked(monkeypatch):
  hooks = pytest.importorskip('jetlink.openpilot.hooks')
  from jetlink.openpilot.events import SwapEvents
  runtime = SimpleNamespace(state='none')

  class FakeHooks:
    def runtime(self):
      return runtime

    def _net(self, name, default, fn, *args):
      return fn(*args)
  monkeypatch.setattr(ja, 'swap_events', lambda tick: hooks.SwapTracker(SwapEvents(tick), FakeHooks(), tick))
  return runtime


def _run(ev, runtime, state, big, in_control, ticks):
  runtime.state = state
  seen = []
  for _ in range(ticks):
    events = Events()
    ev.update(SM(big), in_control, events)
    seen.append(tuple(events))
  return seen


def test_offer_swap_no_entry_chime_and_link_lost(tracked):
  ev = je.JetlinkEvents()
  # engaged, the big model ready: offered once, for OFFER_S
  seen = _run(ev, tracked, 'ready', False, True, je.OFFER_TICKS + 50)
  offered = [s for s in seen if EventName.jetlinkBigModelAvailable in s]
  assert je.OFFER_TICKS - 25 <= len(offered) <= je.OFFER_TICKS + 1
  # disengaged: it swaps in; a second of no entry (bigModelLoading), then the chime
  seen = _run(ev, tracked, 'running', True, False, je.SWITCHING_TICKS + 20)
  no_entry = [i for i, s in enumerate(seen) if EventName.bigModelLoading in s]
  chime = [i for i, s in enumerate(seen) if EventName.jetlinkBigModelActive in s]
  assert len(chime) == 1 and no_entry and max(no_entry) < chime[0]
  assert abs(len(no_entry) - je.SWITCHING_TICKS) <= 25
  assert ev.settling is False
  # engaged on the big model, the link drops: warned for HANDBACK_S, nothing else
  seen = _run(ev, tracked, 'retrying', False, True, je.HANDBACK_TICKS + 50)
  lost = [s for s in seen if EventName.jetlinkBigModelLost in s]
  assert abs(len(lost) - je.HANDBACK_TICKS) <= 25
  assert all(set(s) <= {EventName.jetlinkBigModelLost} for s in seen)


def test_the_events_are_native_and_never_disengage():
  assert (EventName.jetlinkBigModelAvailable, EventName.jetlinkBigModelLost, EventName.jetlinkBigModelActive) == (106, 107, 108)
  tree = ast.parse((HERE / 'events.py').read_text())
  events = next(n.value for n in ast.walk(tree) if isinstance(n, ast.AnnAssign) and getattr(n.target, 'id', '') == 'EVENTS')
  found = {}
  for key, value in zip(events.keys, events.values, strict=True):
    if isinstance(key, ast.Attribute) and key.attr.startswith('jetlinkBigModel'):
      found[key.attr] = {k.attr for k in value.keys}
  assert found == {'jetlinkBigModelAvailable': {'PERMANENT'}, 'jetlinkBigModelLost': {'WARNING'},
                   'jetlinkBigModelActive': {'PERMANENT'}}


def test_selfdrived_carries_the_lines():
  src = (HERE / 'selfdrived.py').read_text()
  assert 'self.jetlink_events = JetlinkEvents()' in src
  assert 'self.jetlink_events.update(self.sm, self.enabled, self.events)' in src
  assert 'or self.jetlink_events.settling' in src
  assert "*JetlinkEvents.OPTIONAL_PROCESSES" in src
  assert DT_CTRL == 0.01
