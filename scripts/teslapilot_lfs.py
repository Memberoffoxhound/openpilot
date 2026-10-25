#!/usr/bin/env python3
"""TeslaPilot: installable branches carry no Git LFS objects.

  --check  (default) exit 1 if any tracked file is a Git LFS pointer, other than
           the chestnut-only big model, which must also be fetchexcluded in
           .lfsconfig. Checked-out submodules are scanned too.
  --fix    replace every disallowed pointer with its real file (git lfs pull from
           the .lfsconfig store) and stage it as a normal blob. Run after each
           comma merge, then commit.

A device install (comma installer `git clone`, updated's fetch) must work with no
LFS fetch at all: the 2026 headaches were pointers that could not be resolved and
LFS placeholders read as real assets.
"""
import argparse
import configparser
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POINTER = b'version https://git-lfs.github.com/spec/v1'
# pointer files allowed to stay: loaded only after chestnut_compiled() refuses pointers
ALLOWED = {
  'openpilot/selfdrive/modeld/models/big_driving_tinygrad.pkl',
}
SUBMODULES = ('opendbc_repo', 'panda', 'msgq_repo', 'rednose_repo', 'teleoprtc_repo', 'tinygrad_repo', 'jetlink_repo')


def is_pointer(path: Path) -> bool:
  try:
    with open(path, 'rb') as f:
      return f.read(len(POINTER)) == POINTER
  except OSError:
    return False


def pointers(repo: Path) -> list[str]:
  """Tracked files whose committed (index) blob is a pointer. Reads the blobs, not the
  working tree, so a checkout that smudged them still counts."""
  out = subprocess.run(['git', 'ls-files', '-s', '-z'], cwd=repo, capture_output=True, check=True).stdout.decode()
  entries = []
  for rec in filter(None, out.split('\0')):
    meta, path = rec.split('\t', 1)
    mode, sha, _ = meta.split()
    if mode in ('100644', '100755'):
      entries.append((sha, path))
  if not entries:
    return []
  checks = subprocess.run(['git', 'cat-file', '--batch-check=%(objectname) %(objectsize)'], cwd=repo, check=True,
                          input='\n'.join(sha for sha, _ in entries).encode(), capture_output=True).stdout.decode().splitlines()
  small = [(sha, path) for (sha, path), line in zip(entries, checks, strict=True) if int(line.split()[1]) < 1024]
  found = []
  for sha, path in small:
    blob = subprocess.run(['git', 'cat-file', 'blob', sha], cwd=repo, capture_output=True, check=True).stdout
    if blob.startswith(POINTER):
      found.append(path)
  return found


def fetchexcluded(repo: Path = ROOT) -> set[str]:
  cp = configparser.ConfigParser()
  try:
    cp.read(repo / '.lfsconfig')
    raw = cp.get('lfs', 'fetchexclude', fallback='')
  except configparser.Error:
    raw = ''
  return {x.strip() for x in raw.split(',') if x.strip()}


def problems(repo: Path = ROOT) -> list[str]:
  errs = []
  for p in pointers(repo):
    if p not in ALLOWED:
      errs.append(f'{p}: Git LFS pointer in an installable branch')
  missing = ALLOWED - fetchexcluded(repo)
  for p in sorted(missing):
    errs.append(f'{p}: allowed pointer but not in .lfsconfig fetchexclude (installs would fetch it)')
  for sm in SUBMODULES:
    d = repo / sm
    if (d / '.git').exists():
      errs += [f'{sm}/{p}: Git LFS pointer in submodule' for p in pointers(d)]
  return errs


def fix(repo: Path = ROOT) -> int:
  bad = [p for p in pointers(repo) if p not in ALLOWED]
  if not bad:
    return 0
  subprocess.run(['git', 'lfs', 'pull', '--include', ','.join(bad), '--exclude', ''], cwd=repo, check=True)
  still = [p for p in bad if is_pointer(repo / p)]
  if still:
    print('still pointers after pull (add an exemption line in .gitattributes?):', *still, sep='\n  ')
    return 1
  subprocess.run(['git', 'add', '--renormalize', '--', *bad], cwd=repo, check=True)
  print(f'replaced {len(bad)} pointer(s) with normal blobs; check .gitattributes exemptions, then commit')
  return 0


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('--fix', action='store_true')
  ap.add_argument('--check', action='store_true')
  args = ap.parse_args()
  if args.fix:
    return fix()
  errs = problems()
  for e in errs:
    print(e)
  print('LFS check:', 'FAIL' if errs else 'OK', f'({len(pointers(ROOT))} pointer(s) tracked, allowed: {sorted(ALLOWED)})')
  return 1 if errs else 0


if __name__ == '__main__':
  sys.exit(main())
