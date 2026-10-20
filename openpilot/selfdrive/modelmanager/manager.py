#!/usr/bin/env python3
"""modelmanagerd: keeps the big-model catalog fresh and applies the pick.

sunnypilot's ModelManagerSP main loop (sunnypilot/models/manager.py) for the
one slot Highland has, with fetcher.py's ModelCache and fetcher_zp.py's
BigCatalogCache / ModelFetcherZP on plain dicts:

  - the catalog is fetched when ModelManager_LastSyncTime_Chestnut is unset,
    0 (the UI's refresh) or an hour old, extended through jetlink with the big
    models newer catalogs list, and cached in ModelManager_ModelsCache_Chestnut
    for jetlink and the UI. A failed fetch keeps the cache and backs off.
  - a ref the UI queues in ModelManager_DownloadRef is looked up in the
    catalog and stored in ModelManager_ActiveBundleChestnut without files:
    jetlink downloads and verifies the ONNX for that ref itself, and its
    owner restarts the provisioning when the pick changes.
  - after a fetch, a pick the catalog no longer lists is reset to the
    default (helpers.validate_active_bundles).

Offroad only (process_config), so nothing here competes with driving.
"""
from __future__ import annotations

import json
import time
import urllib.request

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.modelmanager import (ACTIVE_BIG, CACHE_BIG, CACHE_TIMEOUT, CATALOG_URL, DOWNLOAD_REF, EXTENDED_KEY,
                                              STATUS, SYNC_BIG, catalog_bundles, find_bundle, to_slot)
from openpilot.selfdrive.modelmanager import store

FETCH_TIMEOUT = 10.0
RETRY_AFTER = (30.0, 60.0, 120.0, 300.0)  # after a failed fetch, so offline is not a request a second


def _log():
  try:
    from openpilot.common.swaglog import cloudlog
    return cloudlog
  except Exception:
    import logging
    return logging.getLogger("modelmanagerd")


def http_fetch(url: str = CATALOG_URL, timeout: float = FETCH_TIMEOUT) -> dict:
  request = urllib.request.Request(url, headers={"User-Agent": "highland-modelmanager"})
  with urllib.request.urlopen(request, timeout=timeout) as response:
    return json.loads(response.read(16 << 20))


class ModelManager:
  def __init__(self, fetch=http_fetch, clock=time.monotonic, wall=None, log=None):
    self.fetch = fetch
    self.clock = clock
    self.wall = wall or (lambda: time.time())  # noqa: TID251  the fetch time the UI shows
    self.log = log or _log()
    self.failures = 0
    self._refetched_extends: bool | None = None
    self._status: dict = {}

  # -- the catalog (fetcher.ModelCache, fetcher_zp.BigCatalogCache) ------------

  def _expired(self, cached) -> bool:
    try:
      last = int(store.get(SYNC_BIG) or 0)
    except (TypeError, ValueError):
      last = 0
    if last == 0 or int(self.clock() * 1e9) - last >= CACHE_TIMEOUT * 1e9:
      return True
    if not catalog_bundles(cached):
      return False  # a failed fetch's back-off (refresh_catalog) is still running
    # fetched for other hardware (a chestnut came or went): once per change
    extends = bool(ja.should_extend_catalog())
    if bool(cached.get(EXTENDED_KEY)) != extends and self._refetched_extends != extends:
      self._refetched_extends = extends
      self.log.warning(f"modelmanagerd: catalog was fetched {'without' if extends else 'with'} the newer catalogs; refetching")
      return True
    return False

  def refresh_catalog(self, force: bool = False) -> bool:
    """Fetch the catalog if it is due. True when a new one was cached."""
    cached = store.get(CACHE_BIG)
    if not force and not self._expired(cached):
      return False
    self.report(state="fetching")
    try:
      data = self.fetch()
      if not catalog_bundles(data):
        raise ValueError("catalog lists no usable models")
      extends = bool(ja.should_extend_catalog())
      data = {**(ja.extend_catalog(data) if extends else data), EXTENDED_KEY: extends}
      store.put(CACHE_BIG, data)
      store.put(SYNC_BIG, int(self.clock() * 1e9))
    except Exception as e:
      self.failures += 1
      delay = RETRY_AFTER[min(self.failures, len(RETRY_AFTER)) - 1]
      # the cache stands; due again after delay, or at once on the UI's refresh (0)
      store.put(SYNC_BIG, int((self.clock() - CACHE_TIMEOUT + delay) * 1e9))
      self.log.warning(f"modelmanagerd: catalog fetch failed ({type(e).__name__}: {e}), retrying in {delay:.0f} s")
      self.report(state="failed", error=f"{type(e).__name__}: {e}"[:200])
      return False
    self.failures = 0
    self.report(state="idle", fetched=int(self.wall()), models=len(catalog_bundles(data)), error=None)
    # without jetlink here the newer catalogs' models are missing, not withdrawn
    if extends or ja._api() is not None:
      self.validate_pick(data)
    return True

  # -- the pick (manager._process_download_requests, helpers.validate_active_bundles)

  def validate_pick(self, catalog) -> None:
    pick = store.get(ACTIVE_BIG)
    if not isinstance(pick, dict) or not pick.get("ref"):
      return
    if catalog_bundles(catalog) and find_bundle(catalog, pick["ref"]) is None:
      self.log.warning(f"modelmanagerd: the catalog no longer lists {pick.get('displayName')} ({str(pick['ref'])[:10]}), back to the default")
      store.remove(ACTIVE_BIG)

  def process_request(self) -> None:
    ref = store.get(DOWNLOAD_REF)
    if not ref:
      return
    catalog = store.get(CACHE_BIG)
    bundle = find_bundle(catalog, str(ref))
    if bundle is None:
      if not catalog_bundles(catalog):
        return  # no catalog yet: the request waits for one
      self.log.warning(f"modelmanagerd: {str(ref)[:10]} is not in the catalog")
      self.report(state="failed", error="that model is not in the catalog")
    else:
      store.put(ACTIVE_BIG, to_slot(bundle))
      self.log.warning(f"modelmanagerd: big model set to {bundle['display_name']} ({bundle['ref'][:10]})")
      self.report(selected=bundle["ref"], error=None, state="idle")
    if store.get(DOWNLOAD_REF) == ref:
      store.remove(DOWNLOAD_REF)

  # -- status for the UI ---------------------------------------------------------

  def report(self, **fields) -> None:
    status = {**self._status, **fields}
    if status != self._status:
      self._status = status
      try:
        store.put(STATUS, status)
      except Exception:
        pass

  def step(self) -> None:
    for name, work in (("catalog", self.refresh_catalog), ("request", self.process_request)):
      try:
        work()
      except Exception:
        self.log.exception(f"modelmanagerd: {name} step failed")


def main() -> None:
  manager = ModelManager()
  manager.report(state="idle")
  while True:
    manager.step()
    time.sleep(1.0)


if __name__ == "__main__":
  main()
