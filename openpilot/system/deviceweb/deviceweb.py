#!/usr/bin/env python3
"""LAN UI for S3XYPilot. No auth — bind on the local network only."""
from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.deviceweb import liveapi
from openpilot.system.deviceweb.sysinfo import cpu_pct, cpu_temp_c, mem_pct

PORT = int(os.environ.get("DEVICEWEB_PORT", "8088"))
VERSION = "0.11.23"
STATIC_DIR = Path(__file__).parent / "static"
OPENPILOT_DIR = Path(os.environ.get("OPENPILOT_PATH", "/data/openpilot"))
FONT_PATH = OPENPILOT_DIR / "openpilot/selfdrive/assets/fonts/TESLA.ttf"
SHOT_DIR = Path("/data/media/0/screenshots")
SHOT_REQ = Path("/data/screenshot_request")
SHOT_PLAY = Path("/data/screenshot_play")
NO_STORE = {
  "index.html", "app.js", "app.css", "live.js", "live.css",
  "live-map.js", "live-route.js", "vslam-readout.js", "vslam-readout.css",
}

_info_sm = None


def _params() -> Params:
  return Params()


def _smaster():
  global _info_sm
  if _info_sm is None:
    from openpilot.cereal import messaging
    _info_sm = messaging.SubMaster(["deviceState"])
  return _info_sm


def _info() -> dict:
  p = _params()
  tesla = p.get("LaneColor", return_default=True) == 1
  info = {
    "name": "S3XYPilot",
    "version": p.get("Version") or VERSION,
    "branch": p.get("GitBranch") or "Highland",
    "commit": p.get("GitCommit") or "",
    "dongle": p.get("DongleId") or "",
    "offroad": p.get_bool("IsOffroad"),
    "engaged": p.get_bool("IsEngaged"),
    "theme": "tesla" if tesla else "openpilot",
    "accent": [62, 140, 235] if tesla else [0, 255, 64],
    "tempC": cpu_temp_c(),
    "cpuPct": cpu_pct(),
    "memPct": mem_pct(),
    "diskFreeGb": None,
    "diskTotalGb": None,
  }
  try:
    sm = _smaster()
    sm.update(80)
    if sm.updated["deviceState"] or sm.valid["deviceState"]:
      ds = sm["deviceState"]
      temps = list(ds.cpuTempC) if ds.cpuTempC else []
      if temps:
        info["tempC"] = round(sum(temps) / len(temps))
      try:
        info["memPct"] = int(ds.memoryUsagePercent)
      except Exception:
        pass
      cores = list(ds.cpuUsagePercent) if ds.cpuUsagePercent else []
      if cores:
        info["cpuPct"] = max(0, min(100, round(sum(cores) / len(cores))))
  except Exception:
    pass
  try:
    st = os.statvfs("/data")
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    info["diskTotalGb"] = round(total / 1e9, 1)
    info["diskFreeGb"] = round(free / 1e9, 1)
  except OSError:
    pass
  return info


def _stats_payload() -> dict:
  try:
    from openpilot.selfdrive.ui.layouts.settings.trip_stats import stats_view
    view = stats_view()
  except Exception:
    view = {}
  return view


def _home() -> dict:
  p = _params()
  metric = bool(p.get_bool("IsMetric"))
  view = _stats_payload()
  return {
    "info": _info(),
    "metric": metric,
    "unit": "km" if metric else "mi",
    "stats": view,
  }


def _list_shots() -> list[dict]:
  if not SHOT_DIR.is_dir():
    return []
  items = []
  for f in sorted(SHOT_DIR.iterdir(), key=lambda p: p.name, reverse=True):
    if f.suffix.lower() != ".png" or not f.is_file():
      continue
    try:
      st = f.stat()
    except OSError:
      continue
    items.append({"name": f.name, "size": st.st_size, "mtime": int(st.st_mtime)})
  return items[:250]


def _shot_name(raw: str) -> str | None:
  name = Path(str(raw or "")).name
  if not name.endswith(".png"):
    return None
  return name


def _delete_shots(names: list) -> dict:
  deleted: list[str] = []
  for raw in names:
    name = _shot_name(raw)
    if not name:
      continue
    target = SHOT_DIR / name
    if not target.is_file():
      continue
    try:
      target.unlink()
      deleted.append(name)
    except OSError:
      pass
  return {"ok": True, "deleted": deleted}


def _request_shot() -> dict:
  SHOT_DIR.mkdir(parents=True, exist_ok=True)
  SHOT_REQ.write_text("1")
  try:
    SHOT_PLAY.write_text("1")
  except OSError:
    pass
  return {"ok": True}


def _decorate_vslam(ev: dict, samples=None) -> dict:
  try:
    from openpilot.selfdrive.vslam.classify import annotate
    annotate(ev, samples or [])
  except Exception:
    ev.setdefault("path", ev.get("kind") or "unknown")
    ev.setdefault("filter", "hold")
    ev.setdefault("headline", "Not enough path \u2014 hold")
    ev.setdefault("summary", "Classifier unavailable on this build.")
  return ev


def _vslam_list() -> dict:
  from openpilot.selfdrive.vslam.store import (
    compact_spark, is_enabled, is_filter_enabled, load_events, load_trace, op_long_active,
  )
  p = _params()
  events = list(reversed(load_events(200)))
  for ev in events[:50]:
    samples = []
    need = (not ev.get("spark")) or (not ev.get("headline"))
    if need:
      samples = (load_trace(str(ev.get("id") or "")).get("samples") or [])
    if not ev.get("spark"):
      ev["spark"] = compact_spark(samples)
    _decorate_vslam(ev, samples)
  return {
    "enabled": is_enabled(p),
    "filter_enabled": is_filter_enabled(p),
    "op_long": op_long_active(p),
    "filter_ui": False,  # observe-only until a planner consumer exists
    "events": events,
    "count": len(events),
  }


def _vslam_event(eid: str) -> dict:
  from openpilot.selfdrive.vslam.store import load_events, load_trace
  eid = Path(str(eid or "")).name
  if not eid:
    return {"error": "missing id"}
  ev = next((e for e in load_events(400) if e.get("id") == eid), None)
  if ev is None:
    return {"error": "not found", "id": eid}
  trace = load_trace(eid)
  _decorate_vslam(ev, trace.get("samples") or [])
  return {"event": ev, "trace": trace}


def _vslam_set(on: bool) -> dict:
  from openpilot.selfdrive.vslam.store import is_enabled, set_enabled
  p = _params()
  set_enabled(bool(on), p)
  return {"ok": True, "enabled": is_enabled(p)}


def _vslam_set_filter(on: bool) -> dict:
  from openpilot.selfdrive.vslam.store import is_filter_enabled, op_long_active, set_filter_enabled
  p = _params()
  armed = set_filter_enabled(bool(on), p)
  return {
    "ok": True,
    "filter_enabled": is_filter_enabled(p),
    "armed": bool(armed),
    "op_long": op_long_active(p),
  }


class Handler(BaseHTTPRequestHandler):
  server_version = f"S3XYPilot/{VERSION}"
  protocol_version = "HTTP/1.1"

  def log_message(self, fmt: str, *args) -> None:
    cloudlog.info("deviceweb " + (fmt % args))

  def _cors(self) -> None:
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.send_header("Cache-Control", "no-store")

  def do_OPTIONS(self) -> None:
    self.send_response(204)
    self._cors()
    self.end_headers()

  def _json(self, code: int, obj) -> None:
    raw = json.dumps(obj).encode()
    self.send_response(code)
    self._cors()
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(raw)))
    self.end_headers()
    self.wfile.write(raw)

  def _read_json(self) -> dict:
    n = int(self.headers.get("Content-Length") or 0)
    if n <= 0 or n > 1_000_000:
      return {}
    return json.loads(self.rfile.read(n).decode() or "{}")

  def _bytes(self, data: bytes, ctype: str, cache: str = "no-store") -> None:
    self.send_response(200)
    self._cors()
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", cache)
    self.end_headers()
    self.wfile.write(data)

  def _fail(self, where: str) -> None:
    cloudlog.exception(f"deviceweb {where}")
    self._json(500, {"error": "internal"})

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    qs = parse_qs(parsed.query)
    try:
      if path in ("/api/home", "/api/device/home"):
        return self._json(200, _home())
      if path in ("/api/stats", "/api/device/stats"):
        return self._json(200, {"stats": _stats_payload(), "info": _info()})
      if path in ("/api/live", "/api/device/live"):
        return self._json(200, liveapi.live_state())
      if path in ("/api/audio", "/api/device/audio"):
        return liveapi.audio_sse(self)
      if path in ("/api/vslam", "/api/device/vslam"):
        return self._json(200, _vslam_list())
      if path in ("/api/vslam/event", "/api/device/vslam/event"):
        payload = _vslam_event((qs.get("id") or [""])[0])
        return self._json(404 if payload.get("error") else 200, payload)
      if path in ("/api/screenshots", "/api/device/screenshots"):
        return self._json(200, {"items": _list_shots()})
      if path in ("/api/screenshots/raw", "/api/device/screenshots/raw"):
        name = _shot_name((qs.get("name") or [""])[0])
        target = SHOT_DIR / name if name else None
        if target is None or not target.is_file():
          return self._json(404, {"error": "not found"})
        data = target.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)
        return
      if path in ("/font/TESLA.ttf", "/api/font"):
        if not FONT_PATH.is_file():
          return self._json(404, {"error": "font missing"})
        return self._bytes(FONT_PATH.read_bytes(), "font/ttf", "public, max-age=86400")
      return self._static(path)
    except Exception:
      self._fail("GET")

  def do_DELETE(self) -> None:
    # Screenshot delete is POST /api/screenshots/delete only.
    self._json(404, {"error": "not found"})

  def do_POST(self) -> None:
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    try:
      if path in ("/api/live/start", "/api/device/live/start"):
        return self._json(200, liveapi.start_live())
      if path in ("/api/webrtc/stream", "/api/device/webrtc/stream"):
        try:
          return self._json(200, liveapi.webrtc_stream(self._read_json()))
        except Exception as e:
          cloudlog.exception("deviceweb webrtc")
          return self._json(502, {"error": type(e).__name__, "message": str(e)})
      if path in ("/api/vslam/enabled", "/api/device/vslam/enabled"):
        body = self._read_json()
        on = body.get("enabled")
        if on is None:
          on = body.get("on")
        return self._json(200, _vslam_set(bool(on)))
      if path in ("/api/vslam/filter", "/api/device/vslam/filter"):
        body = self._read_json()
        on = body.get("filter_enabled")
        if on is None:
          on = body.get("enabled")
        if on is None:
          on = body.get("on")
        return self._json(200, _vslam_set_filter(bool(on)))
      if path in ("/api/screenshots/capture", "/api/device/screenshots/capture"):
        return self._json(200, _request_shot())
      if path in ("/api/screenshots/delete", "/api/device/screenshots/delete"):
        names = self._read_json().get("names") or []
        if isinstance(names, str):
          names = [names]
        return self._json(200, _delete_shots(list(names)))
      self._json(404, {"error": "not found"})
    except Exception:
      self._fail("POST")

  def _static(self, path: str) -> None:
    rel = path.lstrip("/")
    if not rel or rel == "console":
      rel = "index.html"
    candidate = (STATIC_DIR / rel).resolve()
    try:
      candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
      return self._json(403, {"error": "denied"})
    if candidate.is_dir():
      candidate = candidate / "index.html"
    if not candidate.is_file():
      candidate = STATIC_DIR / "index.html"
    data = candidate.read_bytes()
    ctype = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    if candidate.suffix == ".webmanifest":
      ctype = "application/manifest+json"
    cache = "no-store" if candidate.name in NO_STORE else "public, max-age=3600"
    self._bytes(data, ctype, cache)


def main() -> None:
  httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
  cloudlog.warning(f"deviceweb listening on 0.0.0.0:{PORT}")
  try:
    httpd.serve_forever()
  finally:
    httpd.server_close()


if __name__ == "__main__":
  main()
