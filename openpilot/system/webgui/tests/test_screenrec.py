import json
import importlib

import pytest

GB = 1024**3


class FakeProc:
  def __init__(self, args, **kw):
    self.args, self.kw, self.written, self.rc = args, kw, [], None
    self.stdin = self

  def write(self, b):
    self.written.append(b)

  def close(self):
    self.rc = 0

  def poll(self):
    return self.rc

  def wait(self, timeout=None):
    return 0

  def kill(self):
    self.rc = -9


@pytest.fixture
def R(tmp_path, monkeypatch):
  monkeypatch.setenv("WEBGUI_DATA", str(tmp_path))
  import openpilot.system.ui.lib.screenrec as m
  m = importlib.reload(m)
  m._encoder = "mpeg4"
  t, free, procs = [0.0], [50 * GB], []

  def popen(args, **kw):
    procs.append(FakeProc(args, **kw))
    return procs[-1]
  rec = m.ScreenRecorder(popen=popen, clock=lambda: t[0], free=lambda p: free[0])
  return m, rec, t, free, procs


def step(rec, t, dt):
  t[0] += dt
  rec.tick()


def request(m, **kw):
  with open(m.REC_REQ, "w") as f:
    json.dump({"name": "r.mp4", "max_s": 10, "fps": 5} | kw, f)


def state(m):
  return json.load(open(m.REC_STATE))


def test_idle_is_inert(R):
  m, rec, t, _, procs = R
  for _ in range(10):
    step(rec, t, 0.6)
    assert not rec.want_frame()
  assert procs == []


def test_start_frames_stop(R):
  m, rec, t, _, procs = R
  request(m)
  step(rec, t, 1)
  assert rec.active and state(m)["recording"]
  assert rec.want_frame() and not rec.want_frame()  # rate limited to fps
  rec.push(b"\0" * 16, 2, 2, flip=True)
  p = procs[0]
  assert p.args[0] == "ffmpeg" and "vflip,format=yuv420p" in p.args and p.args[-1].endswith("screenrecords/r.mp4")
  assert "frag_keyframe+empty_moov" in p.args
  open(m.REC_STOP, "w").write("1")
  step(rec, t, 1)
  assert not rec.active and not state(m)["recording"] and state(m)["error"] == ""


def test_hard_max_duration(R):
  m, rec, t, _, _ = R
  request(m, max_s=10)
  step(rec, t, 1)
  step(rec, t, 9.9)
  assert rec.active
  step(rec, t, 0.6)
  assert not rec.active and state(m)["error"] == "max duration"


def test_clamps_and_rejects_bad_name(R):
  m, rec, t, _, _ = R
  request(m, max_s=99999, fps=500, name="../../etc/x.mp4")
  step(rec, t, 1)
  assert rec.max_s == m.MAX_S and rec.fps == 30 and rec.path == m.REC_DIR + "/x.mp4"
  rec.stop()
  request(m, name="x.sh")
  step(rec, t, 1)
  assert not rec.active and state(m)["error"] == "bad name"


def test_free_space_guard(R):
  m, rec, t, free, _ = R
  free[0] = m.MIN_FREE_BYTES - 1
  request(m)
  step(rec, t, 1)
  assert not rec.active and state(m)["error"] == "low storage"
  free[0] = 50 * GB
  request(m)
  step(rec, t, 1)
  assert rec.active
  free[0] = 1
  step(rec, t, 1)
  assert not rec.active and state(m)["error"] == "low storage"


def test_encoder_death_stops(R):
  m, rec, t, _, procs = R
  request(m)
  step(rec, t, 1)
  rec.push(b"\0" * 16, 2, 2, flip=False)
  procs[0].rc = 1
  step(rec, t, 1)
  assert not rec.active and state(m)["error"] == "encoder exited"


def test_full_queue_drops_not_blocks(R):
  m, rec, t, _, procs = R
  request(m)
  step(rec, t, 1)
  import threading
  gate = threading.Event()
  orig = FakeProc.write
  FakeProc.write = lambda self, b: gate.wait(2)
  try:
    for _ in range(50):
      rec.push(b"\0" * 16, 2, 2, flip=False)  # must return immediately
  finally:
    gate.set()
    FakeProc.write = orig
  assert 0 < rec._frames < 50  # the queue filled and the rest were dropped
  rec.stop()
