#!/usr/bin/env python3
from collections import deque
import struct
import threading
import time

from openpilot.cereal import messaging
from openpilot.common.params import Params

V4L2_BUF_FLAG_KEYFRAME = 0x8
TARGET_SEGMENT_S = 1.0
PLAYLIST_DEPTH = 5
HZ90 = 90_000

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
    if n < 0 or i + n > nbuf:
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
  pts_hdr = bytes([
    0x20 | 0x10 | (((pts >> 30) & 0x7) << 1) | 1,
    (pts >> 22) & 0xFF,
    (((pts >> 15) & 0x7F) << 1) | 1,
    (pts >> 7) & 0xFF,
    ((pts & 0x7F) << 1) | 1,
  ])
  packet_len = 8 + len(data)
  len_bytes = b"\x00\x00" if packet_len > 0xFFFF else struct.pack(">H", packet_len)
  return b"\x00\x00\x01\xE0" + len_bytes + b"\x80\x80\x05" + pts_hdr + data


def _ts_packets(pid: int, payload: bytes, cc: list[int], *, start: bool, pcr: int | None = None) -> bytes:
  """Pack payload into 188-byte TS packets. cc is a 1-int list mutated in place."""
  out = bytearray()
  i = 0
  first = True
  while i < len(payload) or first:
    pusi = start and first
    af_body = bytearray()
    if first and pcr is not None:
      af_body += b"\x10" + _pcr_bytes(pcr)
    remaining = len(payload) - i
    # bytes available for payload after 4-byte header and optional adaptation
    if af_body:
      # af = [len][body][possible stuffing]; need 184 - remaining stuffing if remaining < room
      min_af = 1 + len(af_body)  # length byte + body
      room_for_payload = 184 - min_af
      if remaining < room_for_payload:
        af_body += b"\xff" * (room_for_payload - remaining)
      adapt = bytes([len(af_body)]) + af_body
      chunk = payload[i:i + 184 - len(adapt)]
    else:
      if remaining < 184:
        # stuffing adaptation: length + (optional flags+stuff)
        stuff = 184 - remaining  # total adapt bytes including length
        if stuff == 1:
          adapt = b"\x00"
        else:
          adapt = bytes([stuff - 1]) + (b"\x00" + b"\xff" * (stuff - 2) if stuff > 1 else b"")
          if stuff == 2:
            adapt = b"\x01\x00"
          elif stuff > 2:
            adapt = bytes([stuff - 1, 0x00]) + (b"\xff" * (stuff - 2))
        chunk = payload[i:]
      else:
        adapt = b""
        chunk = payload[i:i + 184]
    afc = 0x10
    if adapt:
      afc = 0x30 if chunk else 0x20
    hdr = bytes([
      0x47,
      (0x40 if pusi else 0x00) | ((pid >> 8) & 0x1F),
      pid & 0xFF,
      afc | (cc[0] & 0xF),
    ])
    cc[0] = (cc[0] + 1) & 0xF
    pkt = hdr + adapt + chunk
    if len(pkt) != 188:
      pkt = (pkt + b"\xff" * 188)[:188]
    out += pkt
    i += len(chunk)
    first = False
    if not payload:
      break
  return bytes(out)


def mux_h264_segment(frames: list[tuple[bytes, int]], cc: dict[str, list[int]]) -> bytes:
  def cc_of(pid: int) -> list[int]:
    return cc.setdefault(str(pid), [0])

  pat_section = bytes([
    0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00,
    0x00, 0x01, 0xE1, 0x00,
  ])
  pat = bytes([0x00]) + pat_section + struct.pack(">I", _mpeg_crc32(pat_section))
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
    out += _ts_packets(0x100, _pes_h264(data, pts), cc_of(0x100), start=True, pcr=pts)
  return bytes(out)


class _CamBuf:
  def __init__(self):
    self.lock = threading.Lock()
    self.segments: deque[tuple[int, float, bytes]] = deque(maxlen=PLAYLIST_DEPTH)
    self.seq = 0
    self.cur_frames: list[tuple[bytes, int]] = []
    self.cur_start_pts: int | None = None
    self.cc: dict[str, list[int]] = {}

  def push(self, raw: bytes, pts_90k: int, keyframe: bool):
    annexb = to_annexb(raw)
    dur = 0.0 if self.cur_start_pts is None else (pts_90k - self.cur_start_pts) / HZ90
    if self.cur_frames and keyframe and dur >= 0.5:
      self._flush()
    self.cur_frames.append((annexb, pts_90k))
    if self.cur_start_pts is None:
      self.cur_start_pts = pts_90k
    elif (pts_90k - self.cur_start_pts) / HZ90 >= TARGET_SEGMENT_S * 2:
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
      "#EXT-X-TARGETDURATION:3",
      f"#EXT-X-MEDIA-SEQUENCE:{segs[0][0]}",
    ]
    for seq, dur, _ in segs:
      lines.append(f"#EXTINF:{max(dur, 0.2):.3f},")
      lines.append(f"/hls/{cam}/{seq}.ts")
    return "\n".join(lines) + "\n"

  def segment(self, seq: int) -> bytes | None:
    with self.lock:
      for s, _, data in self.segments:
        if s == seq:
          return data
    return None


class HlsHub:
  def __init__(self):
    self.cams = {name: _CamBuf() for name in CAMERAS}
    self._threads: list[threading.Thread] = []
    self._stop = threading.Event()
    self.last_access = 0.0
    self._started = False
    self._lock = threading.Lock()

  def touch(self):
    self.last_access = time.monotonic()
    Params().put_bool("IsLiveStreaming", True)

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
    sock = messaging.sub_sock(sock_name, conflate=True)
    buf = self.cams[name]
    t0 = None
    while not self._stop.is_set():
      msg = messaging.recv_one_or_none(sock)
      if msg is None:
        time.sleep(0.005)
        continue
      ev = getattr(msg, msg.which())
      raw = bytes(ev.header) + bytes(ev.data)
      idx = ev.idx
      ts = idx.timestampSof or idx.timestampEof or 0
      if t0 is None:
        t0 = ts
      pts = int((ts - t0) * 9 // 100_000)
      buf.push(raw, max(pts, 0), bool(idx.flags & V4L2_BUF_FLAG_KEYFRAME))
