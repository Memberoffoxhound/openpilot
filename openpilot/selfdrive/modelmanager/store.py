"""The model manager's params, with the raw-file fallback.

Params first; when the params library rejects the key (a params_pyx.so built
before params_keys.h gained it, or no library at all) the param's own file in
the params directory, in params.cc's byte format, as jetlink_adapter does.
Never raises out of get().
"""
from __future__ import annotations

import json

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.modelmanager import KEY_TYPES

_store: list = []


def _params():
  if not _store:
    from openpilot.common.params import Params
    _store.append(Params())
  return _store[0]


def _decode(key: str, raw: bytes):
  kind = KEY_TYPES.get(key, "str")
  if kind == "json":
    return json.loads(raw)
  if kind == "int":
    return int(raw)
  return raw.decode()


def _encode(key: str, value) -> bytes:
  kind = KEY_TYPES.get(key, "str")
  if kind == "json":
    return json.dumps(value).encode()
  if kind == "int":
    return str(int(value)).encode()
  return value if isinstance(value, bytes) else str(value).encode()


def file_get(key: str):
  try:
    raw = (ja._params_dir() / key).read_bytes()
  except OSError:
    return None
  try:
    return _decode(key, raw)
  except Exception:
    return None


def file_put(key: str, value) -> None:
  import os
  where = ja._params_dir()
  where.mkdir(parents=True, exist_ok=True)
  tmp = where / f".tmp_{key}_{os.getpid()}"
  with open(tmp, "wb") as f:
    f.write(_encode(key, value))
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, where / key)


def get(key: str):
  try:
    value = _params().get(key)
  except Exception:
    return file_get(key)
  if isinstance(value, bytes):  # a STRING read by an older library
    try:
      return _decode(key, value)
    except Exception:
      return None
  return value


def put(key: str, value) -> None:
  try:
    _params().put(key, value, block=True)
  except Exception:
    file_put(key, value)


def remove(key: str) -> None:
  try:
    _params().remove(key)
  except Exception:
    ja.file_remove(key)
