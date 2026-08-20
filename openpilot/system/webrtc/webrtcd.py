#!/usr/bin/env python3

from abc import abstractmethod
from collections.abc import Callable
import os
import socket
import time
import capnp
import argparse
import asyncio
import contextlib
import json
import uuid
import logging
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from typing import Any

from openpilot.system.webrtc.helpers import StreamRequestBody, livestream_network_ok
from openpilot.system.webrtc.hls import CAMERAS as HLS_CAMERAS, HlsHub
from openpilot.system.webrtc.schema import generate_field
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.cereal import messaging, log

SESSION_TIMEOUT_SECONDS = 300
VIEWER_HTML = Path(__file__).with_name("viewer.html")
STATIC_DIR = Path(__file__).parent / "static"


# ice candidate parser for logging
def _ice_candidates(sdp: str) -> list[str]:
  return [line.removeprefix("a=") for line in sdp.splitlines() if line.startswith("a=candidate:")]

# socket trick: route lookup for 8.8.8.8 (nothing is sent or actually connected to)
# return the source interfaces IP which is the default interface of the device
def _default_route_ip() -> str | None:
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    s.connect(("8.8.8.8", 53))  # selects a route, sends nothing
    return s.getsockname()[0]
  except OSError:
    return None
  finally:
    s.close()

class AsyncTaskRunner:
  def __init__(self):
    self.task = None
    self.logger = logging.getLogger("webrtcd")

  def start(self):
    assert self.task is None
    self.task = asyncio.create_task(self.run())

  async def stop(self):
    if self.task is None:
      return
    task = self.task
    self.task = None
    if task.done():
      return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
      await task

  @abstractmethod
  async def run(self):
    pass


class CerealOutgoingMessageProxy(AsyncTaskRunner):
  def __init__(self, services: list[str], enabled: bool = True):
    super().__init__()
    self.services = list(services)
    self.sm = messaging.SubMaster(self.services)
    self.channels = []
    self._enabled = enabled

  def add_channel(self, channel):
    self.channels.append(channel)

  def enable(self, enable: bool):
    self._enabled = enable

  def to_json(self, msg_content: Any):
    if isinstance(msg_content, capnp._DynamicStructReader):
      msg_dict = msg_content.to_dict()
    elif isinstance(msg_content, capnp._DynamicListReader):
      msg_dict = [self.to_json(msg) for msg in msg_content]
    elif isinstance(msg_content, bytes):
      msg_dict = msg_content.decode()
    else:
      msg_dict = msg_content

    return msg_dict

  def update(self):
    # this is blocking in async context...
    self.sm.update(0)
    for service, updated in self.sm.updated.items():
      if not updated:
        continue
      msg_dict = self.to_json(self.sm[service])
      mono_time, valid = self.sm.logMonoTime[service], self.sm.valid[service]
      outgoing_msg = {"type": service, "logMonoTime": mono_time, "valid": valid, "data": msg_dict}
      encoded_msg = json.dumps(outgoing_msg).encode()
      for channel in self.channels:
        if not channel.is_open():
          continue
        channel.send(encoded_msg)

  async def run(self):
    while True:
      if not self._enabled:
        await asyncio.sleep(0.01)
        continue
      try:
        self.update()
      except Exception:
        self.logger.exception("Cereal outgoing proxy failure")
      await asyncio.sleep(0.01)


class CerealIncomingMessageProxy:
  def __init__(self, pm: messaging.PubMaster):
    self.pm = pm

  def send(self, message: bytes):
    msg_json = json.loads(message)
    msg_type, msg_data = msg_json["type"], msg_json["data"]
    size = None
    if not isinstance(msg_data, dict):
      size = len(msg_data)

    msg = messaging.new_message(msg_type, size=size)
    setattr(msg, msg_type, msg_data)
    self.pm.send(msg_type, msg)


class DynamicPubMaster(messaging.PubMaster):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.lock = asyncio.Lock()

  async def add_services_if_needed(self, services):
    async with self.lock:
      for service in services:
        if service not in self.sock:
          self.sock[service] = messaging.pub_sock(service)


class LivestreamBitrateController(AsyncTaskRunner):
  bitrates = [800_000, 1_200_000, int(os.environ.get("STREAM_BITRATE", 1_500_000))]
  label_to_bitrate = { "high": bitrates[2], "med": bitrates[1], "low": bitrates[0]}
  sample_interval = 0.2
  high_level = 0.1 # drop immediately
  med_level = 0.05 # drop after # of samples
  low_level = 0 # raise after # of samples
  down_samples = 5
  param_name = "LivestreamEncoderBitrate"

  def __init__(self, get_stats: Callable[[], dict[str, Any]], params: Params, enabled: bool = True):
    super().__init__()
    self.get_stats = get_stats
    self.params = params

    self.level = 2
    self._publish(self.bitrates[self.level])
    self.prev_stats: tuple[Any, ...] | None = None
    self.counter = 0
    self.up_samples = 5 # 1s
    self._auto = True
    self._enabled = enabled

  def enable(self, enable: bool):
    self._enabled = enable

  async def run(self):
    while True:
      await asyncio.sleep(self.sample_interval)
      if not self._enabled:
        continue
      if not self._auto:
        continue

      loss_rate = self._sample()
      if loss_rate is None:
        continue
      if loss_rate >= self.med_level and self.level > 0:
        self.counter += 1
        if self.counter >= self.down_samples or loss_rate >= self.high_level:
          self.level -= 1
          self.up_samples *= 2 # exponential backoff before raising again
          self.counter = 0
          self._publish(self.bitrates[self.level])
      elif loss_rate <= self.low_level and self.level < len(self.bitrates) - 1:
        self.counter -= 1
        if -self.counter >= self.up_samples:
          self.level += 1
          self.counter = 0
          self._publish(self.bitrates[self.level])

  def _sample(self) -> float | None:
    report = next(iter(self.get_stats().values()), None)
    if report is None:
      return None

    current = (report.ssrc, report.fraction_lost, report.packets_lost, report.highest_seq_no, report.jitter, report.lsr, report.dlsr)
    if self.prev_stats == current:
      return None
    self.prev_stats = current

    loss_rate = report.fraction_lost / 256
    return loss_rate

  def _publish(self, bitrate: float):
    self.params.put(self.param_name, bitrate)

  def set_quality(self, quality):
    if quality in self.label_to_bitrate:
      self._publish(self.label_to_bitrate[quality])
      self._auto = False
    elif quality == "auto":
      self._auto = True


class StreamSession:
  shared_pub_master = DynamicPubMaster([])

  def __init__(self, body: StreamRequestBody):
    from openpilot.system.webrtc.device.video import LiveStreamVideoStreamTrack
    from teleoprtc.builder import WebRTCAnswerBuilder

    self.identifier = str(uuid.uuid4())
    self.params = Params()
    # Highland: don't pin ICE to the current default-route IP. Binding to wifi
    # makes the peer connection die the instant the device switches to LTE onroad.
    builder = WebRTCAnswerBuilder(body.sdp, bind_address=None)

    self.enabled = body.enabled
    self.video_tracks = []
    for camera in body.cameras:
      track = LiveStreamVideoStreamTrack(camera, self.enabled)
      self.video_tracks.append(track)
      builder.add_video_stream(camera, track)
    self.stream = builder.stream()

    self.is_body = "testJoystick" in body.bridge_services_in

    self.incoming_bridge: CerealIncomingMessageProxy | None = None
    self.incoming_bridge_services = body.bridge_services_in
    self.outgoing_bridge: CerealOutgoingMessageProxy | None = None
    self.bitrate_controller: LivestreamBitrateController | None = None
    if len(body.bridge_services_in) > 0:
      self.incoming_bridge = CerealIncomingMessageProxy(self.shared_pub_master)
    if len(body.bridge_services_out) > 0:
      self.outgoing_bridge = CerealOutgoingMessageProxy(body.bridge_services_out, self.enabled)
    self.bitrate_controller = LivestreamBitrateController(self.stream.get_receiver_report_stats, self.params, self.enabled)

    self.run_task: asyncio.Task | None = None
    self._cleanup_lock = asyncio.Lock()
    self._cleanup_done = False
    self.logger = logging.getLogger("webrtcd")
    cloudlog.warning(
      "New stream session (%s), video cameras %s, video enabled %s, incoming services %s, outgoing services %s",
      self.identifier, [t.id for t in self.video_tracks], body.enabled, body.bridge_services_in, body.bridge_services_out,
    )

  def start(self):
    self.run_task = asyncio.create_task(self.run())

  async def stop(self):
    if self.run_task is not None and not self.run_task.done() and self.run_task is not asyncio.current_task():
      self.run_task.cancel()
      with contextlib.suppress(asyncio.CancelledError):
        await self.run_task
    self.run_task = None
    await self.post_run_cleanup()

  async def get_answer(self):
    return await self.stream.start()

  def message_handler(self, message: bytes):
    try:
      payload = json.loads(message) if isinstance(message, (bytes, str)) else None
      if isinstance(payload, dict):
        msg_type = payload.get("type")

        match msg_type:
          case "livestreamCameraSwitch":
            # only needed for 1 track stream
            if len(self.video_tracks) == 1:
              self.video_tracks[0].switch_camera(payload["data"]["camera"])
          case "livestreamSettings":
            if self.bitrate_controller is not None:
              self.bitrate_controller.set_quality(payload["data"]["quality"])
          case "livestreamVideoEnable":
            enabled = payload["data"]["enabled"]
            self.enabled = enabled
            for track in self.video_tracks:
              track.enable(enabled)
            if self.outgoing_bridge is not None:
              self.outgoing_bridge.enable(enabled)
            if self.bitrate_controller is not None:
              self.bitrate_controller.enable(enabled)
            if not enabled:
              self.params.put("LivestreamRequestKeyframe", True)
          case "clockSync":
            pong = json.dumps({"type": "clockSync", "data": {
              "action": "pong", "browserSendTime": payload["data"]["browserSendTime"], "deviceTime": time.time() * 1000, # noqa: TID251
            }})
            self.stream.get_messaging_channel().send(pong)
          case "enableTimingSei":
            for track in self.video_tracks:
              track.timing_sei_enabled = bool(payload["data"]["enabled"])
          case _:
            if msg_type not in self.incoming_bridge_services:
              return
            if self.incoming_bridge is not None:
              self.incoming_bridge.send(message)
    except Exception:
      self.logger.exception("Cereal incoming proxy failure")

  async def _watch_network(self):
    while True:
      await asyncio.sleep(2.0)
      reason = None
      if not livestream_network_ok(self.params):
        reason = "Livestream is limited to Wi-Fi or a non-Prime SIM."
      elif not self.params.get_bool("LivestreamEnabled") and not self.params.get_bool("IsOffroad"):
        reason = "On-Air is off."
      if reason is None:
        continue
      try:
        self.stream.get_messaging_channel().send(json.dumps({"type": "disconnect", "data": reason}))
      except Exception:
        pass
      await self.stream.stop()
      return

  async def run_normal_session(self):
    watch = asyncio.create_task(self._watch_network())
    try:
      await asyncio.wait_for(self.stream.wait_for_disconnection(), timeout=SESSION_TIMEOUT_SECONDS)
    except TimeoutError:
      self.logger.warning("Stream session (%s) timed out after %d s", self.identifier, SESSION_TIMEOUT_SECONDS)
      try:
        self.stream.get_messaging_channel().send(json.dumps({"type": "disconnect", "data": "Session timed out"}))
      except Exception:
        pass
    finally:
      watch.cancel()

  async def run_body_session(self):
    await self.stream.wait_for_disconnection()

  async def run(self):
    try:
      self.params.put("LivestreamRequestKeyframe", True)

      # avoid datachannel race by adding messange_handler immediately
      self.stream.set_message_handler(self.message_handler)

      await asyncio.wait_for(self.stream.wait_for_connection(), timeout=15)
      if self.stream.has_messaging_channel():
        if self.incoming_bridge is not None:
          await self.shared_pub_master.add_services_if_needed(self.incoming_bridge_services)
        if self.outgoing_bridge is not None:
          channel = self.stream.get_messaging_channel()
          self.outgoing_bridge.add_channel(channel)
          self.outgoing_bridge.start()
      if self.bitrate_controller is not None:
        self.bitrate_controller.start()

      with cloudlog.ctx(session_id=self.identifier):
        cloudlog.warning("webrtcd.session.connected")
      if self.is_body:
        await self.run_body_session()
      else:
        await self.run_normal_session()
      with cloudlog.ctx(session_id=self.identifier):
        cloudlog.warning("webrtcd.session.ended")
    except Exception:
      self.logger.exception("Stream session failure")
      with cloudlog.ctx(session_id=self.identifier):
        cloudlog.exception("webrtcd.session.exception")
    finally:
      await self.post_run_cleanup()

  async def post_run_cleanup(self):
    async with self._cleanup_lock:
      if self._cleanup_done:
        return
      self._cleanup_done = True
      self.params.put("LivestreamRequestKeyframe", False)
      if self.bitrate_controller is not None:
        await self.bitrate_controller.stop()
      if self.outgoing_bridge is not None:
        await self.outgoing_bridge.stop()
      for track in self.video_tracks:
        track.stop()
      self.video_tracks.clear()
      await self.stream.stop()


class ServerState:
  def __init__(self):
    self.streams: dict[str, StreamSession] = {}
    self.stream_lock = asyncio.Lock()
    self.teardown: asyncio.TimerHandle | None = None
    self.hls = HlsHub()
    self.loop: asyncio.AbstractEventLoop | None = None
    self.sm = messaging.SubMaster([
      "deviceState", "carState", "selfdriveState", "modelV2",
      "extrinsicsCalibration", "radarState", "gpsLocation", "gpsLocationExternal",
      "driverStateV2",
    ])
    self._gps_fix: tuple[float | None, float | None, float | None] = (None, None, None)
    try:
      self._gps_socks = [
        messaging.sub_sock("gpsLocation", conflate=True, timeout=0),
        messaging.sub_sock("gpsLocationExternal", conflate=True, timeout=0),
      ]
    except Exception:
      self._gps_socks = []
    self.trip_t0 = time.monotonic()
    self.trip_last = self.trip_t0
    self.trip_eng = 0.0
    self.trip_miles = 0.0
    self.hud: dict[str, Any] = {}
    self.hud_lock = threading.Lock()
    threading.Thread(target=self._pump, name="hud-pump", daemon=True).start()

  def _pump(self) -> None:
    while True:
      try:
        self.sm.update(50)
        self._poll_gps_socks()
        snap = self.build_hud()
        with self.hud_lock:
          self.hud = snap
      except Exception:
        time.sleep(0.15)

  def _poll_gps_socks(self) -> None:
    for sock in self._gps_socks:
      try:
        msg = messaging.recv_one_or_none(sock)
        if msg is None:
          continue
        g = getattr(msg, msg.which())
        lat, lon = float(g.latitude), float(g.longitude)
        if abs(lat) < 0.01 and abs(lon) < 0.01:
          continue
        hdg = float(getattr(g, "bearingDeg", 0.0) or 0.0) or None
        self._gps_fix = (lat, lon, hdg)
      except Exception:
        continue

  @staticmethod
  def _xyz(line, step: int = 4, cap: int = 24) -> list[list[float]]:
    try:
      xs, ys, zs = list(line.x), list(line.y), list(line.z)
    except Exception:
      return []
    pts = []
    for i in range(0, min(len(xs), len(ys), len(zs)), step):
      pts.append([float(xs[i]), float(ys[i]), float(zs[i])])
      if len(pts) >= cap:
        break
    return pts

  def _read_gps(self) -> tuple[float | None, float | None, float | None]:
    if self._gps_fix[0] is not None:
      return self._gps_fix
    sm = self.sm
    best: tuple[float | None, float | None, float | None] = (None, None, None)
    for name in ("gpsLocation", "gpsLocationExternal"):
      try:
        g = sm[name]
        lat, lon = float(getattr(g, "latitude", 0) or 0), float(getattr(g, "longitude", 0) or 0)
        if abs(lat) < 0.2 and abs(lon) < 0.2:
          continue
        hdg = float(getattr(g, "bearingDeg", 0.0) or 0.0) or None
        best = (lat, lon, hdg)
        if getattr(g, "hasFix", False) or abs(lat) > 1:
          self._gps_fix = best
          return best
      except Exception:
        continue
    if best[0] is None:
      try:
        raw = Params().get("LastGPSPosition")
        if raw:
          if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode(errors="ignore")
          lat = lon = None
          try:
            j = json.loads(raw)
            lat = float(j.get("latitude") or j.get("lat") or 0)
            lon = float(j.get("longitude") or j.get("lon") or 0)
          except Exception:
            parts = [p.strip() for p in raw.replace(";", ",").split(",")]
            if len(parts) >= 2:
              lat, lon = float(parts[0]), float(parts[1])
          if lat is not None and (abs(lat) > 0.2 or abs(lon) > 0.2):
            return lat, lon, None
      except Exception:
        pass
    return best

  def build_hud(self) -> dict[str, Any]:
    params = Params()
    sm = self.sm
    out: dict[str, Any] = {
      "onAir": params.get_bool("LivestreamEnabled"),
      "metric": params.get_bool("IsMetric"),
      "laneColor": 1,
      "enabled": False,
      "experimental": False,
      "speed": 0.0,
      "setSpeed": None,
      "steerDeg": 0.0,
      "alert": "",
      "rpy": [0.0, 0.0, 0.0],
      "wideRpy": [0.0, 0.0, 0.0],
      "height": 1.22,
      "path": [],
      "lanes": [],
      "edges": [],
      "laneProbs": [],
      "lead": None,
      "lat": None,
      "lon": None,
      "hdg": None,
      "faceYaw": 0.0,
      "facePitch": 0.0,
      "faceRoll": 0.0,
      "faceProb": 0.0,
      "blinkL": 0.0,
      "blinkR": 0.0,
      "tripMiles": round(self.trip_miles, 2),
      "engagedPct": 0.0,
    }
    try:
      lc = params.get("LaneColor") or 1
      out["laneColor"] = int(lc)
    except Exception:
      pass

    def got(name: str) -> bool:
      try:
        return bool(sm.seen.get(name) or sm.recv_frame.get(name, 0))
      except Exception:
        return False

    try:
      if got("carState"):
        cs = sm["carState"]
        v = cs.vEgoCluster if cs.vEgoCluster else cs.vEgo
        out["speed"] = float(v)
        out["steerDeg"] = float(cs.steeringAngleDeg)
        cruise = float(cs.vCruiseCluster or 0.0)
        if 0 < cruise < 255:
          out["setSpeed"] = cruise
      if got("selfdriveState"):
        ss = sm["selfdriveState"]
        out["enabled"] = bool(ss.enabled)
        out["experimental"] = bool(ss.experimentalMode)
        a1 = str(getattr(ss, "alertText1", "") or "")
        a2 = str(getattr(ss, "alertText2", "") or "")
        out["alert"] = a1 if a1 else a2
      if got("extrinsicsCalibration"):
        cal = sm["extrinsicsCalibration"]
        rpy = list(getattr(cal, "rpyCalib", []) or [])
        if len(rpy) == 3:
          out["rpy"] = [float(x) for x in rpy]
        wr = list(getattr(cal, "wideFromDeviceEuler", []) or [])
        if len(wr) == 3:
          out["wideRpy"] = [float(x) for x in wr]
        h = list(getattr(cal, "height", []) or [])
        if h:
          out["height"] = float(h[0])
      if got("modelV2"):
        m = sm["modelV2"]
        out["path"] = self._xyz(m.position)
        out["lanes"] = [self._xyz(ll) for ll in m.laneLines]
        out["edges"] = [self._xyz(e) for e in m.roadEdges]
        out["laneProbs"] = [float(p) for p in list(m.laneLineProbs)[:4]]
      if got("radarState"):
        lead = sm["radarState"].leadOne
        if lead and lead.present:
          out["lead"] = {"d": float(lead.dRel), "y": float(lead.yRel), "v": float(lead.vRel)}
      lat, lon, hdg = self._read_gps()
      out["lat"], out["lon"], out["hdg"] = lat, lon, hdg
      if got("driverStateV2"):
        ds = sm["driverStateV2"]
        left, right = ds.leftDriverData, ds.rightDriverData
        pick = left if float(left.faceProb or 0) >= float(right.faceProb or 0) else right
        ori = list(getattr(pick, "faceOrientation", []) or [])
        if len(ori) >= 3:
          out["facePitch"], out["faceYaw"], out["faceRoll"] = float(ori[0]), float(ori[1]), float(ori[2])
        out["faceProb"] = float(pick.faceProb or 0)
        out["blinkL"] = float(getattr(pick, "leftBlinkProb", 0) or 0)
        out["blinkR"] = float(getattr(pick, "rightBlinkProb", 0) or 0)
    except Exception:
      pass
    now = time.monotonic()
    dt = max(0.0, now - self.trip_last)
    self.trip_last = now
    self.trip_miles += abs(float(out["speed"] or 0.0)) * dt / 1609.344
    if out["enabled"]:
      self.trip_eng += dt
    total = max(now - self.trip_t0, 1e-3)
    out["tripMiles"] = round(self.trip_miles, 2)
    out["engagedPct"] = round(100.0 * self.trip_eng / total, 1)
    return out


def schedule_teardown(state: ServerState):
  loop = state.loop
  if loop is None:
    return

  def arm():
    if state.teardown is not None:
      state.teardown.cancel()

    def clear():
      if not state.streams and state.hls.idle():
        Params().put_bool("IsLiveStreaming", False)
        state.hls.stop()

    state.teardown = loop.call_later(60.0, clear)

  loop.call_soon_threadsafe(arm)


def _json_response(obj: Any, status: int = 200) -> tuple[int, bytes, str]:
  return (status, json.dumps(obj).encode(), "application/json; charset=utf-8")


def _text_response(text: str, status: int = 200) -> tuple[int, bytes, str]:
  return (status, text.encode(), "text/plain; charset=utf-8")


async def handle_get_stream(state: ServerState, raw_body: bytes, content_type: str) -> tuple[int, bytes, str]:
  if content_type != "application/json":
    return _json_response({"error": "unsupported media type"}, status=415)

  stream_dict = state.streams
  body = StreamRequestBody(**json.loads(raw_body))
  if not livestream_network_ok():
    return _json_response({"error": "wifi_or_byo_sim", "message": "Livestream is limited to Wi-Fi or a non-Prime SIM."})
  Params().put_bool("IsLiveStreaming", True)

  async with state.stream_lock:
    # don't remove existing connection on prewarm request
    enabled = any(s.run_task and not s.run_task.done() and s.enabled for s in stream_dict.values())
    if enabled and not body.enabled:
      return _json_response({"error": "busy", "message": "someone else is connected."})

    for sid, s in list(stream_dict.items()):
      if s.run_task and not s.run_task.done():
        try:
          ch = s.stream.get_messaging_channel()
          ch.send(json.dumps({"type": "disconnect", "data": "Another device has connected, closing this session."}))
        except Exception:
          pass
      await s.stop()
      stream_dict.pop(sid, None)

    session = StreamSession(body)
    stream_dict[session.identifier] = session
    try:
      answer = await asyncio.wait_for(session.get_answer(), timeout=30)
      cloudlog.event(
        "webrtcd.session.ice_candidates",
        session_id=session.identifier,
        offer_candidates=_ice_candidates(body.sdp),
        answer_candidates=_ice_candidates(answer.sdp),
      )
    except TimeoutError:
      await session.stop()
      stream_dict.pop(session.identifier, None)
      logging.getLogger("webrtcd").exception("Timed out creating stream answer")
      with cloudlog.ctx(session_id=session.identifier):
        cloudlog.warning("webrtcd.session.answer_timeout")
      raise
    except Exception:
      await session.stop()
      stream_dict.pop(session.identifier, None)
      logging.getLogger("webrtcd").exception("Failed to create stream answer")
      with cloudlog.ctx(session_id=session.identifier):
        cloudlog.exception("webrtcd.session.answer_exception")
      raise
    session.start()

    def remove_finished_session(_: asyncio.Task) -> None:
      stream_dict.pop(session.identifier, None)
      schedule_teardown(state)

    session.run_task.add_done_callback(remove_finished_session)

  return _json_response({"sdp": answer.sdp, "type": answer.type})


async def handle_get_schema(state: ServerState, services_param: str) -> tuple[int, bytes, str]:
  services = services_param.split(",")
  services = [s for s in services if s]
  assert all(s in log.Event.schema.fields and not s.endswith("DEPRECATED") for s in services), "Invalid service name"
  schema_dict = {s: generate_field(log.Event.schema.fields[s]) for s in services}
  return _json_response(schema_dict)


async def handle_post_notify(state: ServerState, payload: Any) -> tuple[int, bytes, str]:
  for session in list(state.streams.values()):
    try:
      ch = session.stream.get_messaging_channel()
      ch.send(json.dumps(payload))
    except Exception:
      continue

  return _text_response("OK")


async def on_shutdown(state: ServerState):
  for session in list(state.streams.values()):
    try:
      ch = session.stream.get_messaging_channel()
      ch.send(json.dumps({"type": "disconnect", "data": "device streaming has been stopped."}))
    except Exception:
      pass
    await session.stop()
  state.streams.clear()


class WebrtcdHandler(BaseHTTPRequestHandler):
  protocol_version = "HTTP/1.1"

  _routes = {
    "/": ("GET", "HEAD"),
    "/index.html": ("GET", "HEAD"),
    "/info": ("GET", "HEAD"),
    "/hud": ("GET", "HEAD"),
    "/watch": ("POST",),
    "/schema": ("GET", "HEAD"),
    "/stream": ("POST",),
    "/notify": ("POST",),
  }

  def _loopback(self) -> bool:
    return self.client_address[0] in ("127.0.0.1", "::1")

  def _on_lan(self) -> bool:
    if self._loopback():
      return True
    params = Params()
    return livestream_network_ok(params) and not params.get_bool("NetworkMetered")

  def _can_stream(self) -> bool:
    return self._on_lan() and Params().get_bool("LivestreamEnabled")

  def _lan_ok(self) -> bool:
    return self._can_stream()

  def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
    self.send_response(status)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.send_header("Access-Control-Allow-Origin", "*")
    if extra:
      for k, v in extra.items():
        self.send_header(k, v)
    self.end_headers()
    if self.command != "HEAD":
      self.wfile.write(body)

  def _read_body(self) -> bytes:
    length = int(self.headers.get("Content-Length", 0))
    return self.rfile.read(length) if length else b""

  def _run(self, coro) -> tuple[int, bytes, str]:
    return asyncio.run_coroutine_threadsafe(coro, self.server.loop).result()

  def _hls(self, path: str) -> tuple[int, bytes, str]:
    hub: HlsHub = self.server.state.hls
    hub.note_client(self.client_address[0])
    hub.ensure()
    schedule_teardown(self.server.state)
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[1].endswith(".m3u8"):
      cam = parts[1][:-5]
      if cam not in HLS_CAMERAS:
        return _json_response({"error": "not found"}, status=404)
      body = hub.cams[cam].playlist(cam)
      if not body:
        return (200, b"#EXTM3U\n#EXT-X-VERSION:3\n", "application/vnd.apple.mpegurl")
      return (200, body.encode(), "application/vnd.apple.mpegurl")
    if len(parts) == 3 and parts[2].endswith(".ts"):
      cam = parts[1]
      if cam not in HLS_CAMERAS:
        return _json_response({"error": "not found"}, status=404)
      try:
        seq = int(parts[2][:-3])
      except ValueError:
        return _json_response({"error": "not found"}, status=404)
      data = hub.cams[cam].segment(seq)
      if not data:
        return (404, b"", "video/mp2t")
      return (200, data, "video/mp2t")
    return _json_response({"error": "not found"}, status=404)

  def _static(self, path: str) -> tuple[int, bytes, str]:
    rel = path[len("/static/"):]
    if not rel or ".." in rel or rel.startswith("/"):
      return _json_response({"error": "not found"}, status=404)
    fp = (STATIC_DIR / rel).resolve()
    if not str(fp).startswith(str(STATIC_DIR.resolve())) or not fp.is_file():
      return _json_response({"error": "not found"}, status=404)
    ext = fp.suffix.lower()
    ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "application/octet-stream")
    return (200, fp.read_bytes(), ctype)

  def _snapshot(self) -> dict[str, Any]:
    hub: HlsHub = self.server.state.hls
    hub.note_client(self.client_address[0])
    params = Params()
    temp = mem = None
    strength = 0
    ntype = "none"
    try:
      sm = self.server.state.sm
      if sm.recv_frame.get("deviceState", 0) > 0:
        ds = sm["deviceState"]
        temps = list(getattr(ds, "cpuTempC", None) or [])
        if temps:
          temp = round(float(max(temps)), 1)
        mem = int(getattr(ds, "memoryUsagePercent", 0) or 0)
        ns = ds.networkStrength
        strength = int(getattr(ns, "raw", 0) or 0)
        ntype = str(ds.networkType).split(".")[-1]
    except Exception:
      pass
    on_air = params.get_bool("LivestreamEnabled")
    net_ok = livestream_network_ok(params)
    metered = params.get_bool("NetworkMetered")
    reason = None
    if not on_air:
      reason = "onair"
    elif not net_ok or metered:
      reason = "network"
    return {
      "ok": True,
      "onAir": on_air,
      "networkOk": net_ok,
      "metered": metered,
      "reason": reason,
      "hls": True,
      "kbps": hub.kbps,
      "viewers": hub.client_count(),
      "tempC": temp,
      "memPct": mem,
      "wifiBars": strength,
      "network": ntype,
      "hlsSegs": hub.seg_counts(),
      "hlsFrames": hub.frame_counts(),
    }

  def _xyz(self, line, step: int = 4, cap: int = 24) -> list[list[float]]:
    return ServerState._xyz(line, step, cap)

  def _hud_snapshot(self) -> dict[str, Any]:
    with self.server.state.hud_lock:
      snap = dict(self.server.state.hud)
    return snap or {"onAir": False, "lat": None, "lon": None, "tripMiles": 0, "engagedPct": 0}

  def _dispatch_request(self) -> None:
    parsed = urlparse(self.path)
    path = parsed.path
    try:
      if path in ("/", "/index.html"):
        html = VIEWER_HTML.read_bytes()
        result = (200, html, "text/html; charset=utf-8")
      elif path.startswith("/static/"):
        result = self._static(path)
      elif path == "/info":
        result = _json_response(self._snapshot())
      elif path == "/hud":
        result = _json_response(self._hud_snapshot())
      elif not self._can_stream() and path not in ("/schema",):
        result = (403, b"On-Air is off. Enable livestream in settings.", "text/plain; charset=utf-8")
      elif path == "/watch":
        if self.command != "POST":
          result = _json_response({"error": "method not allowed"}, status=405)
        else:
          self.server.state.hls.note_client(self.client_address[0])
          self.server.state.hls.ensure()
          schedule_teardown(self.server.state)
          result = _json_response({"ok": True})
      elif path.startswith("/hls/"):
        result = self._hls(path)
      else:
        allowed = self._routes.get(path)
        if allowed is None:
          result = _json_response({"error": "not found"}, status=404)
        elif self.command not in allowed:
          result = _json_response({"error": "method not allowed"}, status=405)
        elif path == "/schema":
          services = parse_qs(parsed.query).get("services", [""])[0]
          result = self._run(handle_get_schema(self.server.state, services))
        elif path == "/stream":
          result = self._run(handle_get_stream(self.server.state, self._read_body(), self.headers.get_content_type()))
        else:
          try:
            payload = json.loads(self._read_body())
          except Exception:
            result = _json_response({"error": "bad request"}, status=400)
          else:
            result = self._run(handle_post_notify(self.server.state, payload))
    except Exception as e:
      logging.getLogger("webrtcd").exception("Unhandled error handling %s", self.path)
      result = _json_response({"error": "exception", "message": f"{type(e).__name__}: {e}"}, status=500)

    self._send(*result)

  def do_GET(self) -> None:
    self._dispatch_request()

  def do_HEAD(self) -> None:
    self._dispatch_request()

  def do_POST(self) -> None:
    self._dispatch_request()

  def do_PUT(self) -> None:
    self._dispatch_request()

  def do_DELETE(self) -> None:
    self._dispatch_request()

  def do_PATCH(self) -> None:
    self._dispatch_request()

  def do_OPTIONS(self) -> None:
    self._dispatch_request()

  def log_message(self, format: str, *args: object) -> None:  # noqa: A002  # stdlib override
    # silence default access logging; errors are logged explicitly in _dispatch_request
    pass


class WebrtcdHTTPServer(ThreadingHTTPServer):
  daemon_threads = True
  allow_reuse_address = True
  state: ServerState
  loop: asyncio.AbstractEventLoop


async def _shutdown(server: WebrtcdHTTPServer, state: ServerState, loop: asyncio.AbstractEventLoop) -> None:
  # stop accepting new HTTP connections (blocks until serve_forever returns, so
  # run it off the loop) then tear down active stream sessions.
  await loop.run_in_executor(None, server.shutdown)
  await on_shutdown(state)
  loop.stop()


def prewarm_stream_session_imports() -> None:
  from openpilot.system.webrtc.device.video import LiveStreamVideoStreamTrack
  from teleoprtc.builder import WebRTCAnswerBuilder
  assert LiveStreamVideoStreamTrack
  assert WebRTCAnswerBuilder


def webrtcd_thread(host: str, port: int):
  logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
  prewarm_start = time.monotonic()
  prewarm_stream_session_imports()
  prewarm_end = time.monotonic()
  logging.getLogger("webrtcd").info(f"webrtc prewarm finished in {(prewarm_end - prewarm_start) * 1000} ms")

  loop = asyncio.new_event_loop()
  asyncio.set_event_loop(loop)
  state = ServerState()
  state.loop = loop

  server = WebrtcdHTTPServer((host, port), WebrtcdHandler)
  server.state = state
  server.loop = loop

  # serve HTTP on a daemon thread so the asyncio loop can own the main thread
  http_thread = threading.Thread(target=server.serve_forever, name="webrtcd-http", daemon=True)
  http_thread.start()

  shutting_down = False
  shutdown_task = None

  def request_shutdown() -> None:
    nonlocal shutting_down, shutdown_task
    if shutting_down:
      return
    shutting_down = True
    shutdown_task = loop.create_task(_shutdown(server, state, loop))

  for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, request_shutdown)

  try:
    loop.run_forever()
  finally:
    server.server_close()
    loop.close()


def main():
  parser = argparse.ArgumentParser(description="WebRTC daemon")
  parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to listen on")
  parser.add_argument("--port", type=int, default=5001, help="Port to listen on")
  args = parser.parse_args()

  webrtcd_thread(args.host, args.port)


if __name__=="__main__":
  main()
