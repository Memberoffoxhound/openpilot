#!/usr/bin/env python3
"""Driving-model catalog, favorites, and on-demand install for S3XYPilot.

Release model is the bundle already compiled into this tree and is always
available. Master models are the last three comma.ai/openpilot master bumps
of driving_supercombo.onnx (and big_driving_supercombo.onnx when a Chestnut
eGPU is present). Favoriting a master model keeps it off the 3-deep cycle.
Regular and eGPU pools are independent: 3 master + 5 favorites each.

ONNX files are not prefetched. Download + compile start only when a model is
selected or favorited. Progress is written to DrivingModelInstallStatus.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.modeld.helpers import MODELS_DIR

RELEASE_ID = "release"
COMMA_REPO = "commaai/openpilot"
ONNX_PATH = "openpilot/selfdrive/modeld/models/driving_supercombo.onnx"
BIG_ONNX_PATH = "openpilot/selfdrive/modeld/models/big_driving_supercombo.onnx"
GITHUB_API = "https://api.github.com"
LFS_MEDIA = "https://media.githubusercontent.com/media/commaai/openpilot"

MAX_MASTER = 3
MAX_FAVORITES = 5

DATA_ROOT = Path(os.environ.get("SEXYPILOT_MODEL_ROOT", "/data/sexypilot/models"))
CATALOG_PATH = DATA_ROOT / "catalog.json"

_lock = threading.RLock()
_install_thread: threading.Thread | None = None
_select_after: str | None = None


@dataclass
class ModelInfo:
  id: str
  name: str
  date: str  # YYYY-MM-DD
  sha: str
  egpu: bool = False
  source: str = "master"  # release | master | favorite
  commit_message: str = ""

  @property
  def label(self) -> str:
    badge = " eGPU" if self.egpu else ""
    return f"{self.name}{badge}"

  @property
  def subtitle(self) -> str:
    kind = "release" if self.source == "release" else self.source
    return f"{self.date}  ·  {kind}"


def _params() -> Params:
  return Params()


def _ensure_root() -> None:
  DATA_ROOT.mkdir(parents=True, exist_ok=True)


def model_dir(model_id: str) -> Path:
  return DATA_ROOT / model_id


def onnx_path(info: ModelInfo) -> Path:
  name = "big_driving_supercombo.onnx" if info.egpu else "driving_supercombo.onnx"
  return model_dir(info.id) / name


def pkl_path(info: ModelInfo) -> Path:
  name = "big_driving_tinygrad.pkl" if info.egpu else "driving_tinygrad.pkl"
  return model_dir(info.id) / name


def is_installed(info: ModelInfo) -> bool:
  if info.id.startswith("release"):
    stock = MODELS_DIR / ("big_driving_tinygrad.pkl" if info.egpu else "driving_tinygrad.pkl")
    manifest = Path(str(stock) + ".chunkmanifest")
    return stock.is_file() or manifest.is_file()
  p = pkl_path(info)
  return p.is_file() or Path(str(p) + ".chunkmanifest").is_file()


def selected_id() -> str:
  return _params().get("DrivingModelSelected") or RELEASE_ID


def set_selected_id(model_id: str) -> None:
  _params().put("DrivingModelSelected", model_id, block=True)


def selected_display_name() -> str:
  catalog = load_catalog()
  sid = selected_id()
  for info in catalog_all(catalog):
    if info.id == sid:
      return info.label
  return "Openpilot Release" if sid.startswith(RELEASE_ID) else sid


def selected_pkl_path(chestnut: bool) -> Path | None:
  """Compiled artifact for the currently selected model, or None to use stock."""
  sid = selected_id()
  if sid in (RELEASE_ID, f"{RELEASE_ID}-egpu"):
    return None
  catalog = load_catalog()
  info = next((m for m in catalog_all(catalog) if m.id == sid and m.egpu == chestnut), None)
  if info is None:
    return None
  p = pkl_path(info)
  if p.is_file() or Path(str(p) + ".chunkmanifest").is_file():
    return p
  return None


def want_big_model() -> bool:
  """True unless the user explicitly picked a regular (non-eGPU) master/favorite."""
  info = find_model(selected_id())
  if info is None or info.source == "release" or info.id.startswith("release"):
    return True
  return bool(info.egpu)


def _empty_catalog() -> dict:
  return {
    "release": asdict(_release_info(egpu=False)),
    "release_egpu": asdict(_release_info(egpu=True)),
    "master": [],
    "master_egpu": [],
    "favorites": [],
    "favorites_egpu": [],
    "fetched_at": 0,
  }


def _release_info(egpu: bool) -> ModelInfo:
  date = ""
  try:
    raw = _params().get("GitCommitDate") or ""
    token = raw.strip("'").split()
    if len(token) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}", token[1]):
      date = token[1]
  except Exception:
    pass
  return ModelInfo(
    id=RELEASE_ID if not egpu else f"{RELEASE_ID}-egpu",
    name="Openpilot Release",
    date=date or "bundled",
    sha="bundled",
    egpu=egpu,
    source="release",
    commit_message="openpilot release driving model",
  )


def load_catalog() -> dict:
  _ensure_root()
  if CATALOG_PATH.is_file():
    try:
      data = json.loads(CATALOG_PATH.read_text())
      data.setdefault("release", asdict(_release_info(False)))
      data.setdefault("release_egpu", asdict(_release_info(True)))
      for key in ("master", "master_egpu", "favorites", "favorites_egpu"):
        data.setdefault(key, [])
      return data
    except Exception:
      cloudlog.exception("model catalog read failed")
  catalog = _empty_catalog()
  save_catalog(catalog)
  return catalog


def save_catalog(catalog: dict) -> None:
  _ensure_root()
  tmp = CATALOG_PATH.with_suffix(".tmp")
  tmp.write_text(json.dumps(catalog, indent=2))
  tmp.replace(CATALOG_PATH)


def _as_info(raw: dict) -> ModelInfo:
  return ModelInfo(**{k: raw[k] for k in ModelInfo.__dataclass_fields__ if k in raw})


def catalog_all(catalog: dict | None = None) -> list[ModelInfo]:
  catalog = catalog or load_catalog()
  out: list[ModelInfo] = [_as_info(catalog["release"]), _as_info(catalog["release_egpu"])]
  for key in ("favorites", "favorites_egpu", "master", "master_egpu"):
    out.extend(_as_info(x) for x in catalog.get(key, []))
  return out


def find_model(model_id: str, catalog: dict | None = None) -> ModelInfo | None:
  return next((m for m in catalog_all(catalog) if m.id == model_id), None)


def favorites(egpu: bool, catalog: dict | None = None) -> list[ModelInfo]:
  catalog = catalog or load_catalog()
  key = "favorites_egpu" if egpu else "favorites"
  return [_as_info(x) for x in catalog.get(key, [])]


def masters(egpu: bool, catalog: dict | None = None) -> list[ModelInfo]:
  catalog = catalog or load_catalog()
  key = "master_egpu" if egpu else "master"
  return [_as_info(x) for x in catalog.get(key, [])]


def is_favorite(model_id: str, catalog: dict | None = None) -> bool:
  catalog = catalog or load_catalog()
  ids = {x["id"] for x in catalog.get("favorites", []) + catalog.get("favorites_egpu", [])}
  return model_id in ids


def _pretty_name(message: str, date: str) -> str:
  line = (message or "").split("\n", 1)[0].strip()
  line = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{14,}\b", "", line)
  line = re.sub(r"\b[0-9a-f]{40}\b", "", line)
  line = re.sub(r"\s{2,}", " ", line).strip(" :-/#")
  if not line or line.lower() in ("update model", "models", "model"):
    return f"Master {date}"
  if len(line) > 42:
    line = line[:40].rstrip() + "…"
  return line


def _model_id(sha: str, egpu: bool) -> str:
  prefix = "egpu" if egpu else "master"
  return f"{prefix}-{sha[:12]}"


def _http_json(url: str, timeout: int = 20):
  req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "sexypilot-model-selector"})
  with urllib.request.urlopen(req, timeout=timeout) as resp:
    return json.loads(resp.read().decode())


def _commits_for(path: str, sha: str, per_page: int) -> list[dict]:
  q = urllib.parse.urlencode({"path": path, "sha": sha, "per_page": per_page})
  url = f"{GITHUB_API}/repos/{COMMA_REPO}/commits?{q}"
  return _http_json(url)


def refresh_catalog(include_egpu: bool = False) -> dict:
  """Pull last-three master models from comma. Does not download ONNX."""
  with _lock:
    catalog = load_catalog()
    catalog["release"] = asdict(_release_info(False))
    catalog["release_egpu"] = asdict(_release_info(True))

    def ingest(path: str, egpu: bool) -> list[dict]:
      commits = _commits_for(path, "master", MAX_MASTER + 8)
      seen_sha: set[str] = set()
      models: list[ModelInfo] = []
      for c in commits:
        full = c["sha"]
        if full in seen_sha:
          continue
        seen_sha.add(full)
        date = (c.get("commit", {}).get("author", {}).get("date") or "")[:10]
        msg = c.get("commit", {}).get("message") or ""
        models.append(ModelInfo(
          id=_model_id(full, egpu),
          name=_pretty_name(msg, date or "unknown"),
          date=date or "unknown",
          sha=full,
          egpu=egpu,
          source="master",
          commit_message=msg.split("\n", 1)[0],
        ))
        if len(models) >= MAX_MASTER:
          break
      return [asdict(m) for m in models]

    catalog["master"] = ingest(ONNX_PATH, False)
    if include_egpu:
      catalog["master_egpu"] = ingest(BIG_ONNX_PATH, True)

    catalog["fetched_at"] = time.time()
    _prune_orphans(catalog)
    save_catalog(catalog)
    return catalog


def _protected_ids(catalog: dict) -> set[str]:
  ids = {RELEASE_ID, f"{RELEASE_ID}-egpu", selected_id()}
  for key in ("favorites", "favorites_egpu"):
    ids.update(x["id"] for x in catalog.get(key, []))
  for key in ("master", "master_egpu"):
    ids.update(x["id"] for x in catalog.get(key, []))
  return ids


def _prune_orphans(catalog: dict) -> None:
  keep = _protected_ids(catalog)
  if not DATA_ROOT.is_dir():
    return
  for child in DATA_ROOT.iterdir():
    if not child.is_dir():
      continue
    if child.name not in keep:
      shutil.rmtree(child, ignore_errors=True)


def toggle_favorite(model_id: str) -> tuple[bool, str]:
  """Star / unstar. Starring a missing master model starts an install."""
  with _lock:
    catalog = load_catalog()
    info = find_model(model_id, catalog)
    if info is None:
      return False, "unknown model"
    if info.source == "release" or info.id.startswith("release"):
      return False, "release is always kept"

    fav_key = "favorites_egpu" if info.egpu else "favorites"
    favs = catalog.get(fav_key, [])
    existing = next((i for i, x in enumerate(favs) if x["id"] == model_id), None)
    if existing is not None:
      favs.pop(existing)
      catalog[fav_key] = favs
      save_catalog(catalog)
      _prune_orphans(catalog)
      return True, "unstarred"

    if len(favs) >= MAX_FAVORITES:
      return False, f"favorites full ({MAX_FAVORITES})"

    entry = asdict(info)
    entry["source"] = "favorite"
    favs.append(entry)
    catalog[fav_key] = favs
    save_catalog(catalog)

  if not is_installed(info):
    start_install(info.id)
  return True, "starred"


def set_install_status(payload: dict) -> None:
  _params().put("DrivingModelInstallStatus", payload)


def get_install_status() -> dict:
  return _params().get("DrivingModelInstallStatus") or {}


def start_install(model_id: str, select_when_done: bool = False) -> bool:
  global _install_thread, _select_after
  info = find_model(model_id)
  if info is None:
    return False
  if info.id.startswith("release"):
    set_install_status({"id": info.id, "stage": "ready", "percent": 100, "error": ""})
    if select_when_done:
      set_selected_id(info.id)
      request_cycle()
    return True
  if _install_thread is not None and _install_thread.is_alive():
    current = get_install_status()
    if current.get("id") == model_id:
      if select_when_done:
        _select_after = model_id
      return True
    return False

  if select_when_done:
    _select_after = model_id

  def run():
    try:
      _install(info)
    except Exception as e:
      cloudlog.exception("model install failed")
      set_install_status({"id": info.id, "stage": "failed", "percent": 0, "error": str(e)[:180]})

  _install_thread = threading.Thread(target=run, daemon=True)
  _install_thread.start()
  return True


def _download(url: str, dest: Path, model_id: str) -> None:
  dest.parent.mkdir(parents=True, exist_ok=True)
  tmp = dest.with_suffix(dest.suffix + ".part")
  req = urllib.request.Request(url, headers={"User-Agent": "sexypilot-model-selector"})
  with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
    total = int(resp.headers.get("Content-Length") or 0)
    read = 0
    while True:
      chunk = resp.read(1024 * 256)
      if not chunk:
        break
      out.write(chunk)
      read += len(chunk)
      pct = int(read * 70 / total) if total else min(70, read // (1024 * 1024))
      set_install_status({"id": model_id, "stage": "downloading", "percent": pct, "error": ""})
  tmp.replace(dest)


def _compile_flags(egpu: bool) -> str:
  comma = Path("/TICI").is_file() or Path("/data/openpilot").is_dir()
  if egpu:
    return "DEBUG=2 DEV=USB+AMD:LLVM WARP_DEV=QCOM FLOAT16=1 JIT_BATCH_SIZE=0 GMMU=0 TC_OPT=2"
  if comma:
    return "DEV=QCOM IMAGE=1 FLOAT16=1 NOLOCALS=1 JIT_BATCH_SIZE=0 OPENPILOT_HACKS=1"
  return "DEV=CPU:LLVM"


def _install(info: ModelInfo) -> None:
  global _select_after
  set_install_status({"id": info.id, "stage": "downloading", "percent": 1, "error": ""})
  rel = BIG_ONNX_PATH if info.egpu else ONNX_PATH
  url = f"{LFS_MEDIA}/{info.sha}/{rel}"
  dest_onnx = onnx_path(info)
  _download(url, dest_onnx, info.id)
  if dest_onnx.stat().st_size < 1024:
    raise RuntimeError("download too small — LFS pointer or blocked")

  set_install_status({"id": info.id, "stage": "compiling", "percent": 75, "error": ""})
  dest_pkl = pkl_path(info)
  script = Path(__file__).resolve().parent / "compile_modeld.py"
  model_w, model_h = (1024, 512) if info.egpu else (512, 256)
  frame_skip = ModelConstants.MODEL_RUN_FREQ // ModelConstants.MODEL_CONTEXT_FREQ
  flags = _compile_flags(info.egpu)
  cmd = (
    f"{flags} python3 {script} "
    f"--model-size {model_w}x{model_h} "
    f"--camera-resolutions 1928x1208 1344x760 "
    f"--onnx {dest_onnx} --output {dest_pkl} --frame-skip {frame_skip}"
  )
  env = os.environ.copy()
  proc = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
  if proc.returncode != 0:
    tail = (proc.stderr or proc.stdout or "")[-400:]
    raise RuntimeError(f"compile failed: {tail}")
  if not dest_pkl.is_file():
    raise RuntimeError("compile produced no pkl")
  set_install_status({"id": info.id, "stage": "ready", "percent": 100, "error": ""})
  if _select_after == info.id:
    set_selected_id(info.id)
    request_cycle()
    _select_after = None


def select_model(model_id: str) -> tuple[bool, str]:
  info = find_model(model_id)
  if info is None:
    return False, "unknown model"
  if not is_installed(info):
    start_install(model_id, select_when_done=True)
    return False, "installing"
  set_selected_id(info.id)
  request_cycle()
  return True, "selected"


def request_cycle() -> None:
  _params().put_bool("OnroadCycleRequested", True)
