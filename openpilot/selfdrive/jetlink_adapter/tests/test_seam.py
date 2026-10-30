"""Where jetlink meets Highland's stock modeld. Ported from zoompilot develop
(sunnypilot/jetlink_adapter/tests/test_seam.py), stock modeld only.

The hook lines are jetlink's check (testing.check_seam): prepare() before
modeld goes realtime, attach() once the small model is built, its result run,
frame_drop_ratio written and handed_over() read. And the joining model is held
to whatever the loop reads and writes on the model it runs: a read it cannot
answer is found here rather than on the frame thread of a drive. Both read
modeld rather than import it (that costs tinygrad and a vision stream).
"""
import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

MODELD = Path(__file__).resolve().parents[2] / 'modeld' / 'modeld.py'


def _main(src: str) -> ast.FunctionDef:
  return next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'main')


def _model_attributes(src: str) -> tuple[set[str], set[str]]:
  """What main() reads and writes on `model`, the model the loop runs."""
  loads, stores = set(), set()
  for n in ast.walk(_main(src)):
    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'model':
      (stores if isinstance(n.ctx, ast.Store) else loads).add(n.attr)
    elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'getattr' and len(n.args) >= 2
          and isinstance(n.args[0], ast.Name) and n.args[0].id == 'model' and isinstance(n.args[1], ast.Constant)):
      loads.add(n.args[1].value)
  return loads, stores


def test_the_hooks_are_where_jetlink_needs_them():
  testing = pytest.importorskip('jetlink.openpilot.testing')
  assert testing.check_seam(MODELD) == []


def test_the_joining_model_answers_every_read_and_takes_every_write():
  joining_mod = pytest.importorskip('jetlink.openpilot.joining')
  JoiningModelState = joining_mod.JoiningModelState
  loads, stores = _model_attributes(MODELD.read_text())
  assert 'run' in loads, "this no longer finds what the loop reads off the model"
  assert sorted(n for n in loads | stores if n.startswith('_')) == []
  for name in stores:
    prop = getattr(JoiningModelState, name, None)
    assert isinstance(prop, property) and prop.fset is not None, f"modeld writes model.{name}, which JoiningModelState keeps to itself"

  small = SimpleNamespace(**dict.fromkeys(loads, 0.0))
  stop = threading.Event()

  def connect(should_stop=None):
    stop.wait(5)
    raise ConnectionError("no link in this test")

  joining = JoiningModelState(small, connect, build=None, progress=mock.MagicMock(), log=mock.MagicMock())
  try:
    missing = []
    for name in sorted(loads):
      try:
        getattr(joining, name)
      except AttributeError:
        missing.append(name)
    assert missing == [], f"JoiningModelState cannot answer {missing}, which modeld reads"
  finally:
    stop.set()
    joining.close()
