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


@pytest.fixture
def no_hooks(monkeypatch):
  monkeypatch.setattr(ja, '_hooks', None)
  monkeypatch.setattr(ja, 'hooks', lambda: pytest.fail('jetlink imported with the setting off'))


def test_off_by_default_never_imports_jetlink(params_root, no_hooks, monkeypatch, tmp_path):
  monkeypatch.setattr(ja, 'SHUTDOWN_REQUEST', tmp_path / 'no-request')
  assert ja.link_mode_file() == 0
  assert ja.should_run(False, None, None) is False
  assert ja.should_run(True, None, None) is False
  assert ja.prepare(False) is False
  small = object()
  assert ja.attach(small, small, 1344, 760) is small
  assert ja.status() is None and ja.reason() is None and ja.runtime() is None
  assert ja.swap_events(0.01) is None
  assert ja.shutdown_step(False) is False and ja.shutdown_step(True, 'test') is True
  assert ja.handed_over(small) is False and ja.state(small) == 'none'


def test_a_pending_power_off_asks_jetlink_even_with_the_link_off(params_root, monkeypatch, tmp_path):
  request = tmp_path / 'jetlink-shutdown'
  request.write_text('x')
  monkeypatch.setattr(ja, 'SHUTDOWN_REQUEST', request)
  monkeypatch.setattr(ja, '_hooks', None)
  asked = []
  monkeypatch.setattr(ja, 'hooks', lambda: type('H', (), {'shutdown_step': lambda self, w, r='': asked.append(w) or True})())
  assert ja.shutdown_step(False) is True and asked == [False]


def test_shutdown_request_is_jetlinks():
  gadget = pytest.importorskip('jetlink.comma.gadget')
  assert gadget.SHUTDOWN_REQUEST == ja.SHUTDOWN_REQUEST


def test_chestnut_wins(params_root, no_hooks):
  ja.file_put('JetlinkLink', 2)
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


def test_conformance():
  pytest.importorskip('jetlink.openpilot.stock')
  from jetlink.openpilot.interface import Openpilot, conformance
  from jetlink.openpilot.stock import Stock
  a = ja.Adapter()
  a.__dict__.update(log=None, basedir=ROOT)  # Stock's cached properties, without swaglog
  assert isinstance(a, Stock)
  assert conformance(a, Openpilot) == []
  assert a.keys.progress == 'AcceleratorProgress' and a.keys.big_model == 'ModelManager_ActiveBundleChestnut'
  assert a.IN_CONTROL_SERVICES == ('carState', 'carControl', 'selfdriveState')  # jetlink's own rule
  # stock modeld's warp, which Highland's SConscript compiles into selfdrive/modeld/models
  assert a.warp_path(1344, 760, 512, 256) == ROOT / 'openpilot/selfdrive/modeld/models/driving_warp_1344x760_tinygrad.pkl'


def test_jetlinks_adapter_check():
  testing = pytest.importorskip('jetlink.openpilot.testing')
  assert testing.check_adapter(ja, heavy=('openpilot.common.params', 'openpilot.common.swaglog', 'openpilot.cereal')) == []


def test_the_fallback_answers_as_the_link_off(params_root):
  testing = pytest.importorskip('jetlink.openpilot.testing')
  assert testing.check_fallback(ja._Off("jetlink package API 9, this build expects 3"), ja.HOOK_NAMES, link_on=ja._link_on) == []
  ja.file_put('JetlinkLink', 1)
  assert ja._Off("why").reason() == "why"
  ja.file_put('JetlinkLink', 0)
  assert ja._Off("why").reason() is None


def test_the_module_hooks_answer_as_the_link_off_with_it_off(params_root, monkeypatch, tmp_path):
  testing = pytest.importorskip('jetlink.openpilot.testing')
  monkeypatch.setattr(ja, 'SHUTDOWN_REQUEST', tmp_path / 'no-request')
  monkeypatch.setattr(ja, '_hooks', None)
  # model_state and the catalog are the model manager's and bind with the link off, as jetlink's own
  names = [n for n in ja.HOOK_NAMES if n not in ('model_state', 'should_extend_catalog', 'extend_catalog')]
  assert testing.check_fallback(ja, names, link_on=ja._link_on) == []
  assert ja._hooks is None


def test_hooks_without_a_checkout_are_the_link_off(monkeypatch):
  monkeypatch.setitem(sys.modules, 'jetlink', None)   # import jetlink raises ModuleNotFoundError
  assert isinstance(ja._guard(), ja._Off)


def test_hooks_are_jetlinks_with_a_checkout():
  pytest.importorskip('jetlink.openpilot.hooks')
  from jetlink.openpilot.hooks import Hooks
  assert isinstance(ja._guard(), Hooks)


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


class FakeParams:
  """A Params that knows AdbEnabled and JetlinkLink, over one dict."""
  store: dict = {}

  def get(self, key, *a, **k):
    return self.store.get(key)

  def get_bool(self, key, *a, **k):
    return bool(self.store.get(key))

  def put(self, key, value, *a, **k):
    self.store[key] = value

  def put_bool(self, key, value, *a, **k):
    self.store[key] = bool(value)


def test_link_on_turns_adb_off(params_root, monkeypatch):
  # AGNOS's ADB gadget (g1) holds the USB controller, and jetlink-root.sh will not take it
  FakeParams.store = {'AdbEnabled': True}
  fake = type(sys)('openpilot.common.params')
  fake.Params = FakeParams
  monkeypatch.setitem(sys.modules, 'openpilot.common.params', fake)
  ja.set_link_mode(0)
  assert FakeParams.store['AdbEnabled'] is True and not ja.adb_blocked()
  assert ja.release_adb() is False
  ja.set_link_mode(2)                      # iphone: the toggle turns ADB off
  assert FakeParams.store['AdbEnabled'] is False
  ja.file_put('JetlinkLink', 2)            # the link mode as jetlinkd/UI read it
  assert ja.adb_blocked()
  FakeParams.store['AdbEnabled'] = True    # turned back on elsewhere
  assert ja.release_adb() is True and FakeParams.store['AdbEnabled'] is False
  assert ja.release_adb() is False         # already off: no write


def test_release_adb_file_fallback(params_root, monkeypatch):
  class Broken:
    def __init__(self):
      raise RuntimeError('no params library')
  fake = type(sys)('openpilot.common.params')
  fake.Params = Broken
  monkeypatch.setitem(sys.modules, 'openpilot.common.params', fake)
  ja.file_put('AdbEnabled', b'1')
  assert ja.release_adb() is False         # link off: ADB left alone
  assert (params_root / 'AdbEnabled').read_bytes() == b'1'
  ja.file_put('JetlinkLink', 1)
  assert ja.release_adb() is True
  assert (params_root / 'AdbEnabled').read_bytes() == b'0'
