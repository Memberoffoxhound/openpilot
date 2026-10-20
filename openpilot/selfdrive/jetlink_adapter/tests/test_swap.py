"""The swap onto the phone's large model, over Highland's stock ModelState.

jetlink's joining model was written against sunnypilot's modeld_v2, whose
ModelState carries attributes Highland's does not. The first drive on the
jetlink branch (2026-10-20) failed every swap with
"AttributeError: 'ModelState' object has no attribute 'lat_delay'". Pinned
here: every attribute jetlink reads off the small model is one Highland's
ModelState sets or the adapter fills, and a real JoiningModelState swaps onto
the large model from a Highland-shaped small model.
"""
import ast
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from openpilot.selfdrive import jetlink_adapter as ja

ROOT = Path(__file__).resolve().parents[4]
MODELD = ROOT / 'openpilot/selfdrive/modeld/modeld.py'


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  return tmp_path / 'd'


def _loads(tree: ast.AST, base) -> set[str]:
  """Attribute names read (not assigned) off the expression `base` matches."""
  return {n.attr for n in ast.walk(tree)
          if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and base(n.value)}


def _function(tree: ast.AST, name: str) -> ast.AST:
  return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _jetlink_source(module: str) -> ast.AST:
  mod = pytest.importorskip(module)
  return ast.parse(Path(mod.__file__).read_text())


def _highland_model_state_attrs() -> set[str]:
  """What Highland's ModelState has: assigned on self anywhere in the class, and its methods."""
  cls = next(n for n in ast.walk(ast.parse(MODELD.read_text())) if isinstance(n, ast.ClassDef) and n.name == 'ModelState')
  attrs = {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
           and isinstance(n.value, ast.Name) and n.value.id == 'self'}
  attrs |= {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
  attrs |= {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
  return attrs


def _small_reads() -> set[str]:
  """Every attribute jetlink reads off the small model: the joining model's
  self._small.X and self._active.X, and warp.prepare_reset's model.X / keeper.X (keeper is the
  model itself on stock modeld; adapter is read with a getattr default)."""
  joining = _jetlink_source('jetlink.openpilot.joining')
  # self._active is the small model until a swap lands
  reads = _loads(joining, lambda v: isinstance(v, ast.Attribute) and v.attr in ('_small', '_active')
                 and isinstance(v.value, ast.Name) and v.value.id == 'self')
  reset = _function(_jetlink_source('jetlink.openpilot.warp'), 'prepare_reset')
  reads |= _loads(reset, lambda v: isinstance(v, ast.Name) and v.id in ('model', 'keeper'))
  return reads


def test_highland_covers_every_small_model_read():
  reads = _small_reads()
  assert {'lat_delay', 'PLANPLUS_CONTROL', 'run', 'prev_desire'} <= reads, reads  # the scan still finds them
  covered = _highland_model_state_attrs() | set(ja.SMALL_MODEL_DEFAULTS) | {'numpy_inputs'}
  assert reads <= covered, f"jetlink reads {sorted(reads - covered)} off the small model, which Highland lacks"


def test_highland_model_state_sets_lat_delay_and_modeld_writes_it():
  assert 'lat_delay' in _highland_model_state_attrs()
  assert 'model.lat_delay = lat_delay' in MODELD.read_text()


class HighlandModel:
  """Highland's stock modeld ModelState as jetlink sees it: exactly the
  attributes it sets, none of modeld_v2's."""

  def __init__(self, name, chestnut=False):
    self.name = name
    self.chestnut = chestnut
    self.prev_desire = np.zeros(8, dtype=np.float32)
    self.vision_input_names = ('img', 'big_img')
    self.npy = {'desire': np.zeros(8, dtype=np.float32)}
    self.calls = 0

  def run(self, bufs, transforms, inputs, after_enqueue=None):
    self.calls += 1
    if after_enqueue is not None:
      after_enqueue()
    return {'from': self.name}


class BigModel(HighlandModel):
  """JetlinkModelState's face: it sets lat_delay and PLANPLUS_CONTROL itself."""

  def __init__(self):
    super().__init__('big', chestnut=True)
    self.lat_delay = 0.0
    self.PLANPLUS_CONTROL = 1.0
    self.client = mock.Mock(dead=False)
    self.behind = None

  def close(self):
    pass


class Log:
  def __init__(self):
    self.lines = []

  def _add(self, level, msg, *args, **kwargs):
    self.lines.append((level, str(msg) % args if args else str(msg)))

  def debug(self, *a, **k): self._add('debug', *a)
  def info(self, *a, **k): self._add('info', *a)
  def warning(self, *a, **k): self._add('warning', *a)
  def error(self, *a, **k): self._add('error', *a)
  def exception(self, *a, **k): self._add('exception', *a)
  def event(self, *a, **k): pass


@pytest.fixture
def joining(monkeypatch):
  joining = pytest.importorskip('jetlink.openpilot.joining')
  monkeypatch.setattr(joining, 'SMALL_WARMUP_FRAMES', 0)
  # the join loop reads the USB-C port; never the machine's own
  monkeypatch.setattr(joining.gadget, 'host_attached', lambda: True)
  monkeypatch.setattr(joining.gadget, 'cc_orientation', lambda: 2)
  return joining


def _joining_state(joining, small, big, log):
  def connect(should_stop=None):
    return (mock.MagicMock(name='client'), 'spec')
  return joining.JoiningModelState(small, connect, lambda client, spec: big, progress=mock.Mock(), log=log)


def _swap(state, lat_delay=0.33, timeout=5.0):
  """modeld's frames until the joined link lands: lat_delay written first, as modeld does."""
  deadline = time.monotonic() + timeout
  while state._joined is None and state._big is None and time.monotonic() < deadline:
    time.sleep(0.002)
  assert state._joined is not None or state._big is not None, 'never joined'
  state.in_control = False
  state.lat_delay = lat_delay
  return state.run({}, {}, {})


def _close(state):
  state.close()
  state._thread.join(5)


def test_bare_highland_model_fails_the_swap(joining):
  # the regression as it was on the comma: without lat_delay the swap is caught,
  # logged, and the small model drives on forever
  small = HighlandModel('small')
  log = Log()
  state = _joining_state(joining, small, BigModel(), log)
  try:
    # no modeld write first: on a7865fe modeld never wrote lat_delay
    deadline = time.monotonic() + 5
    while state._joined is None and time.monotonic() < deadline:
      time.sleep(0.002)
    state.in_control = False
    assert state.run({}, {}, {}) == {'from': 'small'}
    assert not state.chestnut
    assert any('could not bring up the large model' in text for _, text in log.lines), log.lines
  finally:
    _close(state)


def test_attach_swaps_onto_the_large_model(joining, monkeypatch):
  small = HighlandModel('small')
  big = BigModel()
  log = Log()
  api = SimpleNamespace(attach=lambda s, w, h: _joining_state(joining, s, big, log))
  monkeypatch.setattr(ja, '_api', lambda: api)
  ja.file_put('JetlinkLink', 2)

  state = ja.attach(small, small, 1344, 760)
  assert isinstance(state, joining.JoiningModelState)
  try:
    for name in (*ja.SMALL_MODEL_DEFAULTS, 'numpy_inputs'):
      assert hasattr(small, name), name
    assert small.numpy_inputs is small.npy
    assert state.run({}, {}, {}) == {'from': 'small'}  # engaged: the small model drives

    assert _swap(state, lat_delay=0.33) == {'from': 'big'}
    assert state.chestnut and ja.handed_over(state)
    assert big.lat_delay == pytest.approx(0.33)
    assert not [line for line in log.lines if line[0] in ('error', 'exception')], log.lines

    # what modeld and its UI read after the swap
    assert state.vision_input_names == ('img', 'big_img')
    assert state.lat_delay == pytest.approx(0.33)
    assert state.PLANPLUS_CONTROL == 1.0
    assert state.desire_key == 'desire_pulse'
    assert ja.state(state) == 'running'
    state.lat_delay = 0.4
    assert small.lat_delay == big.lat_delay == pytest.approx(0.4)
  finally:
    _close(state)


def test_fill_small_keeps_what_is_there_and_never_raises():
  small = HighlandModel('small')
  small.lat_delay = 0.25
  assert 'lat_delay' not in ja.fill_small(small)
  assert small.lat_delay == 0.25
  assert ja.fill_small(object()) == []  # cannot set attributes: logged, not raised
