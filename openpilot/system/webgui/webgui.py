#!/usr/bin/env python3
"""TeslaPilot device web GUI: stats, screenshots, UI screen recording. Stdlib only.

No auth (owner's call: single user). Binds 0.0.0.0:8089 (WEBGUI_HOST/WEBGUI_PORT), plain HTTP: anyone on the
same wifi/hotspot can use it. Read-only on car/controls; writes no params.
The UI process does the actual capture (system/ui/lib/screenshot.py, screenrec.py) via request files.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

STATIC = Path(__file__).parent / "static" / "index.html"
FONT_DIR = Path(__file__).parents[2] / "selfdrive/assets/fonts"
FONTS = ("TESLA.ttf", "Inter-SemiBold.ttf")  # wordmark only: TESLA in TESLA.ttf (as on the device home), PILOT in Inter
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MIN_FREE = 2 * 1024**3
MAX_REC_S = 300
STALE_S = 5.0
GRACE_S = 10.0
CSP = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; "
       + "media-src 'self'; connect-src 'self'; frame-ancestors 'none'")


def safe_file(d: Path, name: str, ext: str) -> Path | None:
  if not NAME_RE.match(name or "") or not name.endswith(ext) or ".." in name:
    return None
  f = d / name
  if f.is_symlink() or f.resolve().parent != d.resolve() or not f.is_file():
    return None
  return f


def list_files(d: Path, ext: str) -> list[dict]:
  try:
    fs = [f for f in d.iterdir() if f.suffix == ext and f.is_file() and not f.is_symlink()]
  except OSError:
    return []
  return [{"name": f.name, "size": f.stat().st_size, "mtime": int(f.stat().st_mtime)} for f in sorted(fs, key=lambda f: f.name, reverse=True)][:500]


class Recorder:
  """Server half of screen recording: guards + state. The UI half (screenrec.py) owns ffmpeg."""
  def __init__(self, data: Path, wall=time.monotonic, free=None):
    self.data, self.dir, self.wall = data, data / "media/0/screenrecords", wall
    self.free = free or (lambda p: shutil.disk_usage(p).free)
    self.req, self.stop_f, self.state_f = data / "screenrec_request", data / "screenrec_stop", data / "screenrec_state"

  @staticmethod
  def _json(f: Path) -> dict:
    try:
      return json.loads(f.read_text())
    except (OSError, ValueError):
      return {}

  def status(self) -> dict:
    st, now = self._json(self.state_f), self.wall()
    rec = bool(st.get("recording")) and now - float(st.get("updated") or 0) < STALE_S
    elapsed = max(0.0, now - float(st.get("started") or now)) if rec else 0.0
    if rec and elapsed > float(st.get("max_s") or MAX_REC_S) + GRACE_S:
      self.stop_f.write_text("watchdog")  # UI should have stopped itself; nudge it
    pending, err = self.req.exists(), st.get("error") or ""
    if pending and now - float(self._json(self.req).get("t") or 0) > STALE_S:
      self.req.unlink(missing_ok=True)
      pending, err = False, "UI did not pick up the request (is the ui process running?)"
    f = self.dir / (st.get("name") or "-")
    try:
      size = f.stat().st_size if rec else 0
    except OSError:
      size = 0
    try:
      free = self.free(str(self.data))
    except OSError:
      free = 0
    return {"recording": rec, "pending": pending, "name": st.get("name") if rec else None, "elapsed": round(elapsed, 1),
            "max_s": st.get("max_s"), "size": size, "free": free, "min_free": MIN_FREE, "error": err,
            "stale": bool(st.get("recording")) and not rec}

  def start(self, max_s, fps=10) -> tuple[int, dict]:
    s = self.status()
    if s["recording"] or s["pending"]:
      return 409, {"error": "already recording"}
    if s["free"] < MIN_FREE:
      return 507, {"error": f"need {MIN_FREE // 1024**3} GB free"}
    try:
      max_s, fps = max(5, min(MAX_REC_S, int(max_s))), max(1, min(30, int(fps)))
    except (TypeError, ValueError):
      return 400, {"error": "bad max_s/fps"}
    name = time.strftime("%Y-%m-%d--%H-%M-%S.mp4")
    self.stop_f.unlink(missing_ok=True)
    tmp = self.req.with_suffix(".tmp")
    tmp.write_text(json.dumps({"name": name, "max_s": max_s, "fps": fps, "t": self.wall()}))
    os.replace(tmp, self.req)
    return 200, {"ok": True, "name": name, "max_s": max_s}

  def stop(self) -> dict:
    self.req.unlink(missing_ok=True)
    self.stop_f.write_text("1")
    return {"ok": True}


class App:
  def __init__(self, data: Path, mock: bool = False, wall=time.monotonic, free=None):
    self.data, self.mock, self.wall = data, mock, wall
    self.shots, self.shot_req = data / "media/0/screenshots", data / "screenshot_request"
    self.rec = Recorder(data, wall, free)

  def stats(self) -> dict:
    from openpilot.system.webgui import stats
    return stats.mock() if self.mock else stats.collect(str(self.data))

  def set_timezone(self, name: str) -> tuple[int, dict]:
    if self.mock:
      return 200, {"ok": True, "mock": True}
    from openpilot.common.params import Params
    from openpilot.selfdrive.ui.tripstats import tz
    return (200, {"ok": True, "tz": name}) if tz.set_override(Params(), name) else (400, {"error": "unknown zone"})

  def capture(self, wait_s: float = 3.0) -> dict:
    self.shots.mkdir(parents=True, exist_ok=True)
    before = {f["name"] for f in list_files(self.shots, ".png")}
    self.shot_req.write_text("1")
    t = time.monotonic() + wait_s
    while time.monotonic() < t:
      new = [f["name"] for f in list_files(self.shots, ".png") if f["name"] not in before]
      if new:
        return {"ok": True, "name": new[0]}
      time.sleep(0.15)
    return {"ok": True, "pending": True}  # screen may be off; UI takes it on next rendered frame

  def delete(self, kind: str, name: str) -> tuple[int, dict]:
    d, ext = (self.shots, ".png") if kind == "shots" else (self.rec.dir, ".mp4")
    f = safe_file(d, name, ext)
    if f is None:
      return 404, {"error": "not found"}
    if kind == "recs" and self.rec.status()["name"] == name:
      return 409, {"error": "recording in progress"}
    f.unlink()
    return 200, {"ok": True}


class Handler(BaseHTTPRequestHandler):
  server_version = "TeslaPilotGUI"
  protocol_version = "HTTP/1.1"
  app: App

  def log_message(self, fmt, *args):
    pass

  def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
    self.send_response(code)
    for k, v in {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                 "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                 **(extra or {})}.items():
      self.send_header(k, v)
    self.end_headers()
    if self.command != "HEAD":
      self.wfile.write(body)

  def _json(self, code: int, obj, extra=None):
    self._send(code, json.dumps(obj).encode(), "application/json", extra)

  def _body(self) -> dict:
    n = int(self.headers.get("Content-Length") or 0)
    if not 0 < n <= 4096:
      return {}
    try:
      return json.loads(self.rfile.read(n))
    except ValueError:
      return {}

  def _route(self) -> tuple[str, list[str]]:
    path = unquote(urlparse(self.path).path)
    return path, [p for p in path.split("/") if p]

  def do_GET(self):
    path, parts = self._route()
    a = self.app
    if path in ("/", "/index.html"):
      return self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8", {"Content-Security-Policy": CSP})
    if len(parts) == 2 and parts[0] == "font" and parts[1] in FONTS:
      return self._send(200, (FONT_DIR / parts[1]).read_bytes(), "font/ttf", {"Cache-Control": "public, max-age=86400"})
    if path == "/api/stats":
      return self._json(200, a.stats())
    if path == "/api/shots":
      return self._json(200, {"items": list_files(a.shots, ".png")})
    if path == "/api/rec":
      return self._json(200, {**a.rec.status(), "items": list_files(a.rec.dir, ".mp4")})
    if len(parts) == 3 and parts[0] == "media" and parts[1] in ("shots", "recs"):
      d, ext, ctype = (a.shots, ".png", "image/png") if parts[1] == "shots" else (a.rec.dir, ".mp4", "video/mp4")
      f = safe_file(d, parts[2], ext)
      return self._file(f, ctype) if f else self._json(404, {"error": "not found"})
    self._json(404, {"error": "not found"})

  do_HEAD = do_GET

  def _file(self, f: Path, ctype: str):
    size = f.stat().st_size
    dl = {"Content-Disposition": f'{"attachment" if "dl=1" in self.path else "inline"}; filename="{f.name}"',
          "Accept-Ranges": "bytes", "Cache-Control": "private, max-age=60"}
    m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
    lo, hi, code = 0, size - 1, 200
    if m and size and (m.group(1) or m.group(2)):
      lo, hi = (int(m.group(1)), int(m.group(2) or size - 1)) if m.group(1) else (max(0, size - int(m.group(2))), size - 1)
      hi = min(hi, size - 1)
      if lo > hi:
        return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
      code, dl["Content-Range"] = 206, f"bytes {lo}-{hi}/{size}"
    self.send_response(code)
    for k, v in {"Content-Type": ctype, "Content-Length": str(hi - lo + 1), "X-Content-Type-Options": "nosniff", **dl}.items():
      self.send_header(k, v)
    self.end_headers()
    if self.command == "HEAD":
      return
    with open(f, "rb") as fh:
      fh.seek(lo)
      left = hi - lo + 1
      while left > 0 and (chunk := fh.read(min(65536, left))):
        self.wfile.write(chunk)
        left -= len(chunk)

  def do_POST(self):
    path, _ = self._route()
    if not (self.headers.get("Content-Type") or "").startswith("application/json"):
      return self._json(415, {"error": "json only"})  # not auth: forces a CORS preflight, so other sites can't POST here
    a, body = self.app, self._body()
    if path == "/api/shots":
      return self._json(200, a.capture())
    if path == "/api/rec/start":
      return self._json(*a.rec.start(body.get("max_s", 60), body.get("fps", 10)))
    if path == "/api/rec/stop":
      return self._json(200, a.rec.stop())
    if path == "/api/timezone":
      return self._json(*a.set_timezone(str(body.get("tz") or "")))
    self._json(404, {"error": "not found"})

  def do_DELETE(self):
    path, parts = self._route()
    if len(parts) == 3 and parts[:2] in (["api", "shots"], ["api", "recs"]):
      return self._json(*self.app.delete(parts[1], parts[2]))
    self._json(404, {"error": "not found"})


def make_server(app: App, host: str, port: int) -> ThreadingHTTPServer:
  Handler.app = app
  srv = ThreadingHTTPServer((host, port), Handler)
  srv.daemon_threads = True
  return srv


def serve(app: App, host: str, port: int, retry_s: float = 5.0) -> ThreadingHTTPServer:
  while True:  # port busy (old instance in TIME_WAIT is fine: allow_reuse_address) -> wait, don't die
    try:
      return make_server(app, host, port)
    except OSError as e:
      print(f"webgui: bind {host}:{port} failed ({e}), retrying", flush=True)
      time.sleep(retry_s)


def main():
  data = Path(os.getenv("WEBGUI_DATA", "/data"))
  host, port = os.getenv("WEBGUI_HOST", "0.0.0.0"), int(os.getenv("WEBGUI_PORT", "8089"))
  app = App(data, mock=os.getenv("WEBGUI_MOCK") == "1")
  for d in (app.shots, app.rec.dir):
    try:
      d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
      print(f"webgui: can't create {d} ({e})", flush=True)
  srv = serve(app, host, port)
  print(f"webgui on http://{host}:{port}  (no auth, LAN-visible, plain HTTP)", flush=True)
  srv.serve_forever()


if __name__ == "__main__":
  main()
