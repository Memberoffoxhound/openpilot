"""hardwared's Jetlink lines (jetlink_power.py): the accelerator's power-off
on shutdown, the startup block while it runs, and the offroad alert."""
import json
import re
from pathlib import Path

import pytest

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.system.hardware import jetlink_power as jp

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  monkeypatch.setattr(ja, 'SHUTDOWN_REQUEST', tmp_path / 'no-request')
  return tmp_path / 'd'


class Clock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t


def test_link_off_shuts_down_at_once_without_jetlink(monkeypatch):
  monkeypatch.setattr(ja, '_hooks', None)
  monkeypatch.setattr(ja, 'hooks', lambda: pytest.fail('jetlink imported with the link off'))
  power = jp.JetlinkPower(now=Clock())
  assert power.shutdown_ready(False, None) is False and not power.powering_off
  assert power.shutdown_ready(True, 1.0) is True and power.powering_off
  alerts = []
  power.alerts(lambda *a, **k: alerts.append((a, k)))
  assert alerts == [((ja.OFFROAD_ALERT, False), {'extra_text': None})]


def test_link_on_waits_for_jetlink_then_the_cap(monkeypatch):
  ja.file_put('JetlinkLink', 1)
  steps = []
  answer = [False]

  class FakeHooks:
    def shutdown_step(self, wanted, reason=''):
      steps.append(wanted)
      return answer[0] if wanted else False
  monkeypatch.setattr(ja, 'hooks', lambda: FakeHooks())
  clock = Clock()
  power = jp.JetlinkPower(now=clock)
  assert power.shutdown_ready(False, None) is False      # every loop from boot asks
  assert power.shutdown_ready(True, 5.0) is False and power.powering_off
  clock.t += 10
  assert power.shutdown_ready(False, 5.0) is False       # the power monitor is not asked again
  answer[0] = True
  assert power.shutdown_ready(False, 5.0) is True        # jetlink says the far end is down
  assert steps == [False, True, True, True]
  # and a jetlink that never answers is cut off at the cap
  answer[0] = False
  power = jp.JetlinkPower(now=clock)
  assert power.shutdown_ready(True, 5.0) is False
  clock.t += jp.ACCELERATOR_OFF_WAIT_T - 0.1
  assert power.shutdown_ready(True, 5.0) is False
  clock.t += 0.2
  assert power.shutdown_ready(True, 5.0) is True


def test_alert_says_why_and_never_raises(monkeypatch):
  ja.file_put('JetlinkLink', 2)
  monkeypatch.setattr(ja, 'reason', lambda: 'no warp built for this camera')
  alerts = []
  power = jp.JetlinkPower(now=Clock())
  power.alerts(lambda *a, **k: alerts.append((a, k)))
  assert alerts == [((ja.OFFROAD_ALERT, True), {'extra_text': 'no warp built for this camera'})]

  def broken(*a, **k):
    raise RuntimeError('UnknownKeyName')
  power.alerts(broken)   # logged, not raised


def test_hardwared_carries_the_lines():
  src = (ROOT / 'openpilot/system/hardware/hardwared.py').read_text()
  assert 'jetlink_power.alerts(set_offroad_alert_if_changed)' in src
  assert 'startup_conditions["not_powering_off"] = not jetlink_power.powering_off' in src
  assert re.search(r'if jetlink_power\.shutdown_ready\(power_monitor\.should_shutdown\(.*\), off_ts\):\n\s+params\.put_bool\("DoShutdown"', src)


def test_the_alert_is_declared():
  header = (ROOT / 'openpilot/common/params_keys.h').read_text()
  assert '{"Offroad_AcceleratorUnavailable", {CLEAR_ON_MANAGER_START, JSON}}' in header
  alerts = json.loads((ROOT / 'openpilot/selfdrive/selfdrived/alerts_offroad.json').read_text())
  assert alerts[ja.OFFROAD_ALERT]['text'] == 'Jetlink unavailable: %1'
