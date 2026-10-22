"""
jetlink from this checkout's jetlink_repo, ahead of anything installed, for
every test: the path a device gets from the jetlink link launch_chffrplus.sh
makes. Ported from zoompilot develop (conftest.py:12-18).
"""
import sys
from pathlib import Path

JETLINK_REPO = str(Path(__file__).resolve().parent / 'jetlink_repo')
if JETLINK_REPO in sys.path:
  sys.path.remove(JETLINK_REPO)
sys.path.insert(0, JETLINK_REPO)
