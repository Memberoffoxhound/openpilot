"""Highland's model manager: the big-model catalog and pick, for Jetlink.

Ported from sunnypilot's model manager as zoompilot wires it on develop
(sunnypilot/models/{fetcher,fetcher_zp,helpers,manager}.py), cut down to what
Highland can use:

  - the big-model (chestnut) catalog, driving_models_chestnut_v27.json, which
    jetlink extends with the big models newer catalogs list (fetcher_zp)
  - the big-model pick, ModelManager_ActiveBundleChestnut, stored without
    files: jetlink fetches and verifies the pick's ONNX itself, by its ref
  - refresh, reset to default and the picker's status

Not ported: sunnypilot's small-model bundles. Every one is a tinygrad pkl or
ONNX for the model interface comma retired in commaai/openpilot#38916
(img/big_img/desire_pulse/features_buffer, float16); Highland's modeld runs
the interface that replaced it (new_img and history queues inside the ONNX),
so none of them can load here. The small model stays the one in the tree.

Bundles are plain dicts (the JSON the catalog lists, and in the params the
camelCase form sunnypilot's capnp to_dict() writes), never capnp: Highland's
cereal has no ModelManagerSP. Every key is read and written through
store.get/put/remove, which fall back to the raw param file when the params
library is older than the key.
"""
from __future__ import annotations

import re

# sunnypilot's helpers.REQUIRED_JSON_VERSION on zoompilot develop: the catalog
# entries this build lists, and jetlink's catalog_selector
REQUIRED_JSON_VERSION = 20

CATALOG_URL = ("https://raw.githubusercontent.com/sunnypilot/sunnypilot-models/refs/heads/gh-pages/docs/" +
               "driving_models_chestnut_v27.json")
CACHE_TIMEOUT = 3600.0  # seconds, sunnypilot's ModelCache default

# params, all in params_keys.h (none BACKUP: Highland has no such flag)
ACTIVE_BIG = "ModelManager_ActiveBundleChestnut"   # the big-model pick; jetlink's keys.big_model
CACHE_BIG = "ModelManager_ModelsCache_Chestnut"    # the catalog JSON; jetlink's keys.catalog
SYNC_BIG = "ModelManager_LastSyncTime_Chestnut"    # monotonic ns of the last fetch, 0 asks for one
DOWNLOAD_REF = "ModelManager_DownloadRef"          # a pick the UI queued for the manager
STATUS = "ModelManager_Status"                     # what the manager is doing, for the UI

KEY_TYPES = {ACTIVE_BIG: "json", CACHE_BIG: "json", SYNC_BIG: "int", DOWNLOAD_REF: "str", STATUS: "json"}

EXTENDED_KEY = "extended"  # fetcher_zp: stamped on the catalog, whether jetlink extended it
_REF = re.compile(r"[0-9a-f]{40}")
_TRAILING_DATE = re.compile(r"\s*\([A-Za-z]+ \d{1,2}, \d{4}\)\s*$")


def is_bundle_version_compatible(bundle: dict) -> bool:
  """helpers.is_bundle_version_compatible, on the catalog's JSON form."""
  try:
    return int(bundle.get("minimum_selector_version", bundle.get("minimumSelectorVersion", 0))) == REQUIRED_JSON_VERSION
  except (TypeError, ValueError):
    return False


def catalog_bundles(catalog) -> list[dict]:
  """The catalog's usable bundles, newest first. Never raises."""
  try:
    bundles = (catalog or {}).get("bundles", []) if isinstance(catalog, dict) else []
    found = [b for b in bundles if isinstance(b, dict) and _REF.fullmatch(str(b.get("ref")))
             and is_bundle_version_compatible(b) and b.get("display_name")]
    found.sort(key=lambda b: int(b.get("index", 0)), reverse=True)
    return found
  except Exception:
    return []


def folder_of(bundle: dict) -> str:
  overrides = bundle.get("overrides") or {}
  if isinstance(overrides, list):  # the capnp to_dict() form
    overrides = {o.get("key"): o.get("value") for o in overrides if isinstance(o, dict)}
  return str(overrides.get("folder") or "other")


def short_name(name: str) -> str:
  """A display name without the catalog's trailing build date."""
  return _TRAILING_DATE.sub("", name or "")


def to_slot(bundle: dict) -> dict:
  """A catalog bundle as the pick param stores it: the camelCase dict
  sunnypilot's ModelBundle.to_dict() writes, so jetlink (models.selected_slot)
  and a sunnypilot reader see the same thing. models is empty: the pick is
  stored without files, as sunnypilot does for a big model with no chestnut."""
  overrides = bundle.get("overrides") or {}
  if isinstance(overrides, dict):
    overrides = [{"key": str(k), "value": str(v)} for k, v in overrides.items()]
  return {
    "index": int(bundle.get("index", 0)),
    "internalName": str(bundle.get("short_name") or ""),
    "displayName": str(bundle.get("display_name") or bundle["ref"][:10]),
    "models": [],
    "status": "downloaded",
    "generation": int(bundle.get("generation") or 0),
    "environment": str(bundle.get("environment") or ""),
    "runner": str(bundle.get("runner") or "tinygrad"),
    "is20hz": bool(bundle.get("is_20hz", False)),
    "minimumSelectorVersion": int(bundle.get("minimum_selector_version", REQUIRED_JSON_VERSION)),
    "overrides": overrides,
    "ref": bundle["ref"],
  }


def find_bundle(catalog, ref: str) -> dict | None:
  return next((b for b in catalog_bundles(catalog) if b.get("ref") == ref), None)
