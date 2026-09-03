"""Live camera telemetry, webrtcd proxy, and cabin-mic SSE."""
from __future__ import annotations

import base64
import json

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

_place_cache = {"key": None, "label": None}

def _place_label(lat, lon):
  if lat is None or lon is None:
    return None
  key = (round(float(lat), 3), round(float(lon), 3))
  if _place_cache["key"] == key and _place_cache["label"]:
    return _place_cache["label"]
  try:
    import urllib.request
    url = (
      "https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18&addressdetails=1"
      f"&lat={float(lat):.5f}&lon={float(lon):.5f}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "S3XYPilot/0.11.23"})
    with urllib.request.urlopen(req, timeout=5) as r:
      data = json.loads(r.read().decode())
    addr = data.get("address") or {}
    road = addr.get("road") or addr.get("pedestrian") or addr.get("residential") or addr.get("hamlet")
    city = (
      addr.get("city") or addr.get("town") or addr.get("village")
      or addr.get("hamlet") or addr.get("suburb") or addr.get("county")
    )
    iso = addr.get("ISO3166-2-lvl4") or ""
    st = iso.split("-")[-1] if "-" in iso else (addr.get("state_code") or "")
    if not st:
      raw = addr.get("state") or ""
      st = raw if len(raw) <= 12 else ""
      if not st:
        st = (addr.get("country_code") or "").upper()
    parts = [x for x in (road, city, st) if x]
    seen, uniq = set(), []
    for part in parts:
      k = part.lower()
      if k in seen:
        continue
      seen.add(k)
      uniq.append(part)
    label = ", ".join(uniq) if uniq else None
    if label:
      _place_cache["key"] = key
      _place_cache["label"] = label
      return label
  except Exception:
    pass
  return _place_cache.get("label")

WEBRTC_CAMERAS = ("road", "wideRoad", "driver")
_live_sm = None


def _params() -> Params:
  return Params()


def webrtc_up() -> bool:
  try:
    import requests
    return bool(requests.get("http://127.0.0.1:5001/schema", timeout=0.4).ok)
  except Exception:
    return False


def _smaster():
  global _live_sm
  if _live_sm is None:
    from openpilot.cereal import messaging
    _live_sm = messaging.SubMaster([
      "carState", "selfdriveState", "gpsLocation", "gpsLocationExternal",
    ])
  return _live_sm


def _gps_from(msg):
  lat = getattr(msg, "latitude", None)
  lon = getattr(msg, "longitude", None)
  bearing = getattr(msg, "bearingDeg", None)
  if lat is None and hasattr(msg, "positionGeodetic"):
    try:
      val = list(msg.positionGeodetic.value)
      lat, lon = float(val[0]), float(val[1])
    except Exception:
      lat = lon = None
  if lat is None or lon is None or abs(float(lat)) < 1e-4:
    return None
  return float(lat), float(lon), float(bearing or 0)


def live_state() -> dict:
  p = _params()
  out = {
    "speedMs": 0.0,
    "engaged": bool(p.get_bool("IsEngaged")),
    "metric": bool(p.get_bool("IsMetric")),
    "lat": None,
    "lon": None,
    "bearing": None,
    "livestream": bool(p.get_bool("IsLiveStreaming")),
    "webrtc": webrtc_up(),
    "mic": bool(p.get_bool("RecordAudio")),
    "tempC": None,
    "memPct": None,
    "cpuPct": None,
    "place": None,
  }
  try:
    import os
    vals = {}
    with open("/proc/meminfo") as f:
      for line in f:
        k, rest = line.split(":", 1)
        vals[k] = int(rest.strip().split()[0])
    total, avail = vals.get("MemTotal") or 0, vals.get("MemAvailable") or 0
    if total > 0:
      out["memPct"] = max(0, min(100, round(100.0 * (1.0 - avail / total))))
    temps = []
    for name in os.listdir("/sys/class/thermal"):
      if not name.startswith("thermal_zone"):
        continue
      base = "/sys/class/thermal/" + name
      try:
        kind = open(base + "/type").read().strip().lower()
        if "cpu" in kind:
          temps.append(int(open(base + "/temp").read().strip()) / 1000.0)
      except Exception:
        continue
    if temps:
      out["tempC"] = round(sum(temps) / len(temps))
  except Exception:
    pass
  try:
    sm = _smaster()
    sm.update(80)
    if sm.valid["carState"] or sm.updated["carState"]:
      out["speedMs"] = float(sm["carState"].vEgo)
    if sm.valid["selfdriveState"] or sm.updated["selfdriveState"]:
      ss = sm["selfdriveState"]
      out["engaged"] = bool(getattr(ss, "enabled", False) or getattr(ss, "active", False))
    for key in ("gpsLocationExternal", "gpsLocation"):
      if key not in sm.valid:
        continue
      if not (sm.valid[key] or sm.updated[key]):
        continue
      gps = _gps_from(sm[key])
      if gps:
        out["lat"], out["lon"], out["bearing"] = gps
        break
  except Exception:
    pass
  if out["lat"] is None:
    try:
      raw = (p.get("LastGPSPosition") or "")
      if isinstance(raw, bytes):
        raw = raw.decode()
      parts = [x.strip() for x in str(raw).split(",")]
      if len(parts) >= 2:
        lat, lon = float(parts[0]), float(parts[1])
        if abs(lat) > 1e-4:
          out["lat"], out["lon"] = lat, lon
    except Exception:
      pass
  if out.get("lat") is not None:
    out["place"] = _place_label(out["lat"], out["lon"])
  return out


def start_live() -> dict:
  p = _params()
  p.put_bool("IsLiveStreaming", True)
  try:
    from openpilot.system.webrtc.helpers import wait_for_webrtcd
    wait_for_webrtcd()
    return {"ok": True, "ready": True, "webrtc": True}
  except Exception as e:
    return {"ok": False, "ready": False, "webrtc": webrtc_up(), "error": str(e)}


def webrtc_stream(body: dict) -> dict:
  cams = [c for c in (body.get("cameras") or ["road"]) if c in WEBRTC_CAMERAS]
  if not cams:
    cams = ["road"]
  _params().put_bool("IsLiveStreaming", True)
  from openpilot.system.webrtc.helpers import StreamRequestBody, post_stream_request, wait_for_webrtcd
  wait_for_webrtcd()
  req = StreamRequestBody(
    sdp=str(body.get("sdp") or ""),
    cameras=cams,
    enabled=bool(body.get("enabled", True)),
    bridge_services_in=list(body.get("bridge_services_in") or []),
    bridge_services_out=list(body.get("bridge_services_out") or [
      "carState", "selfdriveState", "deviceState", "gpsLocation", "gpsLocationExternal",
    ]),
  )
  return post_stream_request(req)


def audio_sse(handler) -> None:
  from openpilot.cereal import messaging
  handler.send_response(200)
  handler._cors()
  handler.send_header("Content-Type", "text/event-stream")
  handler.send_header("Cache-Control", "no-cache")
  handler.send_header("Connection", "keep-alive")
  handler.send_header("X-Accel-Buffering", "no")
  handler.end_headers()
  sm = messaging.SubMaster(["rawAudioData"])
  try:
    while True:
      sm.update(250)
      if not (sm.updated.get("rawAudioData") or sm.valid.get("rawAudioData")):
        continue
      msg = sm["rawAudioData"]
      data = bytes(getattr(msg, "data", b"") or b"")
      if not data:
        continue
      rate = int(getattr(msg, "sampleRate", 0) or 16000)
      payload = json.dumps({"pcm": base64.b64encode(data).decode("ascii"), "rate": rate})
      handler.wfile.write(f"data: {payload}\n\n".encode())
      handler.wfile.flush()
  except (BrokenPipeError, ConnectionResetError, OSError):
    return
