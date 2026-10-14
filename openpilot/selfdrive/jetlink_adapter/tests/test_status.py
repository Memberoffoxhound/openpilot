"""Jetlink UI status logic (selfdrive/ui/jetlink_status.py) and modeld's live file."""
from collections import namedtuple

import pytest

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.ui import jetlink_status as js

S = namedtuple('S', 'enabled transport present progress model active_model runnable reason', defaults=(None,) * 8)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.setenv('JETLINK_LIVE_PATH', str(tmp_path / 'live.json'))
  monkeypatch.setattr(ja._live, 'start', 0.0)


def ready(**kw):
  base = {'enabled': True, 'transport': 'iOS over USB (iPhone17,2)', 'present': True, 'model': 'Cinque Terre V3 Model',
              'active_model': 'Cinque Terre V3 Model', 'runnable': True}
  base.update(kw)
  return S(**base)


def test_off():
  s = js.evaluate('off', ready(), {'state': 'running', 'big': True}, True, True)
  assert s.state == js.OFF and s.icon is None


def test_offroad_states():
  assert js.evaluate('ios', None, None, False, False).state == js.UNAVAILABLE
  assert js.evaluate('ios', ready(present=False), None, False, False).state == js.WAITING
  assert js.evaluate('ios', ready(present=False), None, False, False).icon is None
  p = js.evaluate('ios', ready(progress={'stage': 'download', 'frac': 0.4, 'msg': '1.2 GB'}), None, False, False)
  assert (p.state, p.icon, p.progress) == (js.PREPARING, js.ICON_PULSE, ('download', 0.4, '1.2 GB'))
  r = js.evaluate('ios', ready(), None, False, False)
  assert (r.state, r.icon, r.model) == (js.READY, js.ICON_DIM, 'Cinque Terre V3 Model')
  assert js.evaluate('ios', ready(runnable=False), None, False, False).icon is None


def test_onroad_states():
  live = {'state': 'running', 'big': True, 'exec_ms_mean': 37.2, 'exec_ms_max': 47.0, 'over_budget': 0, 'frames': 20}
  d = js.evaluate('ios', ready(), live, True, True)
  assert (d.state, d.icon) == (js.DRIVING, js.ICON_ACTIVE)
  assert d.timing.startswith('37 ms avg / 47 ms max (budget 50 ms')
  # modelV2 says small: not lit
  assert js.evaluate('ios', ready(), live, True, False).icon == js.ICON_DIM
  assert js.evaluate('ios', ready(), {'state': 'joining', 'big': False}, True, False).state == js.JOINING
  assert js.evaluate('ios', ready(), {'state': 'ready', 'big': False}, True, False).state == js.WAITING_SWITCH
  fb = js.evaluate('ios', ready(), {'state': 'unavailable', 'big': False}, True, False)
  assert (fb.state, fb.icon) == (js.FELL_BACK, js.ICON_DIM)
  assert js.evaluate('usb', ready(present=False), None, True, False).icon is None


def test_drops_named():
  s = js.evaluate('ios', ready(progress={'stage': 'join', 'frac': 0, 'msg': 'linking', 'drops': 3}), None, False, False)
  assert 'check cable/app (3 drops)' in s.progress[2]


def test_publish_live_window():
  class Joining:
    big_model_state = 'running'
    chestnut = True
  assert ja.publish_live(object(), 0.03, now=1.0) is False  # small model: nothing written
  assert not ja.live_path().exists()
  m = Joining()
  assert ja.publish_live(m, 0.030, now=10.0) is False
  assert ja.publish_live(m, 0.060, now=10.5) is False
  assert ja.publish_live(m, 0.040, now=11.0) is True
  live = ja.read_live()
  assert live['big'] is True and live['frames'] == 3 and live['over_budget'] == 1 and live['exec_ms_max'] == 60.0


def test_read_live_stale_and_garbage():
  ja.live_path().write_text('{"t": 0, "state": "running"}')
  assert ja.read_live(now=100.0) is None
  ja.live_path().write_text('not json')
  assert ja.read_live() is None


def test_ui_never_raises(monkeypatch):
  monkeypatch.setattr(ja, 'link_mode', lambda: 2)
  monkeypatch.setattr(ja, 'status', lambda: (_ for _ in ()).throw(RuntimeError('boom')))
  ui = js.JetlinkUI()
  assert ui.refresh(now=100.0).state == js.OFF


def test_charge_phone_fallback():
  assert ja.charge_phone() is False
  ja.set_charge_phone(True)
  assert ja.charge_phone() is True
