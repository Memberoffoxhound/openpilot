"""On-demand UI screen recorder. webgui writes REC_REQ (JSON) / REC_STOP; we pipe frames to ffmpeg.

Inert until a request file shows up: one stat() every POLL_S. Frames are taken at `fps` (not the
UI rate), queued, and written by a thread so a slow encoder drops frames instead of stalling the UI.
Hard stops: max duration, max size, low free space, ffmpeg death.
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time

DATA = os.getenv("WEBGUI_DATA", "/data")
REC_DIR = os.path.join(DATA, "media/0/screenrecords")
REC_REQ = os.path.join(DATA, "screenrec_request")
REC_STOP = os.path.join(DATA, "screenrec_stop")
REC_STATE = os.path.join(DATA, "screenrec_state")
POLL_S = 0.5
MAX_S = 300
MAX_BYTES = 400 * 1024 * 1024
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024

_encoder: str | None = None


def pick_encoder() -> str:
  # AGNOS ffmpeg 4.2 is built without --enable-gpl, so no libx264: fall back to native mpeg4
  global _encoder
  if _encoder is None:
    try:
      out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
      out = ""
    _encoder = "libx264" if " libx264 " in out else "mpeg4"
  return _encoder


def ffmpeg_args(w: int, h: int, fps: int, flip: bool, path: str, enc: str) -> list[str]:
  vf = ("vflip," if flip else "") + "format=yuv420p"
  codec = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"] if enc == "libx264" else ["-c:v", "mpeg4", "-q:v", "5"]
  return ["ffmpeg", "-v", "error", "-nostats", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps),
          "-i", "pipe:0", "-vf", vf, *codec, "-g", str(fps * 2), "-threads", "1",
          "-movflags", "frag_keyframe+empty_moov", "-flush_packets", "1", "-y", path]  # fragmented: playable if killed


def free_bytes(path: str) -> int:
  try:
    return shutil.disk_usage(path).free
  except OSError:
    return 0


class ScreenRecorder:
  def __init__(self, popen=subprocess.Popen, clock=time.monotonic, free=free_bytes):
    # clock is CLOCK_MONOTONIC: system-wide, so webgui can compare it against its own
    self._popen, self._clock, self._free = popen, clock, free
    self._next_poll = 0.0
    self._next_frame = 0.0
    self.active = False
    self.path = ""
    self.fps = 10
    self.max_s = 60
    self._t0 = 0.0
    self._started = 0.0
    self._frames = 0
    self._proc = None
    self._q: queue.Queue | None = None
    self._thread: threading.Thread | None = None
    self.error = ""

  # --- control (called once per UI frame, cheap) ---
  def tick(self) -> None:
    now = self._clock()
    if now < self._next_poll:
      return
    self._next_poll = now + POLL_S
    if os.path.exists(REC_STOP):
      _rm(REC_STOP)
      self.stop("requested")
    if not self.active and os.path.exists(REC_REQ):
      try:
        with open(REC_REQ) as f:
          req = json.load(f)
      except (OSError, ValueError):
        req = {}
      _rm(REC_REQ)
      self._start(req)
    if self.active:
      if now - self._t0 >= self.max_s:
        self.stop("max duration")
      elif self._size() >= MAX_BYTES:
        self.stop("max size")
      elif self._free(REC_DIR) < MIN_FREE_BYTES:
        self.stop("low storage")
      elif self._proc is not None and self._proc.poll() is not None:
        self.stop("encoder exited")
      else:
        self._write_state()

  def _start(self, req: dict) -> None:
    name = os.path.basename(str(req.get("name") or time.strftime("%Y-%m-%d--%H-%M-%S.mp4")))
    if not name.endswith(".mp4"):
      self.error = "bad name"
      return self._write_state()
    os.makedirs(REC_DIR, exist_ok=True)
    if self._free(REC_DIR) < MIN_FREE_BYTES:
      self.error = "low storage"
      return self._write_state()
    self.path = os.path.join(REC_DIR, name)
    self.fps = max(1, min(30, int(req.get("fps") or 10)))
    self.max_s = max(1, min(MAX_S, int(req.get("max_s") or 60)))
    self.active, self.error, self._frames = True, "", 0
    self._t0 = self._started = self._clock()
    self._next_frame = 0.0
    self._write_state()

  # --- frames ---
  def want_frame(self) -> bool:
    if not self.active:
      return False
    now = self._clock()
    if now < self._next_frame:
      return False
    self._next_frame = now + 1.0 / self.fps
    return True

  def push(self, data: bytes, w: int, h: int, flip: bool) -> None:
    if not self.active:
      return
    if self._proc is None:
      try:
        self._proc = self._popen(ffmpeg_args(w, h, self.fps, flip, self.path, pick_encoder()),
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 preexec_fn=lambda: os.nice(10))
      except Exception as e:
        self.error = f"ffmpeg: {e}"
        self.active = False
        return self._write_state()
      self._q = queue.Queue(maxsize=8)
      self._thread = threading.Thread(target=self._writer, args=(self._proc, self._q), daemon=True)
      self._thread.start()
    try:
      self._q.put_nowait(data)
      self._frames += 1
    except queue.Full:
      pass  # encoder behind: drop, never block the UI

  @staticmethod
  def _writer(proc, q: queue.Queue) -> None:
    while (data := q.get()) is not None:
      try:
        proc.stdin.write(data)
      except (BrokenPipeError, OSError, ValueError):
        return

  def stop(self, reason: str = "") -> None:
    if not self.active:
      return
    self.active = False
    self.error = "" if reason in ("", "requested") else reason
    proc, q, th = self._proc, self._q, self._thread
    self._proc = self._q = self._thread = None
    if q is not None:
      try:
        q.put(None, timeout=1)
      except queue.Full:
        pass
    if th is not None:
      th.join(timeout=2)
    if proc is not None:
      try:
        proc.stdin.close()
        proc.wait(timeout=5)
      except Exception:
        proc.kill()
    self._write_state()

  def _size(self) -> int:
    try:
      return os.path.getsize(self.path)
    except OSError:
      return 0

  def _write_state(self) -> None:
    st = {"recording": self.active, "name": os.path.basename(self.path), "started": self._started,
          "max_s": self.max_s, "fps": self.fps, "frames": self._frames, "error": self.error, "updated": self._clock()}
    tmp = REC_STATE + ".tmp"
    try:
      with open(tmp, "w") as f:
        json.dump(st, f)
      os.replace(tmp, REC_STATE)
    except OSError:
      pass


def _rm(path: str) -> None:
  try:
    os.remove(path)
  except OSError:
    pass
