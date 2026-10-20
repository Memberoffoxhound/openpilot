"""Highland's model manager and its Jetlink wiring.

Ported from zoompilot's sunnypilot/models/tests/test_manager_download.py and
test_default_bootstrap.py (the big-model slot, the catalog cache, fetcher_zp's
refetch on a hardware change, an empty catalog never resetting the pick, a
dropped model falling back to the default), on Highland's dict bundles. New
here: the raw-file fallbacks for a params library older than the keys, the
default catalog before the first fetch, and a pick resolving through jetlink
itself (Models.selected_model and link.identity).

Every test runs on the raw param files (no params library on the box, which is
the stale-library case on a device), under a PARAMS_ROOT of its own.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive import modelmanager as mm
from openpilot.selfdrive.modelmanager import store
from openpilot.selfdrive.modelmanager.manager import ModelManager
from openpilot.selfdrive.ui import model_picker as mp

ROOT = Path(__file__).resolve().parents[4]
REF_A = 'a' * 40
REF_B = 'b' * 40
REF_OLD = 'c' * 40


def bundle(ref, name, index, folder='Big Models', selector='20'):
  return {'short_name': name[:4].upper(), 'display_name': f'{name} (October 01, 2026)', 'ref': ref, 'index': index,
          'minimum_selector_version': selector, 'generation': '12', 'environment': 'release', 'runner': 'tinygrad',
          'is_20hz': True, 'is_big': True, 'overrides': {'folder': folder}, 'models': []}


CATALOG = {'tinygrad_ref': 'x', 'bundles': [bundle(REF_A, 'Alpha', 1), bundle(REF_B, 'Bravo', 2, folder='New'),
                                            bundle(REF_OLD, 'Old', 3, selector='19')]}


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  store._store.clear()
  # no params library here: Params() fails and every read is the file
  monkeypatch.setattr(store, '_params', mock.Mock(side_effect=ImportError('no params_pyx')))
  monkeypatch.setattr(ja, 'should_extend_catalog', lambda: False)
  monkeypatch.setattr(ja, 'extend_catalog', lambda c: c)
  return tmp_path / 'd'


class Clock:
  def __init__(self, t=1000.0):
    self.t = t

  def __call__(self):
    return self.t


def manager(fetch=None, clock=None):
  return ModelManager(fetch=fetch or mock.Mock(return_value=json.loads(json.dumps(CATALOG))), clock=clock or Clock(),
                      wall=lambda: 1_790_000_000, log=mock.Mock())


# -- keys and params ----------------------------------------------------------------

def test_keys_declared_without_backup():
  header = (ROOT / 'openpilot/common/params_keys.h').read_text()
  for key in mm.KEY_TYPES:
    line = next((ln for ln in header.splitlines() if f'{{"{key}",' in ln), None)
    assert line is not None, key
    assert 'BACKUP' not in line
  assert 'BACKUP' not in header


def test_jetlink_keys_are_the_model_managers():
  assert ja.KEYS.big_model == 'ModelManager_ActiveBundleChestnut' == mm.ACTIVE_BIG
  assert ja.KEYS.catalog == 'ModelManager_ModelsCache_Chestnut' == mm.CACHE_BIG
  assert {mm.ACTIVE_BIG, mm.CACHE_BIG} <= ja.JSON_KEYS
  assert ja.Adapter.catalog_selector.fget(None) == mm.REQUIRED_JSON_VERSION == 20


@pytest.mark.parametrize('key,value', [(mm.ACTIVE_BIG, {'ref': REF_A, 'displayName': 'Alpha'}), (mm.SYNC_BIG, 12345),
                                       (mm.DOWNLOAD_REF, REF_B), (mm.STATUS, {'state': 'idle'})])
def test_store_falls_back_to_the_raw_file(params_root, key, value):
  store.put(key, value)
  raw = (params_root / key).read_bytes()
  assert raw == (json.dumps(value).encode() if isinstance(value, dict) else str(value).encode())
  assert store.get(key) == value
  store.remove(key)
  assert store.get(key) is None and not (params_root / key).exists()


def test_store_reads_a_garbled_file_as_unset(params_root):
  params_root.mkdir(parents=True)
  (params_root / mm.CACHE_BIG).write_bytes(b'{not json')
  assert store.get(mm.CACHE_BIG) is None
  assert mp.bundles() == []


def test_store_uses_params_when_it_knows_the_key(monkeypatch):
  fake = mock.Mock()
  fake.get.return_value = {'ref': REF_A}
  monkeypatch.setattr(store, '_params', lambda: fake)
  assert store.get(mm.ACTIVE_BIG) == {'ref': REF_A}
  store.put(mm.ACTIVE_BIG, {'ref': REF_B})
  fake.put.assert_called_once_with(mm.ACTIVE_BIG, {'ref': REF_B}, block=True)


def test_adapter_reads_the_pick_from_the_file(params_root):
  a = ja.Adapter.__new__(ja.Adapter)
  a._stores = {}
  store.put(mm.ACTIVE_BIG, {'ref': REF_A, 'displayName': 'Alpha'})
  with mock.patch.object(ja.Adapter, '_params', side_effect=ImportError):
    assert a.get(ja.KEYS.big_model) == {'ref': REF_A, 'displayName': 'Alpha'}


def test_adapter_catalog_defaults_until_fetched():
  pytest.importorskip('jetlink.registry.catalog')
  from jetlink.registry.catalog import DEFAULT_BIG_MODEL_REF
  a = ja.Adapter.__new__(ja.Adapter)
  a._stores = {}
  with mock.patch.object(ja.Adapter, '_params', side_effect=ImportError):
    cat = a.get(ja.KEYS.catalog)
    assert [b['ref'] for b in mm.catalog_bundles(cat)] == [DEFAULT_BIG_MODEL_REF]
    store.put(mm.CACHE_BIG, CATALOG)
    assert a.get(ja.KEYS.catalog) == CATALOG


# -- the catalog -------------------------------------------------------------------

def test_catalog_lists_selector_20_newest_first():
  assert [b['ref'] for b in mm.catalog_bundles(CATALOG)] == [REF_B, REF_A]
  assert mm.catalog_bundles(None) == [] and mm.catalog_bundles({'bundles': 'x'}) == []


def test_first_step_fetches_and_caches():
  m = manager()
  m.step()
  m.fetch.assert_called_once()
  assert store.get(mm.CACHE_BIG)['bundles'][0]['ref'] == REF_A
  assert store.get(mm.CACHE_BIG)[mm.EXTENDED_KEY] is False
  assert store.get(mm.SYNC_BIG) == int(1000.0 * 1e9)
  assert store.get(mm.STATUS)['state'] == 'idle' and store.get(mm.STATUS)['models'] == 2


def test_matching_cache_is_used_without_fetch():
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  clock.t += 600
  m.step()
  assert m.fetch.call_count == 1


def test_cache_expires_after_an_hour_and_on_refresh():
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  clock.t += mm.CACHE_TIMEOUT
  m.step()
  assert m.fetch.call_count == 2
  mp.refresh()
  m.step()
  assert m.fetch.call_count == 3


def test_corrupt_cache_is_refetched(params_root):
  m = manager()
  m.step()
  (params_root / mm.CACHE_BIG).write_bytes(b'garbage')
  store.put(mm.SYNC_BIG, 0)
  m.step()
  assert m.fetch.call_count == 2 and mm.catalog_bundles(store.get(mm.CACHE_BIG))


def test_failed_fetch_keeps_the_cache_and_backs_off():
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  m.fetch.side_effect = OSError('offline')
  store.put(mm.SYNC_BIG, 0)
  m.step()
  assert store.get(mm.STATUS)['state'] == 'failed'
  assert mm.catalog_bundles(store.get(mm.CACHE_BIG))
  for _ in range(5):
    clock.t += 1
    m.step()
  assert m.fetch.call_count == 2  # backing off, not a request a second
  clock.t += 30
  m.step()
  assert m.fetch.call_count == 3
  mp.refresh()  # the UI's refresh skips the back-off
  m.step()
  assert m.fetch.call_count == 4


def test_offline_first_boot_does_not_spin():
  clock = Clock()
  m = manager(fetch=mock.Mock(side_effect=OSError('offline')), clock=clock)
  for _ in range(10):
    clock.t += 1
    m.step()
  assert m.fetch.call_count == 1


def test_empty_catalog_is_not_cached():
  m = manager(fetch=mock.Mock(return_value={'bundles': []}))
  m.step()
  assert store.get(mm.CACHE_BIG) is None and store.get(mm.STATUS)['state'] == 'failed'


def test_extended_through_jetlink(monkeypatch):
  extra = bundle('d' * 40, 'Delta', 9)
  monkeypatch.setattr(ja, 'should_extend_catalog', lambda: True)
  monkeypatch.setattr(ja, 'extend_catalog', lambda c: {**c, 'bundles': [*c['bundles'], extra]})
  m = manager()
  m.step()
  cat = store.get(mm.CACHE_BIG)
  assert cat[mm.EXTENDED_KEY] is True and mm.catalog_bundles(cat)[0]['ref'] == 'd' * 40


def test_hardware_change_refetches_once(monkeypatch):
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  monkeypatch.setattr(ja, 'should_extend_catalog', lambda: True)
  clock.t += 1
  m.step()
  assert m.fetch.call_count == 2
  m.fetch.side_effect = OSError('offline')  # the refetch failed: the cache stands, no loop
  store.put(mm.CACHE_BIG, {**CATALOG, mm.EXTENDED_KEY: False})
  store.put(mm.SYNC_BIG, int(clock.t * 1e9))
  for _ in range(5):
    clock.t += 1
    m.step()
  assert m.fetch.call_count == 2


# -- the pick ----------------------------------------------------------------------

def test_pick_is_stored_without_files():
  m = manager()
  m.step()
  mp.select(REF_B)
  m.step()
  slot = store.get(mm.ACTIVE_BIG)
  assert slot['ref'] == REF_B and slot['displayName'] == 'Bravo (October 01, 2026)' and slot['models'] == []
  assert slot['minimumSelectorVersion'] == 20 and {'key': 'folder', 'value': 'New'} in slot['overrides']
  assert store.get(mm.DOWNLOAD_REF) is None
  assert mp.big_model_label() == 'bravo'


def test_pick_waits_for_a_catalog():
  m = manager(fetch=mock.Mock(side_effect=OSError('offline')))
  mp.select(REF_B)
  m.step()
  assert store.get(mm.DOWNLOAD_REF) == REF_B and store.get(mm.ACTIVE_BIG) is None


def test_unlisted_pick_is_refused():
  m = manager()
  m.step()
  mp.select(REF_OLD)  # selector 19: not for this build
  m.step()
  assert store.get(mm.ACTIVE_BIG) is None and store.get(mm.DOWNLOAD_REF) is None
  assert store.get(mm.STATUS)['state'] == 'failed'


def test_a_model_the_new_catalog_lacks_falls_back_to_the_default(monkeypatch):
  monkeypatch.setattr(ja, 'should_extend_catalog', lambda: True)
  m = manager()
  store.put(mm.ACTIVE_BIG, {'ref': 'e' * 40, 'displayName': 'Withdrawn'})
  m.step()
  assert store.get(mm.ACTIVE_BIG) is None


def test_without_jetlink_a_newer_catalogs_pick_is_kept(monkeypatch):
  monkeypatch.setattr(ja, '_api', lambda: None)  # jetlink could not bind: no newer catalogs
  m = manager()
  store.put(mm.ACTIVE_BIG, {'ref': 'e' * 40, 'displayName': 'Train Track'})
  m.step()
  assert store.get(mm.ACTIVE_BIG)['ref'] == 'e' * 40


def test_offline_keeps_the_pick():
  store.put(mm.ACTIVE_BIG, {'ref': 'e' * 40, 'displayName': 'Kept'})
  m = manager(fetch=mock.Mock(side_effect=OSError('offline')))
  m.step()
  assert store.get(mm.ACTIVE_BIG)['ref'] == 'e' * 40


def test_empty_catalog_does_not_reset_the_pick():
  store.put(mm.ACTIVE_BIG, {'ref': REF_A, 'displayName': 'Alpha'})
  manager(fetch=mock.Mock(return_value={'bundles': []})).step()
  assert store.get(mm.ACTIVE_BIG)['ref'] == REF_A


def test_reset_to_default():
  store.put(mm.ACTIVE_BIG, {'ref': REF_A})
  store.put(mm.DOWNLOAD_REF, REF_B)
  mp.reset_to_default()
  assert store.get(mm.ACTIVE_BIG) is None and store.get(mm.DOWNLOAD_REF) is None
  assert mp.big_model_label().endswith('(default)')


def test_a_failing_step_never_kills_the_loop(monkeypatch):
  m = manager()
  monkeypatch.setattr(m, 'process_request', mock.Mock(side_effect=RuntimeError('boom')))
  m.step()
  m.log.exception.assert_called()


# -- the picker's lists ------------------------------------------------------------

def test_folders_newest_first():
  store.put(mm.CACHE_BIG, CATALOG)
  assert [(f, [b['ref'] for b in bs]) for f, bs in mp.folders()] == [('New', [REF_B]), ('Big Models', [REF_A])]
  assert mp.list_label().startswith('2 models')


# -- through jetlink ---------------------------------------------------------------

def _jetlink_op():
  pytest.importorskip('jetlink.openpilot.models')
  a = ja.Adapter.__new__(ja.Adapter)
  from jetlink.openpilot.interface import Keys
  a.keys, a.log, a.basedir, a._stores, a._sm = Keys(**ja.KEYS._asdict()), mock.Mock(), ROOT, {}, None
  return a


def test_jetlink_runs_the_pick(params_root):
  op = _jetlink_op()
  from jetlink.openpilot.link import identity
  from jetlink.openpilot.models import Models
  with mock.patch.object(ja.Adapter, '_params', side_effect=ImportError):
    m = manager()
    m.step()
    models = Models(op)
    assert [x['ref'] for x in models.catalog()] == [REF_B, REF_A]
    mp.select(REF_A)
    m.step()
    models = Models(op)  # its slot cache lives INDEX_TTL
    assert models.selected_slot() == {'name': 'Alpha (October 01, 2026)', 'ref': REF_A}
    selected = models.selected_model()
    assert selected['ref'] == REF_A
    store_ptrs = {REF_A: {'oid': 'f' * 64, 'size': 1234}}
    ja.file_put(ja.KEYS.pointers, store_ptrs)
    parts = SimpleNamespace(models=models, progress=mock.Mock())
    assert identity(parts, selected) == ('f' * 64, 1234)
    # a pointer looked up the first time, through the registry
    ja.file_put(ja.KEYS.pointers, {})
    models = Models(op)
    with mock.patch.object(Models, 'fetch_pointer', return_value=('9' * 64, 99)) as fetch:
      parts = SimpleNamespace(models=models, progress=mock.Mock())
      assert identity(parts, models.selected_model()) == ('9' * 64, 99)
      fetch.assert_called_once_with(REF_A)


def test_jetlink_default_with_no_pick():
  op = _jetlink_op()
  from jetlink.openpilot.models import Models
  from jetlink.registry.catalog import DEFAULT_BIG_MODEL_REF
  with mock.patch.object(ja.Adapter, '_params', side_effect=ImportError):
    # before the first fetch: jetlink's default, as before the model manager
    assert Models(op).selected_model()['ref'] == DEFAULT_BIG_MODEL_REF
    store.put(mm.CACHE_BIG, {'bundles': [*CATALOG['bundles'], bundle(DEFAULT_BIG_MODEL_REF, 'Cinque Terre V3', 0)]})
    assert Models(op).selected_model()['ref'] == DEFAULT_BIG_MODEL_REF


def test_jetlink_extends_at_selector_20():
  """jetlink's merge keeps the newer catalogs' bundles at our selector, so its
  own catalog() (== catalog_selector) lists them."""
  pytest.importorskip('jetlink.registry.catalog')
  from jetlink.registry.catalog import merge_catalogs
  newer = {'bundles': [bundle('d' * 40, 'Delta', 30, selector='21')]}
  merged = merge_catalogs([CATALOG, newer], selector=mm.REQUIRED_JSON_VERSION)
  assert 'd' * 40 in [b['ref'] for b in mm.catalog_bundles(merged)]


# -- manager and selfdrived --------------------------------------------------------

def test_manager_registers_modelmanagerd():
  src = (ROOT / 'openpilot/system/manager/process_config.py').read_text()
  assert ('RestartingPythonProcess("modelmanagerd", "openpilot.selfdrive.modelmanager.manager", only_offroad, enabled=not PC)'
          in src)


def test_selfdrived_never_waits_for_modelmanagerd():
  src = (ROOT / 'openpilot/selfdrive/selfdrived/selfdrived.py').read_text()
  assert "p.name not in ('jetlinkd', 'modelmanagerd')" in src


def test_modelmanager_imports_light():
  """manager, the UI and process_config import these: nothing heavy at import."""
  for path in (ROOT / 'openpilot/selfdrive/modelmanager').glob('*.py'):
    tree = ast.parse(path.read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {(n.module or '') if isinstance(n, ast.ImportFrom) else n.names[0].name for n in top}
    assert not names & {'numpy', 'tinygrad', 'cereal', 'requests', 'openpilot.common.params'}, (path.name, names)


# -- the mici page, over stand-in widgets (no raylib on the test box) ---------------

class _Widget:
  def __init__(self, text='', value='', *a, **k):
    self.text, self.value, self.cb, self.enabled = text, value, None, True

  def set_click_callback(self, cb):
    self.cb = cb

  def set_enabled(self, enabled):
    self.enabled = enabled

  def get_value(self):
    return self.value

  def set_value(self, value):
    self.value = value


class _Scroller:
  def __init__(self):
    self.widgets = []

  def add_widgets(self, widgets):
    self.widgets += widgets


class _NavScroller:
  def __init__(self, **k):
    self._scroller = _Scroller()

  def show_event(self):
    pass

  def _update_state(self):
    pass


@pytest.fixture
def page(monkeypatch):
  import importlib
  import sys
  import types
  gui = SimpleNamespace(stack=[], push_widget=None, pop_widgets_to=None)
  gui.push_widget = gui.stack.append
  gui.pop_widgets_to = lambda w: gui.stack.clear()
  fakes = {
    'openpilot.selfdrive.ui.mici.widgets.button': {'BigButton': _Widget, 'GreyBigButton': _Widget},
    'openpilot.selfdrive.ui.ui_state': {'ui_state': SimpleNamespace(started=False)},
    'openpilot.system.ui.lib.application': {'gui_app': gui},
    'openpilot.system.ui.widgets.scroller': {'NavScroller': _NavScroller},
    'openpilot.selfdrive.ui.jetlink_status': {'jetlink_ui': SimpleNamespace(
      _at=0.0, refresh=lambda started, big: SimpleNamespace(state='off', progress=('download', 0.5, 'train track')))},
  }
  for name, attrs in fakes.items():
    monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
  monkeypatch.delitem(sys.modules, 'openpilot.selfdrive.ui.mici.layouts.settings.models', raising=False)
  mod = importlib.import_module('openpilot.selfdrive.ui.mici.layouts.settings.models')
  return mod, gui


def test_models_page_picks_and_resets(page):
  mod, gui = page
  store.put(mm.CACHE_BIG, CATALOG)
  p = mod.ModelsLayoutMici()
  p._update_state()
  assert p._big.value.endswith('(default)') and p._progress.value == 'download 50% train track'
  assert p._refresh.value.startswith('2 models')
  p._big.cb()                      # the folders
  folders = gui.stack[-1]._scroller.widgets
  assert [w.text for w in folders] == [f'{mp.default_name()} ({mp.DEFAULT_LABEL})'.lower(), 'new', 'big models']
  folders[1].cb()                  # the models in "new"
  models = gui.stack[-1]._scroller.widgets
  assert [w.text for w in models] == ['bravo']
  models[0].cb()
  assert store.get(mm.DOWNLOAD_REF) == REF_B and gui.stack == []
  manager().process_request()
  p._tick = 0
  p._update_state()
  assert p._big.value == 'bravo'
  p._reset.cb()
  assert store.get(mm.ACTIVE_BIG) is None
  p._refresh.cb()
  assert store.get(mm.SYNC_BIG) == 0


def test_models_page_locked_onroad(page):
  mod, _ = page
  p = mod.ModelsLayoutMici()
  mod.ui_state.started = True
  assert not p._big.enabled() and not p._refresh.enabled() and not p._reset.enabled()
