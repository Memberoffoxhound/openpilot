"""The Jetlink status display, as zoompilot's: the chestnut icons driven by
jetlink's Status.icon() (ui_state._jetlink_state), and the models panel's lines
(selfdrive/ui/accelerator_link.py). ui_state needs raylib, so its ChestnutState
values are read from the source."""
import ast
import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.ui import accelerator_link as al

UI = Path(__file__).resolve().parents[1]


def chestnut_values() -> set[str]:
  tree = ast.parse((UI / 'ui_state.py').read_text())
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ChestnutState')
  return {n.value.value for n in cls.body if isinstance(n, ast.Assign)}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))


def status(runnable=True, **kw):
  from jetlink.openpilot.status import Status
  base = {'enabled': True, 'mode': 'ios', 'transport': 'iOS over USB (iPhone17,2)', 'present': True, 'port': 'host',
          'ready': runnable, 'reason': None, 'progress': None, 'model': 'Cinque Terre V3 Model',
          'default_model': 'Cinque Terre V3 Model'}
  base.update(kw)
  return Status(**base)


def test_every_icon_is_a_chestnut_state():
  values = chestnut_values()
  assert 'waiting' in values
  states = ('none', 'joining', 'retrying', 'ready', 'running', 'unavailable')
  for present, runnable, stage in itertools.product((True, False), (True, False), (None, 'download', 'failed', 'ready')):
    s = status(present=present, runnable=runnable, progress={'stage': stage, 'frac': 0.5, 'msg': 'x'} if stage else None)
    for started, seen, big, st in itertools.product((True, False), (True, False), (True, False), states):
      assert s.icon(started, seen, big, st) in values


def test_icon_like_zoompilot():
  s = status()
  assert s.icon(False, False, False, 'none') == 'ready'
  assert status(progress={'stage': 'download', 'frac': 0.4, 'msg': '1 GB'}).icon(False, False, False, 'none') == 'loading'
  assert s.icon(True, True, True, 'running') == 'active'
  assert s.icon(True, True, False, 'ready') == 'waiting'          # dimmed on home
  assert s.icon(True, True, False, 'joining') == 'loading'
  assert s.icon(True, True, False, 'unavailable') == 'failed'
  assert status(present=False).icon(True, True, False, 'none') == 'disconnected'


def test_home_uses_chestnut_icons_only():
  home = (UI / 'mici/layouts/home.py').read_text()
  hud = (UI / 'mici/onroad/hud_renderer.py').read_text()
  assert 'jetlink_metal' not in home + hud and 'jetlink_status' not in home + hud
  assert 'ChestnutState.WAITING' in home and 'set_opacity(0.5 if waiting else 1.0)' in home
  assert not list((UI.parent / 'assets/icons_mici').glob('jetlink_metal*'))


def test_link_mode_and_toggle():
  assert al.link_mode() == 'off'
  assert al.link_toggle_meaningful(False) and not al.link_toggle_meaningful(True)
  ja.set_link_mode(ja.MODES.index('ios'))
  assert al.link_mode() == 'ios' and al.link_toggle_meaningful(True)
  assert [al.LINK_MODE_LABELS[m] for m in ja.MODES] == ['off', 'usb', 'iOS']


def test_link_status():
  assert al.link_status(None) == ''
  assert al.link_status(SimpleNamespace(port_state='connected', transport='iOS over USB')) == 'Jetlink connected: iOS over USB.'
  assert al.link_status(SimpleNamespace(port_state='empty')) == 'Nothing on the USB port.'
  assert al.link_status(SimpleNamespace(port_state=None)) == ''


def test_progress_and_drops():
  assert al.big_model_progress(None) is None
  assert al.big_model_progress(SimpleNamespace(progress={'stage': 'ready'})) is None
  p = al.big_model_progress(SimpleNamespace(mode='ios', progress={'stage': 'join', 'frac': 0, 'msg': 'linking', 'drops': 3}))
  assert p == ('join', 0.0, 'linking, check cable or app (3 drops)')


def test_model_info():
  small, big = 'built-in', 'Cinque Terre'
  j = SimpleNamespace(active_model='Tomb Raider', progress=None, standin=None, port_state='connected', transport='x')
  assert al.model_info(j, 'active', False, small, big) == ('tomb raider', 'big model', 'cinque terre')
  assert al.model_info(j, 'waiting', False, small, big)[0] == 'built-in'
  assert al.model_info(j, 'loading', False, small, big)[2] == 'getting ready'
  assert al.model_info(j, 'failed', False, small, big)[2] == 'unavailable'
  j.progress = {'stage': 'download', 'frac': 0.42, 'msg': 'downloading'}
  assert al.model_info(j, 'loading', False, small, big)[2] == 'downloading 42%'
  j.progress, j.standin = None, 'Old Model'
  assert al.model_info(j, 'ready', False, small, big)[2] == 'old model for now'
  assert al.model_info(None, 'disconnected', False, small, big) == ('built-in', 'big model', 'cinque terre')
  assert al.model_info(object(), 'active', False, small, big)[0] == 'built-in'   # never raises
