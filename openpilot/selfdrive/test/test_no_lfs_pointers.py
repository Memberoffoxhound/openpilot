"""TeslaPilot: installable branches must work with no Git LFS fetch on the device."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.modeld import helpers

POINTER = b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'0' * 64 + b'\nsize 12345\n'


def _lfs():
  spec = importlib.util.spec_from_file_location('teslapilot_lfs', Path(BASEDIR) / 'scripts/teslapilot_lfs.py')
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def test_no_lfs_pointer_in_the_tree():
  # the only pointer allowed is the chestnut-only big model, and it is fetchexcluded
  assert _lfs().problems(Path(BASEDIR)) == []


def test_the_check_catches_a_pointer(tmp_path):
  lfs = _lfs()
  subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
  (tmp_path / 'wheel.png').write_bytes(POINTER)
  (tmp_path / 'real.png').write_bytes(b'\x89PNG real')
  subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
  errs = lfs.problems(tmp_path)
  assert any(e.startswith('wheel.png:') for e in errs)
  assert not any(e.startswith('real.png:') for e in errs)
  # the allowed big model must be fetchexcluded, else installs pull 776 MB
  assert any('fetchexclude' in e for e in errs)


@pytest.mark.parametrize('pointer_file', ['big_driving_tinygrad.pkl', 'big_driving_warp_1344x760_tinygrad.pkl',
                                          'big_driving_warp_1928x1208_tinygrad.pkl', None])
def test_chestnut_compiled_refuses_placeholders(tmp_path, monkeypatch, pointer_file):
  monkeypatch.setattr(helpers, 'MODELS_DIR', tmp_path)
  for name in ('big_driving_tinygrad.pkl', 'big_driving_warp_1344x760_tinygrad.pkl', 'big_driving_warp_1928x1208_tinygrad.pkl'):
    (tmp_path / name).write_bytes(POINTER if name == pointer_file else b'\x80\x04real pickle')
  assert helpers.chestnut_compiled() is (pointer_file is None)


def test_chestnut_compiled_false_on_this_checkout():
  # installs leave the big model a pointer, so no chestnut path ever loads it
  big = helpers.modeld_pkl_path(chestnut=True)
  if big.is_file() and big.read_bytes()[:len(POINTER) - 80].startswith(b'version https://git-lfs'):
    assert not helpers.chestnut_compiled()
