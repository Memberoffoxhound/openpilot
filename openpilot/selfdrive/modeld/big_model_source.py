"""
The big driving model, for a chestnut build.

Ported from zoompilot develop (openpilot/sunnypilot/models/big_model_source.py,
93b6ca9, MIT, Zeph Leggett), moved under selfdrive/modeld since this fork has no
sunnypilot tree.

.lfsconfig leaves the big model out of every install fetch (fetchexclude): most
devices never run it and it is ~776 MB, the bulk of the LFS payload. A chestnut
build fetches that one object first. Until it has, the file is an LFS pointer and
chestnut_compiled() reads it as absent, so modeld never loads a pointer.
"""
import subprocess
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.modeld.helpers import modeld_pkl_path

BIG_PKL = modeld_pkl_path(chestnut=True)
LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'
FETCH_TIMEOUT = 3600


def is_lfs_pointer(path: Path) -> bool:
  try:
    with open(path, 'rb') as f:
      return f.read(len(LFS_POINTER)) == LFS_POINTER
  except OSError:
    return False


def ensure_big_pkl(path: Path = BIG_PKL, repo: str = BASEDIR) -> bool:
  """True once `path` is the model itself, fetching it if it is still a pointer.

  False, with the reason printed, when the fetch fails (offline, say): the
  build then goes on without the big model rather than failing whole, and the
  next build tries again.
  """
  if not is_lfs_pointer(path):
    return path.is_file()
  print(f"Fetching {path.name} for the chestnut; installs leave it out (.lfsconfig)", flush=True)
  try:
    # -X "" drops the fetchexclude for this one pull
    subprocess.run(['git', 'lfs', 'pull', '--include', str(path.relative_to(repo)), '--exclude', ''],
                   cwd=repo, check=True, timeout=FETCH_TIMEOUT)
  except (OSError, subprocess.SubprocessError) as e:
    print(f"Could not fetch {path.name}, skipping big model build: {e}", flush=True)
    return False
  if is_lfs_pointer(path):
    print(f"{path.name} is still an LFS pointer, skipping big model build", flush=True)
    return False
  return True
