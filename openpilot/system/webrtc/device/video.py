import asyncio
from dataclasses import dataclass
import struct
import time

from teleoprtc.tracks import TiciVideoStreamTrack

from openpilot.cereal import messaging
from openpilot.common.realtime import DT_MDL
from openpilot.common.params import Params


# v4l2 buffer flag marking an encoded keyframe (linux/videodev2.h)
V4L2_BUF_FLAG_KEYFRAME = 0x8

# arbitrary 16-byte UUID identifying openpilot frame-timing SEI messages
TIMING_SEI_UUID = bytes([
  0xa5, 0xe0, 0xc4, 0xa4, 0x5b, 0x6e, 0x4e, 0x1e,
  0x9c, 0x7e, 0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc,
])
_SEI_PREFIX = b'\x00\x00\x00\x01\x06\x05\x30' + TIMING_SEI_UUID

# Prefer the producer that is already running. Onroad that is encoderd
# (qcam H264 + HEVC mains). Offroad that is stream_encoderd livestream*.
# Never start a second encoder just to feed WebRTC.
_ONROAD_SOCKS = {
  "driver": ("cabinEncodeData", "driverEncodeData", "livestreamCabinEncodeData"),
  "wideRoad": ("wideRoadEncodeData", "livestreamWideRoadEncodeData"),
  "road": ("qNarrowRoadEncodeData", "roadEncodeData", "livestreamNarrowRoadEncodeData"),
}
_OFFROAD_SOCKS = {
  "driver": ("livestreamCabinEncodeData", "cabinEncodeData", "driverEncodeData"),
  "wideRoad": ("livestreamWideRoadEncodeData", "wideRoadEncodeData"),
  "road": ("livestreamNarrowRoadEncodeData", "qNarrowRoadEncodeData", "roadEncodeData"),
}
_STALE_S = 1.0


@dataclass(frozen=True)
class EncodedVideoFrame:
  data: bytes
  pts: int

  def __bytes__(self) -> bytes:
    return self.data


class LiveStreamVideoStreamTrack(TiciVideoStreamTrack):
  def __init__(self, camera_type: str, video_enabled: bool = True):
    super().__init__(camera_type, DT_MDL)

    self._camera_type = camera_type
    self._pts = 0
    self._t0_ns = time.monotonic_ns()
    self.timing_sei_enabled = False
    self.params = Params()
    self._seen_keyframe = False
    self.video_enabled = video_enabled
    self._offroad = self.params.get_bool("IsOffroad")
    self._candidates = self._candidate_names(camera_type, self._offroad)
    self._cand_i = 0
    self._sock_name = self._candidates[0]
    self._sock = messaging.sub_sock(self._sock_name, conflate=True)
    self._last_frame_mono = time.monotonic()

  def stop(self) -> None:
    super().stop()
    self._sock = None

  def _candidate_names(self, camera_type: str, offroad: bool) -> tuple[str, ...]:
    table = _OFFROAD_SOCKS if offroad else _ONROAD_SOCKS
    return table[camera_type]

  def _bind(self, name: str) -> None:
    self._sock_name = name
    self._sock = messaging.sub_sock(name, conflate=True)
    self._seen_keyframe = False
    self._last_frame_mono = time.monotonic()

  def _resync_producer(self) -> None:
    offroad = self.params.get_bool("IsOffroad")
    names = self._candidate_names(self._camera_type, offroad)
    if offroad != self._offroad or names != self._candidates:
      self._offroad = offroad
      self._candidates = names
      self._cand_i = 0
      self._bind(names[0])
      return
    if (time.monotonic() - self._last_frame_mono) < _STALE_S:
      return
    if len(self._candidates) < 2:
      return
    self._cand_i = (self._cand_i + 1) % len(self._candidates)
    self._bind(self._candidates[self._cand_i])

  def switch_camera(self, camera_type: str) -> None:
    self._camera_type = camera_type
    self._offroad = self.params.get_bool("IsOffroad")
    self._candidates = self._candidate_names(camera_type, self._offroad)
    self._cand_i = 0
    self._bind(self._candidates[0])

  def enable(self, enabled: bool):
    self.video_enabled = enabled
    if not enabled:
      self._seen_keyframe = False

  def request_keyframe(self) -> None:
    self.params.put("LivestreamRequestKeyframe", True, block=False)

  def _build_frame_data(self, msg) -> bytes:
    encode_data = getattr(msg, msg.which())
    if not self.timing_sei_enabled:
      return encode_data.header + encode_data.data

    idx = encode_data.idx
    sei_nal = _SEI_PREFIX + struct.pack('>4d',
      (idx.timestampEof - idx.timestampSof) / 1e6,
      (msg.logMonoTime - idx.timestampEof) / 1e6,
      (time.monotonic_ns() - msg.logMonoTime) / 1e6,
      time.time() * 1000,  # noqa: TID251
    ) + b'\x80'
    return encode_data.header + sei_nal + encode_data.data

  async def recv(self):
    while True:
      if not self.video_enabled:
        await asyncio.sleep(0.005)
        continue

      self._resync_producer()
      msg = messaging.recv_one_or_none(self._sock) if self._sock is not None else None
      if msg is not None:
        if not self._seen_keyframe and (getattr(msg, msg.which()).idx.flags & V4L2_BUF_FLAG_KEYFRAME):
          self._seen_keyframe = True
          self.params.put("LivestreamRequestKeyframe", False, block=False)
        self._last_frame_mono = time.monotonic()
        break
      await asyncio.sleep(0.005)

    self._pts = ((time.monotonic_ns() - self._t0_ns) * self._clock_rate) // 1_000_000_000
    self.log_debug("track sending frame %d from %s", self._pts, self._sock_name)

    return EncodedVideoFrame(self._build_frame_data(msg), self._pts)
