"""The old trip layer (qlog cache, trip_stats.json, background jobs, TripMeter) is gone for good."""
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


def test_no_trip_files_or_jobs_left():
  root = PKG.parents[2]
  for f in root.rglob("*.py"):
    if "tests" in f.parts:
      continue
    src = f.read_text(errors="ignore")
    for word in ("trip_seed", "trip_stats", "trip_fold", "trip_overlay", "TripMeter", "spawn_trip_job"):
      assert word not in src, (f, word)
