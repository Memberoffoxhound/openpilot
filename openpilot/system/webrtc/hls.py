#!/usr/bin/env python3
from collections import deque
import struct
import threading
import time

from openpilot.cereal import messaging
from openpilot.common.params import Params

V4L2_BUF_FLAG_KEYFRAME = 0x8
TARGET_SEGMENT_S = 0.25
PLAYLIST_DEPTH = 2
HZ90 = 90_000
AUD = b"\x00\x00\x00\x01\x09\xf0"

CAMERAS = {
  "wide": "livestreamWideRoadEncodeData",
  "road": "livestreamNarrowRoadEncodeData",
  "driver": "livestreamCabinEncodeData",
}


def to_annexb(buf: bytes) -> bytes:
  if not buf:
    return buf
  if buf.startswith(b"\x00\x00\x00\x01") or buf.startswith(b"\x00\x00\x01"):
    return buf
  out = bytearray()
  i, nbuf = 0, len(buf)
  while i + 4 <= nbuf:
    n = int.from_bytes(buf[i:i + 4], "big")
    i += 4
    if n <= 0 or i + n > nbuf:
      break
    out += b"\x00\x00\x00\x01"
    out += buf[i:i + n]
    i += n
  return bytes(out) if out else buf


def _mpeg_crc32(data: bytes) -> int:
  crc = 0xFFFFFFFF
  for b in data:
    crc ^= b << 24
    for _ in range(8):
      if crc & 0x80000000:
        crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
      else:
        crc = (crc << 1) & 0xFFFFFFFF
  return crc


def _pcr_bytes(pts_90k: int) -> bytes:
  base = pts_90k & 0x1FFFFFFFF
  return bytes([
    (base >> 25) & 0xFF,
    (base >> 17) & 0xFF,
    (base >> 9) & 0xFF,
    (base >> 1) & 0xFF,
    ((base & 0x1) << 7) | 0x7E,
    0x00,
  ])


def _pes_h264(data: bytes, pts: int) -> bytes:
  pts &= 0x1FFFFFFFF
  # PTS-only: '0010' + PTS[32:30] + marker
  pts_hdr = bytes([
    0x20 | (((pts >> 30) & 0x7) << 1) | 1,
    (pts >> 22) & 0xFF,
    (((pts >> 15) & 0x7F) << 1) | 1,
    (pts >> 7) & 0xFF,
    ((pts & 0x7F) << 1) | 1,
  ])
  packet_len = 8 + len(data)
  len_bytes = b"\x00\x00" if packet_len > 0xFFFF else struct.pack(">H", packet_len)
  return b"\x00\x00\x01\xE0" + len_bytes + b"\x80\x80\x05" + pts_hdr + data


def _ts_packets(pid: int, payload: bytes, cc: list[int], *, start: bool, pcr: int | None = None) -> bytes:
  out = bytearray()
  i = 0
  n = len(payload)
  first = True
  while i < n or first:
    pusi = start and first
    extra = bytearray()
    if first and pcr is not None:
      extra += b"\x10" + _pcr_bytes(pcr)
    remaining = n - i
    if extra:
      min_body = len(extra)
      if remaining + 1 + min_body >= 184:
        af = bytes([min_body]) + extra
        take = 184 - len(af)
      else:
        stuff = 184 - remaining - 1 - min_body
        af = bytes([min_body + stuff]) + extra + (b"\xff" * stuff)
        take = remaining
    elif remaining >= 184:
      af = b""
      take = 184
    else:
      stuff_total = 184 - remaining
      if stuff_total == 1:
        af = b"\x00"
      else:
        af = bytes([stuff_total - 1, 0x00]) + (b"\xff" * (stuff_total - 2))
      take = remaining
    chunk = payload[i:i + take]
    afc = 0x10 if not af else (0x30 if chunk else 0x20)
    pkt = bytes([
      0x47,
      (0x40 if pusi else 0x00) | ((pid >> 8) & 0x1F),
      pid & 0xFF,
      afc | (cc[0] & 0xF),
    ]) + af + chunk
    if len(pkt) != 188:
      raise RuntimeError(f"bad ts packet {len(pkt)}")
    cc[0] = (cc[0] + 1) & 0xF
    out += pkt
    i += take
    first = False
    if n == 0:
      break
  return bytes(out)


def mux_h264_segment(frames: list[tuple[bytes, int]], cc: dict[str, list[int]]) -> bytes:
  def cc_of(pid: int) -> list[int]:
    return cc.setdefault(str(pid), [0])

  # PAT: program 1 → PMT PID 0x1000
  pat_section = bytes([
    0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,
    0x00, 0x01, 0xF0, 0x00,
  ])
  pat = bytes([0x00]) + pat_section + struct.pack(">I", _mpeg_crc32(pat_section))
  # PMT: PCR + H.264 on PID 0x100
  pmt_section = bytes([
    0x02, 0xB0, 0x12, 0x00, 0x01, 0xC1, 0x00, 0x00,
    0xE1, 0x00, 0xF0, 0x00,
    0x1B, 0xE1, 0x00, 0xF0, 0x00,
  ])
  pmt = bytes([0x00]) + pmt_section + struct.pack(">I", _mpeg_crc32(pmt_section))
  out = bytearray()
  out += _ts_packets(0, pat, cc_of(0), start=True)
  out += _ts_packets(0x1000, pmt, cc_of(0x1000), start=True)
  for data, pts in frames:
    au = data if data.startswith(AUD) else AUD + data
    out += _ts_packets(0x100, _pes_h264(au, pts), cc_of(0x100), start=True, pcr=pts)
  return bytes(out)


class _CamBuf:
  def __init__(self):
    self.lock = threading.Lock()
    self.segments: deque[tuple[int, float, bytes]] = deque(maxlen=PLAYLIST_DEPTH)
    self.seq = 0
    self.cur_frames: list[tuple[bytes, int]] = []
    self.cur_start_pts: int | None = None
    self.cc: dict[str, list[int]] = {}
    self.got_keyframe = False
    self.frames = 0

  def push(self, raw: bytes, pts_90k: int, keyframe: bool):
    if not self.got_keyframe and not keyframe:
      return
    self.got_keyframe = True
    annexb = to_annexb(raw)
    if not annexb:
      return
    dur = 0.0 if self.cur_start_pts is None else (pts_90k - self.cur_start_pts) / HZ90
    if self.cur_frames and keyframe and dur >= 0.22:
      self._flush()
    self.cur_frames.append((annexb, pts_90k))
    self.frames += 1
    if self.cur_start_pts is None:
      self.cur_start_pts = pts_90k
    elif (pts_90k - self.cur_start_pts) / HZ90 >= 0.6:
      self._flush()

  def _flush(self):
    if not self.cur_frames:
      self.cur_start_pts = None
      return
    start = self.cur_start_pts or self.cur_frames[0][1]
    dur = max(0.2, (self.cur_frames[-1][1] - start) / HZ90)
    ts = mux_h264_segment(self.cur_frames, self.cc)
    with self.lock:
      self.seq += 1
      self.segments.append((self.seq, dur, ts))
    self.cur_frames = []
    self.cur_start_pts = None

  def playlist(self, cam: str) -> str | None:
    with self.lock:
      segs = list(self.segments)
    if not segs:
      return None
    lines = [
      "#EXTM3U",
      "#EXT-X-VERSION:3",
      "#EXT-X-INDEPENDENT-SEGMENTS",
      "#EXT-X-TARGETDURATION:1",
      "#EXT-X-START:TIME-OFFSET=-0.25,PRECISE=YES",
      f"#EXT-X-MEDIA-SEQUENCE:{segs[0][0]}",
    ]
    for seq, dur, _ in segs:
      lines.append(f"#EXTINF:{max(dur, 0.2):.3f},")
      lines.append(f"{cam}/{seq}.ts")
    return "\n".join(lines) + "\n"

  def segment(self, seq: int) -> bytes | None:
    with self.lock:
      for s, _, data in self.segments:
        if s == seq:
          return data
    return None

  def seg_count(self) -> int:
    with self.lock:
      return len(self.segments)


class HlsHub:
  def __init__(self):
    self.cams = {name: _CamBuf() for name in CAMERAS}
    self._threads: list[threading.Thread] = []
    self._stop = threading.Event()
    self.last_access = 0.0
    self._started = False
    self._lock = threading.Lock()
    self._bytes = 0
    self._bytes_t = time.monotonic()
    self.kbps = 0
    self.clients: dict[str, float] = {}

  def note_client(self, ip: str):
    now = time.monotonic()
    self.clients[ip] = now
    dead = [k for k, t in self.clients.items() if now - t > 30]
    for k in dead:
      self.clients.pop(k, None)

  def client_count(self) -> int:
    now = time.monotonic()
    return sum(1 for t in self.clients.values() if now - t < 30)

  def seg_counts(self) -> dict[str, int]:
    return {name: cam.seg_count() for name, cam in self.cams.items()}

  def frame_counts(self) -> dict[str, int]:
    return {name: cam.frames for name, cam in self.cams.items()}

  def touch(self):
    self.last_access = time.monotonic()
    Params().put_bool("IsLiveStreaming", True)
    Params().put("LivestreamEncoderBitrate", 1_500_000)

  def ensure(self):
    self.touch()
    with self._lock:
      if self._started:
        return
      self._started = True
      self._stop.clear()
      self._threads = []
      for name, sock in CAMERAS.items():
        t = threading.Thread(target=self._reader, args=(name, sock), name=f"hls-{name}", daemon=True)
        t.start()
        self._threads.append(t)

  def idle(self, timeout: float = 60.0) -> bool:
    if self.last_access == 0.0:
      return True
    return (time.monotonic() - self.last_access) > timeout

  def stop(self):
    self._stop.set()
    with self._lock:
      self._started = False
      self._threads = []

  def _reader(self, name: str, sock_name: str):
    sock = messaging.sub_sock(sock_name, conflate=False)
    buf = self.cams[name]
    t0 = None
    last_pts = -1
    while not self._stop.is_set():
      msg = messaging.recv_one_or_none(sock)
      if msg is None:
        time.sleep(0.002)
        continue
      ev = getattr(msg, msg.which())
      raw = bytes(ev.header) + bytes(ev.data)
      idx = ev.idx
      ts = idx.timestampSof or idx.timestampEof or 0
      if t0 is None:
        t0 = ts
      if ts:
        pts = int((ts - t0) * 9 // 100_000)
      else:
        last_pts = last_pts + HZ90 // 20 if last_pts >= 0 else 0
        pts = last_pts
      last_pts = pts
      self._bytes += len(raw)
      now = time.monotonic()
      dt = now - self._bytes_t
      if dt >= 1.0:
        self.kbps = int(self._bytes * 8 / max(dt, 0.001) / 1000)
        self._bytes = 0
        self._bytes_t = now
      buf.push(raw, max(pts, 0), bool(idx.flags & V4L2_BUF_FLAG_KEYFRAME))
