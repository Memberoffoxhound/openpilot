"""Highland's Jetlink adapter: off means off, the params fallback, and the
interface jetlink holds the adapter to."""
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from openpilot.selfdrive import jetlink_adapter as ja

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  return tmp_path / 'd'


def test_top_level_is_stdlib_only():
  # manager and the UI import this; jetlinkd stays ~10 MB
  heavy = "('numpy', 'zmq', 'capnp', 'jetlink', 'openpilot.common.params')"
  code = f"import sys; import openpilot.selfdrive.jetlink_adapter; print([m for m in {heavy} if m in sys.modules])"
  out = subprocess.check_output([sys.executable, '-c', code], cwd=ROOT, text=True).strip()
  assert out == '[]'


def test_off_by_default_never_binds(params_root, monkeypatch):
  monkeypatch.setattr(ja, '_api', lambda: pytest.fail('jetlink bound with the setting off'))
  assert ja.link_mode_file() == 0
  assert ja.should_run(False, None, None) is False
  assert ja.should_run(True, None, None) is False
  assert ja.prepare(False) is False
  small = object()
  assert ja.attach(small, small, 1344, 760) is small


def test_chestnut_wins(params_root, monkeypatch):
  ja.file_put('JetlinkLink', 2)
  monkeypatch.setattr(ja, '_api', lambda: pytest.fail('bound beside a chestnut'))
  assert ja.prepare(True) is False


def test_file_fallback_formats(params_root):
  ja.file_put('JetlinkLink', 2)
  assert (params_root / 'JetlinkLink').read_bytes() == b'2'
  assert ja.file_get('JetlinkLink') == 2
  ja.file_put('JetlinkChargePhone', True)
  assert (params_root / 'JetlinkChargePhone').read_bytes() == b'1'
  ja.file_put('JetlinkSpec', {'built': True})
  assert ja.file_get('JetlinkSpec') == {'built': True}
  ja.file_remove('JetlinkSpec')
  assert ja.file_get('JetlinkSpec') is None
  assert not list(params_root.glob('.tmp_*'))


def test_link_mode_survives_stale_params(params_root, monkeypatch):
  # a params library that predates the key raises UnknownKeyName
  class Stale:
    def get(self, key, *a, **k):
      raise RuntimeError('UnknownKeyName')
    def put(self, key, *a, **k):
      raise RuntimeError('UnknownKeyName')
  fake = type(sys)('openpilot.common.params')
  fake.Params = Stale
  monkeypatch.setitem(sys.modules, 'openpilot.common.params', fake)
  assert ja.link_mode() == 0
  ja.set_link_mode(2)
  assert ja.link_mode() == 2
  assert ja.link_mode_file() == 2
  ja.set_link_mode(9)
  assert ja.link_mode() == 0


def test_jetlink_reads_what_we_write(params_root):
  settings = pytest.importorskip('jetlink.openpilot.settings')
  from jetlink.openpilot.interface import Keys
  s = settings.Settings(settings.FileParams(params_root), Keys(**ja.KEYS._asdict()))
  assert s.mode() == 'off'
  for i, mode in enumerate(ja.MODES):
    ja.file_put('JetlinkLink', i)
    assert s.mode() == mode
  assert s.charge_phone() is False


def test_api_and_modes_match_jetlink():
  jl = pytest.importorskip('jetlink.openpilot')
  from jetlink.openpilot import interface
  assert jl.API == ja.API
  assert interface.MODES == ja.MODES


def test_conformance(monkeypatch):
  pytest.importorskip('jetlink.openpilot')
  from jetlink.openpilot.interface import Openpilot, conformance
  a = ja.Adapter.__new__(ja.Adapter)  # without cloudlog/basedir imports
  a.keys, a.log, a.basedir, a._stores, a._sm = None, None, ROOT, {}, None
  assert conformance(a, Openpilot) == []


def test_keys_declared():
  header = (ROOT / 'openpilot/common/params_keys.h').read_text()
  declared = set(re.findall(r'\{"(\w+)",', header))
  wanted = {k for k in ja.KEYS if k}
  assert wanted <= declared, wanted - declared


def test_manager_registers_jetlinkd():
  src = (ROOT / 'openpilot/system/manager/process_config.py').read_text()
  assert 'RestartingPythonProcess(jetlink_adapter.OWNER, "openpilot.selfdrive.jetlink_adapter", jetlink_adapter.should_run' in src
  assert importlib.util.find_spec('openpilot.selfdrive.jetlink_adapter') is not None


def test_submodule_pin():
  gm = (ROOT / '.gitmodules').read_text()
  assert 'path = jetlink_repo' in gm and 'zoompilot/jetlink' in gm
