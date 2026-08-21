#!/usr/bin/env python3
"""LAN device console for DELAMAIN. No auth — bind on the local network only."""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import subprocess
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

PORT = int(os.environ.get("DEVICEWEB_PORT", "8088"))
STATIC_DIR = Path(__file__).parent / "static"
OPENPILOT_DIR = Path(os.environ.get("OPENPILOT_PATH", "/data/openpilot"))

FILE_ROOTS = (
  "/data/media/0",
  "/data/params/d",
  "/data/log",
  "/data/openpilot",
)
SECRET_NAMES = {
  "AccessToken", "GithubSshKeys", "SecOCKey", "AssistNowToken", "ApiCache_Device",
}
WRITE_BOOL = {
  "OpenpilotEnabledToggle", "ExperimentalMode", "AutoLaneChangeEnabled", "IsLdwEnabled",
  "AlwaysOnDM", "IsMetric", "DisengageOnAccelerator", "RecordFront", "RecordAudio",
  "LivestreamEnabled", "SshEnabled", "AdbEnabled", "DisablePowerDown", "DisableUpdates",
  "GsmRoaming", "GsmMetered", "NetworkMetered", "ShowDebugInfo", "JoystickDebugMode",
}
WRITE_INT = {"LaneColor", "LongitudinalPersonality"}
READ_KEYS = sorted(WRITE_BOOL | WRITE_INT | {
  "DongleId", "Version", "GitBranch", "GitCommit", "GitRemote", "HardwareSerial",
  "IsOffroad", "IsEngaged", "UpdateAvailable", "UpdaterState", "UpdaterCurrentDescription",
  "UpdaterNewDescription", "UpdaterTargetBranch", "SshEnabled",
})
MAX_DOWNLOAD = 80 * 1024 * 1024


def _params() -> Params:
  return Params()


def _safe_file(raw: str) -> Path | None:
  if not raw:
    return None
  path = Path(posixpath.normpath(unquote(raw)))
  if ".." in path.parts:
    return None
  text = str(path)
  if not any(text == root or text.startswith(root + "/") for root in FILE_ROOTS):
    return None
  if path.name in SECRET_NAMES:
    return None
  try:
    resolved = path.resolve()
  except OSError:
    return None
  allowed = False
  for root in FILE_ROOTS:
    try:
      resolved.relative_to(Path(root).resolve())
      allowed = True
      break
    except (ValueError, OSError):
      continue
  return resolved if allowed else None


def _git(*args: str) -> str:
  return subprocess.check_output(["git", "-C", str(OPENPILOT_DIR), *args], text=True, timeout=45).strip()


def _info() -> dict:
  p = _params()
  info = {
    "name": "DELAMAIN",
    "version": p.get("Version") or "0.11.2.1",
    "branch": p.get("GitBranch") or "Highland",
    "commit": p.get("GitCommit") or "",
    "remote": p.get("GitRemote") or "",
    "dongle": p.get("DongleId") or "",
    "serial": p.get("HardwareSerial") or "",
    "offroad": p.get_bool("IsOffroad"),
    "engaged": p.get_bool("IsEngaged"),
    "onAir": p.get_bool("LivestreamEnabled"),
    "tempC": None,
    "memPct": None,
    "diskFreeGb": None,
    "diskTotalGb": None,
    "network": "unknown",
    "wifiBars": 0,
    "updateAvailable": p.get_bool("UpdateAvailable"),
    "updaterState": p.get("UpdaterState") or "idle",
    "updaterNotes": p.get("UpdaterCurrentDescription") or p.get("UpdaterNewDescription") or "",
  }
  try:
    from openpilot.cereal import messaging, log
    sm = messaging.SubMaster(["deviceState"])
    sm.update(0)
    if sm.updated["deviceState"] or sm.valid["deviceState"]:
      ds = sm["deviceState"]
      temps = list(ds.cpuTempC) if ds.cpuTempC else []
      if temps:
        info["tempC"] = round(sum(temps) / len(temps))
      info["memPct"] = int(ds.memoryUsagePercent)
      nt = int(ds.networkType)
      names = {0: "none", 1: "wifi", 2: "cell2g", 3: "cell3g", 4: "cell4g", 5: "cell5g"}
      info["network"] = names.get(nt, "net")
      info["wifiBars"] = int(getattr(ds, "wifiIpAddress", None) and 3 or 0)
      try:
        info["wifiBars"] = int(ds.networkStrength)
      except Exception:
        pass
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


def _list_dir(raw: str) -> list[dict]:
  if not raw:
    return [{"name": Path(r).name or r, "path": r, "dir": True, "size": 0} for r in FILE_ROOTS]
  path = _safe_file(raw)
  if path is None or not path.is_dir():
    raise FileNotFoundError(raw)
  out = []
  with os.scandir(path) as it:
    for ent in it:
      if ent.name in SECRET_NAMES or ent.name.startswith("."):
        continue
      try:
        st = ent.stat(follow_symlinks=False)
      except OSError:
        continue
      child = str(path / ent.name)
      out.append({
        "name": ent.name,
        "path": child,
        "dir": ent.is_dir(follow_symlinks=False),
        "size": 0 if ent.is_dir(follow_symlinks=False) else st.st_size,
        "mtime": int(st.st_mtime * 1000),
      })
  out.sort(key=lambda x: (not x["dir"], x["name"].lower()))
  return out


def _read_params() -> dict[str, str]:
  p = _params()
  out: dict[str, str] = {}
  for k in READ_KEYS:
    if k in SECRET_NAMES:
      continue
    try:
      if k in WRITE_BOOL:
        out[k] = "1" if p.get_bool(k) else "0"
      else:
        v = p.get(k)
        out[k] = "" if v is None else str(v)
    except Exception:
      out[k] = ""
  return out


def _write_params(body: dict) -> None:
  p = _params()
  for k, v in body.items():
    if k in SECRET_NAMES:
      continue
    if k in WRITE_BOOL:
      p.put_bool(k, str(v) in ("1", "true", "True", "yes"), block=True)
    elif k in WRITE_INT:
      p.put(k, str(int(v)), block=True)


def _check_updates() -> dict:
  p = _params()
  branch = p.get("GitBranch") or "Highland"
  try:
    _git("fetch", "origin", branch)
    head = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", f"origin/{branch}")
    available = head != remote
    p.put_bool("UpdateAvailable", available, block=True)
    return {"ok": True, "available": available, "head": head, "remote": remote, "branch": branch}
  except Exception as e:
    return {"ok": False, "error": str(e)}


def _apply_update() -> dict:
  p = _params()
  if not p.get_bool("IsOffroad"):
    return {"ok": False, "error": "Go offroad first."}
  branch = p.get("GitBranch") or "Highland"
  try:
    _git("fetch", "origin", branch)
    _git("reset", "--hard", f"origin/{branch}")
    p.put_bool("DoReboot", True, block=True)
    return {"ok": True, "rebooting": True}
  except Exception as e:
    return {"ok": False, "error": str(e)}


class Handler(BaseHTTPRequestHandler):
  server_version = "DELAMAIN/0.11.2.1"

  def log_message(self, fmt: str, *args) -> None:
    cloudlog.info("deviceweb " + (fmt % args))

  def _cors(self) -> None:
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
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

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    qs = parse_qs(parsed.query)
    try:
      if path in ("/api/info", "/api/device/info"):
        return self._json(200, _info())
      if path in ("/api/params", "/api/device/params"):
        return self._json(200, _read_params())
      if path in ("/api/files", "/api/device/files"):
        target = (qs.get("path") or [""])[0]
        return self._json(200, {"path": target, "items": _list_dir(target)})
      if path in ("/api/files/raw", "/api/device/files/raw"):
        target = _safe_file((qs.get("path") or [""])[0])
        if target is None or not target.is_file():
          return self._json(404, {"error": "not found"})
        size = target.stat().st_size
        if size > MAX_DOWNLOAD:
          return self._json(413, {"error": "file too large"})
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)
        return
      if path in ("/api/updates", "/api/device/updates"):
        return self._json(200, _info())
      return self._static(path)
    except FileNotFoundError:
      self._json(404, {"error": "not found"})
    except Exception:
      cloudlog.exception("deviceweb GET")
      self._json(500, {"error": traceback.format_exc().splitlines()[-1]})

  def do_PUT(self) -> None:
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    try:
      if path in ("/api/params", "/api/device/params"):
        _write_params(self._read_json())
        return self._json(200, _read_params())
      self._json(404, {"error": "not found"})
    except Exception:
      cloudlog.exception("deviceweb PUT")
      self._json(500, {"error": traceback.format_exc().splitlines()[-1]})

  def do_POST(self) -> None:
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    p = _params()
    try:
      if path in ("/api/updates/check", "/api/device/updates/check"):
        return self._json(200, _check_updates())
      if path in ("/api/updates/apply", "/api/device/updates/apply"):
        return self._json(200, _apply_update())
      if path in ("/api/action/reboot", "/api/device/reboot"):
        p.put_bool("DoReboot", True, block=True)
        return self._json(200, {"ok": True})
      if path in ("/api/action/shutdown", "/api/device/shutdown"):
        p.put_bool("DoShutdown", True, block=True)
        return self._json(200, {"ok": True})
      self._json(404, {"error": "not found"})
    except Exception:
      cloudlog.exception("deviceweb POST")
      self._json(500, {"error": traceback.format_exc().splitlines()[-1]})

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
    self.send_response(200)
    self._cors()
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(data)))
    if candidate.name == "index.html":
      self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(data)


def main() -> None:
  httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
  cloudlog.warning(f"deviceweb listening on 0.0.0.0:{PORT}")
  try:
    httpd.serve_forever()
  finally:
    httpd.server_close()


if __name__ == "__main__":
  main()
