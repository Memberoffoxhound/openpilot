#!/usr/bin/env python3
"""LAN device console for S3XYPilot. No auth — bind on the local network only."""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.weather_news import config as grok_cfg
from openpilot.selfdrive.weather_news import grok as grok_api

try:
  from openpilot.system.deviceweb import stats as drive_stats
except ImportError:
  import importlib.util
  _stats_spec = importlib.util.spec_from_file_location("deviceweb_stats", Path(__file__).parent / "stats.py")
  drive_stats = importlib.util.module_from_spec(_stats_spec)
  assert _stats_spec.loader is not None
  _stats_spec.loader.exec_module(drive_stats)

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
  "XaiApiKey", "OpenaiApiKey", "GroqApiKey", "GeminiApiKey",
}
WRITE_BOOL = {
  "OpenpilotEnabledToggle", "ExperimentalMode", "ExperimentalModeConfirmed",
  "AutoLaneChangeEnabled", "IsLdwEnabled", "AlwaysOnDM", "IsMetric",
  "DisengageOnAccelerator", "RecordFront", "RecordAudio",
  "SshEnabled", "AdbEnabled", "DisablePowerDown", "DisableUpdates",
  "ShowDebugInfo", "JoystickDebugMode", "GrokVoiceEnabled",
  "WeatherNewsWifiOnly", "IsLiveStreaming",
}
WRITE_INT = {"LaneColor", "LongitudinalPersonality", "CompassSize", "WeatherNewsMode",
             "WeatherNewsDuration", "WeatherNewsPlayback", "CustomOnroadUi"}
WRITE_STR = {"WeatherNewsPreview"}  # preview: nice|aggressive
# networkd/ModemManager own these — writing the param from the PWA does not stick (sunnylink hides NetworkMetered)
DEVICE_ONLY = {"GsmRoaming", "GsmMetered", "NetworkMetered"}
READ_KEYS = sorted(WRITE_BOOL | WRITE_INT | WRITE_STR | DEVICE_ONLY | {
  "DongleId", "Version", "GitBranch", "GitCommit", "GitRemote", "HardwareSerial",
  "IsOffroad", "IsEngaged", "UpdateAvailable", "UpdaterState", "UpdaterCurrentDescription",
  "UpdaterNewDescription", "UpdaterTargetBranch", "SshEnabled",
  "WeatherNewsLastRunDate", "WeatherNewsStatus", "GrokVoiceEnabled", "WeatherNewsTopics",
  "WeatherNewsDuration", "WeatherNewsWifiOnly", "WeatherNewsPlayback", "GrokProvider", "IsLiveStreaming",
  "LastGPSPosition", "CustomOnroadUi",
})
MAX_DOWNLOAD = 80 * 1024 * 1024
DATA_DIR = Path("/data/media/0")
CLIP_DIR = DATA_DIR / "clips"
SHOT_DIR = DATA_DIR / "screenshots"
MAX_CLIP_SEC = 30
SEG_RE = re.compile(
  r"^(?:(?P<dongle>[0-9a-fA-F]{16})[|_])?(?P<time>\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})(?:--(?P<seg>\d+))?$"
)
ROUTE_RE = re.compile(r"^(?P<rid>\d{8}--[0-9a-fA-F]+)(?:--(?P<seg>\d+))?$")
REALDATA = Path("/data/media/0/realdata")
FONT_PATH = OPENPILOT_DIR / "openpilot/selfdrive/assets/fonts/TESLA.ttf"
WEBRTC_URL = "http://127.0.0.1:5001/stream"
WEBRTC_SCHEMA = "http://127.0.0.1:5001/schema?services=deviceState"
TRIP_PATH = Path("/data/trip_meter.json")
GPS_CACHE = DATA_DIR / "stats"
DELOREAN_PATH = Path("/data/delorean_sound")
GROK_HOWTO = {
  "xai": "console.x.ai → API keys. Paste an xAI key. Chat is grok-4-fast; spoken voice is Ara TTS.",
  "openai": "platform.openai.com → API keys. Chat is gpt-4o-mini; spoken voice is OpenAI tts-1 (alloy).",
  "groq": "console.groq.com → API keys. Chat is Llama 3.3 70B. Groq has no TTS — add an OpenAI key too if you want Ara-style spoken audio.",
  "gemini": "aistudio.google.com → API keys. Chat is gemini-3.6-flash. Spoken voice is Ara if you also pasted an xAI key, otherwise OpenAI tts-1.",
}

_clip_lock = threading.Lock()
_clip_proc: subprocess.Popen | None = None
_clip_job: dict = {
  "state": "idle",
  "error": "",
  "route": "",
  "start": 0,
  "end": 0,
  "output": "",
}


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


_cpu_last: tuple[int, int] | None = None


def _cpu_pct() -> int | None:
  global _cpu_last
  try:
    with open("/proc/stat") as f:
      nums = [int(x) for x in f.readline().split()[1:8]]
    idle, total = nums[3] + nums[4], sum(nums)
    prev = _cpu_last
    _cpu_last = (idle, total)
    if prev is None:
      time.sleep(0.05)
      return _cpu_pct()
    didle, dtot = idle - prev[0], total - prev[1]
    if dtot <= 0:
      return 0
    return max(0, min(100, round(100.0 * (1.0 - didle / dtot))))
  except Exception:
    return None


def _mem_pct() -> int | None:
  try:
    vals: dict[str, int] = {}
    with open("/proc/meminfo") as f:
      for line in f:
        k, rest = line.split(":", 1)
        vals[k] = int(rest.strip().split()[0])
        if "MemAvailable" in vals and "MemTotal" in vals:
          break
    total, avail = vals.get("MemTotal") or 0, vals.get("MemAvailable") or 0
    if total <= 0:
      return None
    return max(0, min(100, round(100.0 * (1.0 - avail / total))))
  except Exception:
    return None


def _cpu_temp_c() -> int | None:
  temps: list[float] = []
  try:
    for name in os.listdir("/sys/class/thermal"):
      if not name.startswith("thermal_zone"):
        continue
      base = Path("/sys/class/thermal") / name
      try:
        kind = (base / "type").read_text().strip().lower()
        if "cpu" not in kind:
          continue
        temps.append(int((base / "temp").read_text().strip()) / 1000.0)
      except Exception:
        continue
  except Exception:
    return None
  if not temps:
    return None
  return round(sum(temps) / len(temps))


def _info() -> dict:
  p = _params()
  info = {
    "name": "S3XYPilot",
    "version": p.get("Version") or "0.1.10.24",
    "branch": p.get("GitBranch") or "Highland",
    "commit": p.get("GitCommit") or "",
    "remote": p.get("GitRemote") or "",
    "dongle": p.get("DongleId") or "",
    "serial": p.get("HardwareSerial") or "",
    "offroad": p.get_bool("IsOffroad"),
    "engaged": p.get_bool("IsEngaged"),
    "tempC": _cpu_temp_c(),
    "cpuPct": _cpu_pct(),
    "memPct": _mem_pct(),
    "diskFreeGb": None,
    "diskTotalGb": None,
    "network": "unknown",
    "wifiBars": 0,
    "updateAvailable": p.get_bool("UpdateAvailable"),
    "updaterState": p.get("UpdaterState") or "idle",
    "updaterNotes": p.get("UpdaterCurrentDescription") or p.get("UpdaterNewDescription") or "",
  }
  try:
    from openpilot.cereal import messaging
    sm = messaging.SubMaster(["deviceState"])
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
        # custom bools may live only on disk until first write
        try:
          out[k] = "1" if p.get_bool(k) else "0"
        except Exception:
          path = Path("/data/params/d") / k
          if path.exists():
            out[k] = "1" if path.read_text().strip().lower() in ("1", "true", "yes", "on") else "0"
          else:
            out[k] = "0"
      else:
        v = p.get(k)
        if v is None or v == "":
          path = Path("/data/params/d") / k
          if path.exists():
            out[k] = path.read_text().strip()
          else:
            out[k] = "1" if k in ("WeatherNewsMode", "WeatherNewsPlayback") else ""
        else:
          out[k] = str(v)
    except Exception:
      out[k] = ""
  try:
    out["Delorean"] = "1" if DELOREAN_PATH.read_text().strip().lower() in ("1", "true") else "0"
  except Exception:
    out["Delorean"] = "0"
  return out


def _write_params(body: dict) -> None:
  p = _params()
  param_dir = Path("/data/params/d")
  param_dir.mkdir(parents=True, exist_ok=True)
  for k, v in body.items():
    if k in SECRET_NAMES or k in DEVICE_ONLY:
      continue
    if k in WRITE_BOOL:
      on = str(v) in ("1", "true", "True", "yes")
      try:
        p.put_bool(k, on, block=True)
      except Exception:
        (param_dir / k).write_text("1" if on else "0")
      if k == "ExperimentalMode" and on:
        try:
          p.put_bool("ExperimentalModeConfirmed", True, block=True)
        except Exception:
          pass
    elif k in WRITE_INT:
      try:
        p.put(k, str(int(v)), block=True)
      except Exception:
        (param_dir / k).write_text(str(int(v)))
    elif k in WRITE_STR:
      s = str(v).strip().lower()
      if k == "WeatherNewsPreview" and s not in ("", "nice", "aggressive"):
        continue
      try:
        p.put(k, s, block=True)
      except Exception:
        (param_dir / k).write_text(s)
    if k == "GrokVoiceEnabled":
      grok_cfg.set_voice_enabled(str(v) in ("1", "true", "True", "yes"))
    elif k == "Delorean":
      DELOREAN_PATH.write_text("1" if str(v) in ("1", "true", "True", "yes") else "0")


def _mask(k: str) -> str:
  k = k or ""
  return (k[:4] + "…" + k[-4:]) if len(k) >= 8 else ""


def _grok_status() -> dict:
  return {
    "voice_on": grok_cfg.voice_enabled(),
    "configured": grok_cfg.configured(),
    "masked": grok_cfg.masked_key(),
    "openai_masked": _mask(grok_cfg.openai_key()),
    "groq_masked": _mask(grok_cfg.groq_key()),
    "gemini_masked": _mask(grok_cfg.gemini_key()),
    "url": grok_api.console_url("/grok"),
    "topics": grok_cfg.topics_text(),
    "suggestions": list(grok_cfg.TOPIC_SUGGESTIONS),
    "duration": grok_cfg.duration(),
    "wifi_only": grok_cfg.wifi_only(),
    "every_drive": grok_cfg.every_drive(),
    "playback": grok_cfg.playback(),
    "provider": grok_cfg.provider(),
    "howto": GROK_HOWTO,
  }


def _write_grok(body: dict) -> dict:
  if "api_key" in body:
    grok_cfg.set_api_key(str(body.get("api_key") or ""))
  if "openai_key" in body:
    grok_cfg.set_openai_key(str(body.get("openai_key") or ""))
  if "groq_key" in body:
    grok_cfg.set_groq_key(str(body.get("groq_key") or ""))
  if "gemini_key" in body:
    grok_cfg.set_gemini_key(str(body.get("gemini_key") or ""))
  if "provider" in body:
    grok_cfg.set_provider(str(body.get("provider") or "xai"))
  if "voice_on" in body:
    grok_cfg.set_voice_enabled(str(body.get("voice_on")) in ("1", "true", "True", "yes", "on"))
  if "topics" in body:
    grok_cfg.set_topics(str(body.get("topics") or ""))
  if "duration" in body:
    grok_cfg.set_duration(int(body.get("duration") or 60))
  if "wifi_only" in body:
    grok_cfg.set_wifi_only(str(body.get("wifi_only")) in ("1", "true", "True", "yes", "on"))
  if "every_drive" in body:
    grok_cfg.set_every_drive(str(body.get("every_drive")) in ("1", "true", "True", "yes", "on"))
  if "playback" in body:
    grok_cfg.set_playback(int(body.get("playback") or grok_cfg.PLAYBACK_BOOSTED))
  return _grok_status()


_update_lock = threading.Lock()
_update_job: dict = {
  "state": "idle",
  "percent": 0,
  "status": "",
  "error": "",
  "eta": None,
  "available": False,
}
_update_cancel = threading.Event()


def _set_update(**kwargs) -> None:
  with _update_lock:
    _update_job.update(kwargs)


def _update_status() -> dict:
  p = _params()
  with _update_lock:
    j = dict(_update_job)
  j["updaterState"] = p.get("UpdaterState") or "idle"
  j["updateAvailable"] = bool(p.get_bool("UpdateAvailable") or j.get("available"))
  j["fetchAvailable"] = p.get_bool("UpdaterFetchAvailable")
  j["offroad"] = p.get_bool("IsOffroad")
  return j


def _signal_updated(sig: str) -> bool:
  r = subprocess.run(
    ["pkill", f"-{sig}", "-f", "openpilot.system.updated.updated"],
    capture_output=True, timeout=5,
  )
  return r.returncode == 0


def _git_fetch_progress(branch: str) -> bool:
  proc = subprocess.Popen(
    ["git", "-C", str(OPENPILOT_DIR), "fetch", "--progress", "origin", branch],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
  )
  assert proc.stdout is not None
  for line in proc.stdout:
    if _update_cancel.is_set():
      proc.kill()
      return False
    m = re.search(r"(\d+)%", line)
    if m:
      pct = 18 + int(int(m.group(1)) * 0.7)
      _set_update(state="downloading", percent=min(88, pct), status=f"Downloading… {min(88, pct)}%")
  return proc.wait() == 0


def _ready_and_reboot() -> None:
  _set_update(state="ready", percent=100, status="Update ready. Installing in 10s.", available=True, error="")
  for left in range(10, 0, -1):
    if _update_cancel.is_set():
      _set_update(state="idle", status="Install cancelled.", eta=None, percent=100)
      return
    _set_update(eta=left, status=f"Installing in {left}s…")
    time.sleep(1)
  _params().put_bool("DoReboot", True, block=True)
  _set_update(state="rebooting", percent=100, status="Rebooting…", eta=0)


def _run_update() -> None:
  p = _params()
  branch = p.get("GitBranch") or "Highland"
  try:
    _set_update(state="checking", percent=8, status="Checking…", error="", eta=None, available=False)
    _signal_updated("SIGUSR1")
    t0 = time.monotonic()
    saw = False
    while time.monotonic() - t0 < 12:
      if _update_cancel.is_set():
        _set_update(state="idle", status="Cancelled")
        return
      st = p.get("UpdaterState") or "idle"
      if st and st != "idle":
        saw = True
        _set_update(percent=12, status=st)
      if p.get_bool("UpdateAvailable") or p.get_bool("UpdaterFetchAvailable"):
        break
      time.sleep(0.4)

    if p.get_bool("UpdateAvailable"):
      _ready_and_reboot()
      return

    if p.get_bool("UpdaterFetchAvailable") or saw:
      _set_update(state="downloading", percent=20, status="Downloading…")
      _signal_updated("SIGHUP")
      t1 = time.monotonic()
      while time.monotonic() - t1 < 180:
        if _update_cancel.is_set():
          _set_update(state="idle", status="Cancelled")
          return
        st = p.get("UpdaterState") or "idle"
        elapsed = time.monotonic() - t1
        if st == "downloading...":
          _set_update(percent=min(80, 20 + int(elapsed * 1.2)), status="Downloading…")
        elif st == "finalizing update...":
          _set_update(percent=90, status="Finalizing…")
        elif p.get_bool("UpdateAvailable") or st == "idle" and elapsed > 4:
          if p.get_bool("UpdateAvailable"):
            _ready_and_reboot()
            return
          break
        time.sleep(0.5)

    _set_update(state="downloading", percent=22, status="Fetching origin…")
    if not _git_fetch_progress(branch):
      if _update_cancel.is_set():
        _set_update(state="idle", status="Cancelled")
        return
      _set_update(state="error", error="git fetch failed", status="Fetch failed")
      return
    head = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", f"origin/{branch}")
    if head == remote:
      _set_update(state="idle", percent=100, status="Already current.", available=False)
      p.put_bool("UpdateAvailable", False, block=True)
      return
    _set_update(percent=92, status="Applying…")
    _git("reset", "--hard", f"origin/{branch}")
    p.put_bool("UpdateAvailable", True, block=True)
    _ready_and_reboot()
  except Exception as e:
    cloudlog.exception("update job")
    _set_update(state="error", error=str(e), status="Update failed")


def _check_updates() -> dict:
  p = _params()
  if not p.get_bool("IsOffroad"):
    return {"ok": False, "error": "Go offroad first."}
  with _update_lock:
    if _update_job["state"] in ("checking", "downloading", "finalizing", "ready", "rebooting"):
      return {"ok": False, "error": "update already running", "job": dict(_update_job)}
  _update_cancel.clear()
  threading.Thread(target=_run_update, daemon=True).start()
  return {"ok": True, "job": _update_status()}


def _apply_update() -> dict:
  p = _params()
  if not p.get_bool("IsOffroad"):
    return {"ok": False, "error": "Go offroad first."}
  if p.get_bool("UpdateAvailable"):
    _update_cancel.clear()
    threading.Thread(target=_ready_and_reboot, daemon=True).start()
    return {"ok": True, "job": _update_status()}
  return _check_updates()


def _cancel_update() -> dict:
  _update_cancel.set()
  _set_update(state="idle", status="Cancelled", eta=None)
  return _update_status()


def _clip_gate() -> str | None:
  p = _params()
  if not p.get_bool("IsOffroad"):
    return "Offroad only. Park first."
  if p.get_bool("IsLiveStreaming"):
    return "Turn Connect live off. Clip uses the UI/camera path."
  if p.get_bool("IsDriverViewEnabled"):
    return "Exit driver view first."
  return None


def _route_id(name: str) -> str | None:
  m = ROUTE_RE.match(name) or SEG_RE.match(name)
  if not m:
    return None
  gd = m.groupdict()
  return gd.get("rid") or gd.get("time")


def _scan_roots() -> list[Path]:
  roots = []
  if REALDATA.is_dir():
    roots.append(REALDATA)
  if DATA_DIR.is_dir():
    roots.append(DATA_DIR)
  return roots


def _list_routes() -> list[dict]:
  grouped: dict[str, dict] = {}
  for root in _scan_roots():
    try:
      entries = os.scandir(root)
    except OSError:
      continue
    for ent in entries:
      if ent.name in ("clips", "screenshots", "realdata", "stats"):
        continue
      rid = _route_id(ent.name)
      if not rid or not ent.is_dir(follow_symlinks=False):
        continue
      m = ROUTE_RE.match(ent.name) or SEG_RE.match(ent.name)
      try:
        seg = int(m.group("seg")) if m and m.group("seg") is not None else 0
      except (TypeError, ValueError):
        seg = 0
      g = grouped.setdefault(rid, {
        "name": rid, "segments": 0, "bytes": 0, "has_qcam": False, "has_fcam": False,
        "dongle": (m.group("dongle") if m and m.groupdict().get("dongle") else "") or "",
        "mtime": 0, "root": str(root), "segs": [],
      })
      g["segments"] += 1
      g["segs"].append(seg)
      try:
        st = ent.stat(follow_symlinks=False)
        g["mtime"] = max(g["mtime"], int(st.st_mtime))
        for f in os.scandir(ent.path):
          try:
            g["bytes"] += f.stat(follow_symlinks=False).st_size
          except OSError:
            pass
          if f.name.startswith("qcamera"):
            g["has_qcam"] = True
          if f.name.startswith("fcamera"):
            g["has_fcam"] = True
      except OSError:
        pass
  out = list(grouped.values())
  for g in out:
    g["segs"] = sorted(set(g["segs"]))
    g["segments"] = len(g["segs"])
    g["seconds"] = max(60, g["segments"] * 60)
  out.sort(key=lambda x: (x["mtime"], x["name"]), reverse=True)
  return out[:120]


def _dist(meters: float, metric: bool) -> float:
  m = float(meters or 0)
  return round(m / 1000.0, 1) if metric else round(m / 1609.344, 1)


def _home() -> dict:
  trip: dict = {}
  try:
    trip = json.loads(TRIP_PATH.read_text())
  except Exception:
    pass
  p = _params()
  metric = bool(p.get_bool("IsMetric"))
  gps_raw = (p.get("LastGPSPosition") or "").strip()
  lat = lon = None
  if "," in gps_raw:
    try:
      lat, lon = (float(x) for x in gps_raw.split(",", 1))
    except Exception:
      lat = lon = None
  today_m = float(trip.get("today_m") or 0)
  today_eng = float(trip.get("today_eng_m") or 0)
  week_m = float(trip.get("week_m") or 0)
  week_eng = float(trip.get("week_eng_m") or 0)
  return {
    "info": _info(),
    "metric": metric,
    "unit": "km" if metric else "mi",
    "gps": {"lat": lat, "lon": lon},
    "today": _dist(today_m, metric),
    "todayEng": _dist(today_eng, metric),
    "week": _dist(week_m, metric),
    "weekEng": _dist(week_eng, metric),
    "trip": _dist(float(trip.get("trip_m") or 0), metric),
    "last": _dist(float(trip.get("last_m") or 0), metric),
    "engPct": round(100.0 * week_eng / week_m, 0) if week_m > 50 else 0,
    "route": trip.get("route") or "",
    "dayId": trip.get("day_id") or "",
    "weekId": trip.get("week_id") or "",
    "engaged": bool(p.get_bool("IsEngaged")),
    "offroad": bool(p.get_bool("IsOffroad")),
    "live": bool(p.get_bool("IsLiveStreaming")),
  }


def _seg_dir(rid: str, seg: int) -> Path | None:
  if _route_id(rid) != rid:
    return None
  for root in _scan_roots():
    p = root / f"{rid}--{seg}"
    if p.is_dir():
      return p
    if seg == 0:
      p = root / rid
      if p.is_dir():
        return p
  return None


def _qcam_path(rid: str, seg: int) -> Path | None:
  d = _seg_dir(rid, seg)
  if d is None:
    return None
  for name in ("qcamera.ts", "qcamera"):
    p = d / name
    if p.is_file():
      return p
  return None


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
  import math
  r = 6371000.0
  p1, p2 = math.radians(a[0]), math.radians(b[0])
  dphi = math.radians(b[0] - a[0])
  dl = math.radians(b[1] - a[1])
  h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
  return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _route_gps(rid: str) -> dict:
  if _route_id(rid) != rid:
    return {"name": rid, "points": [], "error": "bad route"}
  GPS_CACHE.mkdir(parents=True, exist_ok=True)
  cache = GPS_CACHE / f"gps_{rid.replace('/', '_')}.json"
  if cache.is_file():
    try:
      return json.loads(cache.read_text())
    except Exception:
      pass
  segs = []
  for root in _scan_roots():
    try:
      for ent in os.scandir(root):
        m = ROUTE_RE.match(ent.name) or SEG_RE.match(ent.name)
        if not m:
          continue
        ident = m.groupdict().get("rid") or m.groupdict().get("time")
        if ident != rid:
          continue
        try:
          segs.append(int(m.group("seg") or 0))
        except (TypeError, ValueError):
          segs.append(0)
    except OSError:
      continue
  segs = sorted(set(segs))[:12]
  points: list[list[float]] = []
  last: tuple[float, float] | None = None
  t0 = time.monotonic()
  try:
    from openpilot.tools.lib.logreader import LogReader
  except Exception as e:
    return {"name": rid, "points": [], "error": str(e)[:80]}
  for seg in segs:
    if time.monotonic() - t0 > 8:
      break
    d = _seg_dir(rid, seg)
    if d is None:
      continue
    qlog = None
    try:
      for f in os.scandir(d):
        if f.name.startswith("qlog"):
          qlog = Path(f.path)
          break
    except OSError:
      continue
    if qlog is None:
      continue
    try:
      for msg in LogReader(str(qlog)):
        if time.monotonic() - t0 > 8:
          break
        which = msg.which()
        if which not in ("gpsLocation", "gpsLocationExternal"):
          continue
        g = getattr(msg, which)
        lat, lon = float(g.latitude), float(g.longitude)
        if abs(lat) < 1 and abs(lon) < 1:
          continue
        pt = (lat, lon)
        if last is None or _haversine_m(last, pt) >= 22:
          points.append([round(lat, 6), round(lon, 6)])
          last = pt
    except Exception:
      continue
  report = {"name": rid, "points": points[:1800]}
  try:
    cache.write_text(json.dumps(report))
  except Exception:
    pass
  return report


def _webrtc_ready() -> bool:
  try:
    with urllib.request.urlopen(WEBRTC_SCHEMA, timeout=1) as r:
      return r.status == 200
  except Exception:
    return False


def _webrtc_stream(body: dict) -> tuple[int, dict]:
  raw = json.dumps(body).encode()
  req = urllib.request.Request(
    WEBRTC_URL, data=raw, method="POST",
    headers={"Content-Type": "application/json", "Content-Length": str(len(raw))},
  )
  try:
    with urllib.request.urlopen(req, timeout=35) as r:
      return r.status, json.loads(r.read().decode() or "{}")
  except urllib.error.HTTPError as e:
    try:
      payload = json.loads(e.read().decode() or "{}")
    except Exception:
      payload = {"error": str(e)}
    return e.code, payload
  except Exception as e:
    return 503, {"error": str(e), "hint": "Turn On-Air on and wait for webrtcd."}


def _clip_status() -> dict:
  with _clip_lock:
    j = dict(_clip_job)
    out = j.get("output") or ""
  if out and Path(out).is_file():
    j["size"] = Path(out).stat().st_size
    j["file"] = out
  return j


def _kill_clip(reason: str = "cancelled") -> None:
  global _clip_proc
  with _clip_lock:
    proc = _clip_proc
  if proc is not None and proc.poll() is None:
    proc.terminate()
    try:
      proc.wait(timeout=6)
    except Exception:
      proc.kill()
  with _clip_lock:
    _clip_proc = None
    if _clip_job["state"] == "running":
      _clip_job["state"] = "error"
      _clip_job["error"] = reason


def _watch_onroad() -> None:
  while True:
    time.sleep(2)
    try:
      if not _params().get_bool("IsOffroad"):
        with _clip_lock:
          running = _clip_job["state"] == "running"
        if running:
          cloudlog.warning("clip aborted: onroad")
          _kill_clip("aborted — car went onroad")
    except Exception:
      pass


def _run_clip(route: str, start: int, end: int, title: str, qcam: bool) -> None:
  global _clip_proc
  CLIP_DIR.mkdir(parents=True, exist_ok=True)
  dongle = _params().get("DongleId") or "0000000000000000"
  route_id = route if "/" in route or "|" in route else f"{dongle}/{route}"
  out = CLIP_DIR / f"{route.replace('|', '_')}_{start}-{end}.mp4"
  cmd = [
    sys.executable, "-m", "openpilot.tools.clip.run",
    route_id, "-s", str(start), "-e", str(end),
    "-d", str(DATA_DIR), "-o", str(out), "-f", "9",
    "-t", title or "S3XYPilot",
  ]
  if qcam:
    cmd.append("--qcam")
  env = os.environ.copy()
  env["OFFSCREEN"] = "1"
  env["RECORD"] = "1"
  log_path = Path("/tmp/clip.log")
  with log_path.open("ab") as logf:
    logf.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n".encode())
    try:
      proc = subprocess.Popen(cmd, cwd=str(OPENPILOT_DIR), env=env, stdout=logf, stderr=logf)
      with _clip_lock:
        _clip_proc = proc
        _clip_job["output"] = str(out)
      rc = proc.wait()
      with _clip_lock:
        if _clip_job["state"] != "running":
          return
        if rc == 0 and out.is_file() and out.stat().st_size > 1000:
          _clip_job["state"] = "done"
          _clip_job["error"] = ""
        else:
          _clip_job["state"] = "error"
          _clip_job["error"] = f"clip exited {rc}"
    except Exception as e:
      with _clip_lock:
        _clip_job["state"] = "error"
        _clip_job["error"] = str(e)
    finally:
      with _clip_lock:
        _clip_proc = None


def _start_clip(body: dict) -> dict:
  gate = _clip_gate()
  if gate:
    return {"ok": False, "error": gate}
  route = str(body.get("route") or "")
  if not SEG_RE.match(route) and not SEG_RE.match(route.replace("|", "_").replace("/", "_")):
    if not re.match(r"^\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2}$", route):
      return {"ok": False, "error": "bad route"}
  try:
    start = int(body.get("start") or 0)
    end = int(body.get("end") or 0)
  except (TypeError, ValueError):
    return {"ok": False, "error": "bad times"}
  if end - start < 3:
    return {"ok": False, "error": "clip must be at least 3 seconds"}
  if end - start > MAX_CLIP_SEC:
    return {"ok": False, "error": f"max {MAX_CLIP_SEC}s on this device"}
  with _clip_lock:
    if _clip_job["state"] == "running":
      return {"ok": False, "error": "already rendering"}
    _clip_job.update({"state": "running", "error": "", "route": route, "start": start, "end": end, "output": ""})
  threading.Thread(
    target=_run_clip,
    args=(route, start, end, str(body.get("title") or "S3XYPilot"), bool(body.get("qcam"))),
    daemon=True,
  ).start()
  return {"ok": True, "job": _clip_status()}


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


SHOT_REQ = Path("/data/screenshot_request")
SHOT_PLAY = Path("/data/screenshot_play")


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
  # UI ScreenShotter watches this flag and writes the PNG.
  SHOT_REQ.write_text("1")
  try:
    SHOT_PLAY.write_text("1")
  except OSError:
    pass
  return {"ok": True}


class Handler(BaseHTTPRequestHandler):
  server_version = "S3XYPilot/0.1.10.24"

  def log_message(self, fmt: str, *args) -> None:
    cloudlog.info("deviceweb " + (fmt % args))

  def _cors(self) -> None:
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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
      if path in ("/api/grok", "/api/device/grok"):
        return self._json(200, _grok_status())
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
        return self._json(200, {**_info(), "job": _update_status()})
      if path in ("/api/routes", "/api/device/routes"):
        return self._json(200, {"routes": _list_routes()})
      if path in ("/api/clip", "/api/device/clip"):
        return self._json(200, _clip_status())
      if path in ("/api/screenshots", "/api/device/screenshots"):
        return self._json(200, {"items": _list_shots()})
      if path in ("/api/screenshots/raw", "/api/device/screenshots/raw"):
        name = Path((qs.get("name") or [""])[0]).name
        target = SHOT_DIR / name
        if not name.endswith(".png") or not target.is_file():
          return self._json(404, {"error": "not found"})
        data = target.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return
      if path in ("/api/stats", "/api/device/stats"):
        return self._json(200, drive_stats.status())
      if path in ("/api/home", "/api/device/home"):
        return self._json(200, _home())
      if path in ("/api/live", "/api/device/live"):
        return self._json(200, {
          "live": bool(_params().get_bool("IsLiveStreaming")),
          "webrtc": _webrtc_ready(),
        })
      if path in ("/api/qcam", "/api/device/qcam"):
        rid = _route_id((qs.get("route") or [""])[0])
        if not rid:
          return self._json(400, {"error": "bad route"})
        try:
          seg = int((qs.get("seg") or ["0"])[0])
        except (TypeError, ValueError):
          seg = 0
        target = _qcam_path(rid, seg)
        if target is None:
          return self._json(404, {"error": "no qcamera"})
        return self._send_file(target, "video/mp2t")
      if path in ("/api/route/gps", "/api/device/route/gps"):
        rid = _route_id((qs.get("route") or [""])[0])
        if not rid:
          return self._json(400, {"error": "bad route"})
        return self._json(200, _route_gps(rid))
      if path in ("/font/TESLA.ttf", "/api/font"):
        if not FONT_PATH.is_file():
          return self._json(404, {"error": "font missing"})
        data = FONT_PATH.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "font/ttf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)
        return
      if path in ("/api/clip/file", "/api/device/clip/file"):
        st = _clip_status()
        target = _safe_file(st.get("output") or "")
        if target is None or not target.is_file():
          return self._json(404, {"error": "no clip"})
        data = target.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)
        return
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
      if path in ("/api/grok", "/api/device/grok"):
        return self._json(200, _write_grok(self._read_json()))
      self._json(404, {"error": "not found"})
    except Exception:
      cloudlog.exception("deviceweb PUT")
      self._json(500, {"error": traceback.format_exc().splitlines()[-1]})

  def do_DELETE(self) -> None:
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    try:
      if path in ("/api/screenshots", "/api/device/screenshots"):
        names = self._read_json().get("names") or []
        if isinstance(names, str):
          names = [names]
        return self._json(200, _delete_shots(list(names)))
      self._json(404, {"error": "not found"})
    except Exception:
      cloudlog.exception("deviceweb DELETE")
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
      if path in ("/api/updates/cancel", "/api/device/updates/cancel"):
        return self._json(200, _cancel_update())
      if path in ("/api/action/reboot", "/api/device/reboot"):
        p.put_bool("DoReboot", True, block=True)
        return self._json(200, {"ok": True})
      if path in ("/api/action/shutdown", "/api/device/shutdown"):
        p.put_bool("DoShutdown", True, block=True)
        return self._json(200, {"ok": True})
      if path in ("/api/clip", "/api/device/clip"):
        return self._json(200, _start_clip(self._read_json()))
      if path in ("/api/clip/cancel", "/api/device/clip/cancel"):
        _kill_clip("cancelled")
        return self._json(200, _clip_status())
      if path in ("/api/stats", "/api/device/stats"):
        body = self._read_json()
        start = str(body.get("from") or "")
        end = str(body.get("to") or "")
        if not start or not end:
          start, end = drive_stats.default_range()
        return self._json(200, drive_stats.start(start, end, p.get_bool("IsOffroad")))
      if path in ("/api/live", "/api/device/live"):
        body = self._read_json()
        on = str(body.get("on", True)).lower() in ("1", "true", "yes", "on")
        p.put_bool("IsLiveStreaming", on, block=True)
        return self._json(200, {"ok": True, "live": on, "webrtc": _webrtc_ready()})
      if path in ("/api/webrtc/stream", "/api/device/webrtc/stream"):
        code, payload = _webrtc_stream(self._read_json())
        return self._json(code, payload)
      if path in ("/api/grok/test", "/api/device/grok/test"):
        body = self._read_json()
        key = str(body.get("api_key") or "").strip() or None
        provider = str(body.get("provider") or "").strip() or None
        ok, msg = grok_api.test_key(key, provider)
        return self._json(200, {"ok": ok, "status": msg, **_grok_status()})
      if path in ("/api/weather/preview", "/api/device/weather/preview"):
        body = self._read_json()
        mode = str(body.get("mode") or "").strip().lower()
        if mode == "unhinged":
          mode = "aggressive"
        if mode not in ("nice", "aggressive"):
          try:
            cur = int(p.get("WeatherNewsMode", return_default=True) or 1)
          except Exception:
            cur = 1
          if cur == 0:
            return self._json(400, {"ok": False, "error": "weather is off"})
          mode = "aggressive" if cur == 2 else "nice"
        _write_params({"WeatherNewsPreview": mode})
        return self._json(200, {"ok": True, "mode": mode})
      if path in ("/api/screenshots/capture", "/api/device/screenshots/capture"):
        return self._json(200, _request_shot())
      if path in ("/api/screenshots/delete", "/api/device/screenshots/delete"):
        names = self._read_json().get("names") or []
        if isinstance(names, str):
          names = [names]
        return self._json(200, _delete_shots(list(names)))
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
    if candidate.name in ("index.html", "app.js", "app.css"):
      self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(data)

  def _send_file(self, target: Path, ctype: str) -> None:
    size = target.stat().st_size
    start, end, code = 0, size - 1, 200
    rng = self.headers.get("Range") or ""
    if rng.startswith("bytes=") and size > 0:
      spec = rng[6:].split("-", 1)
      try:
        if spec[0]:
          start = max(0, int(spec[0]))
        if len(spec) > 1 and spec[1]:
          end = min(size - 1, int(spec[1]))
        code = 206
      except ValueError:
        start, end, code = 0, size - 1, 200
    if start > end or start >= size:
      self.send_response(416)
      self._cors()
      self.send_header("Content-Range", f"bytes */{size}")
      self.end_headers()
      return
    length = end - start + 1
    self.send_response(code)
    self._cors()
    self.send_header("Content-Type", ctype)
    self.send_header("Accept-Ranges", "bytes")
    self.send_header("Content-Length", str(length))
    if code == 206:
      self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    self.end_headers()
    with target.open("rb") as f:
      f.seek(start)
      left = length
      while left > 0:
        chunk = f.read(min(65536, left))
        if not chunk:
          break
        self.wfile.write(chunk)
        left -= len(chunk)


def main() -> None:
  threading.Thread(target=_watch_onroad, daemon=True).start()
  httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
  cloudlog.warning(f"deviceweb listening on 0.0.0.0:{PORT}")
  try:
    httpd.serve_forever()
  finally:
    httpd.server_close()


if __name__ == "__main__":
  main()
