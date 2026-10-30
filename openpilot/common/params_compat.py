"""Params that survive a params library older than the key.

tripstats, park_offroad and tesla_step_aside are meant to be copied to other
forks, whose prebuilt params library may not know their keys yet: an unknown key
reads and writes the raw params file, in params.cc's byte format, instead of
raising. Standard library only, so tesla_step_aside stays light for card."""
import json
import os


def _path(params, key: str) -> str:
  return os.path.join(params.get_param_path(), key)


def _known(params, key: str) -> bool:
  try:
    params.check_key(key)
    return True
  except Exception:
    return False


def get(params, key: str):
  """params.get with its default, the raw file's bytes for an unknown key, None when unreadable."""
  if not _known(params, key):
    try:
      with open(_path(params, key), "rb") as f:
        return f.read().strip()
    except Exception:
      return None
  try:
    return params.get(key, return_default=True)
  except Exception:
    return None


def get_bool(params, key: str, default: bool = False) -> bool:
  raw = get(params, key)
  if isinstance(raw, bytes):
    return raw in (b"1", b"true", b"True")
  return default if raw is None else bool(raw)


def get_json(params, key: str) -> dict | None:
  raw = get(params, key)
  try:
    if isinstance(raw, (bytes, str)):
      raw = json.loads(raw)
  except ValueError:
    return None
  return raw if isinstance(raw, dict) else None


def _write(params, key: str, write, raw: bytes) -> None:
  if _known(params, key):
    try:
      write()
      return
    except Exception:
      pass
  path = _path(params, key)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  tmp = f"{path}.tmp{os.getpid()}"
  with open(tmp, "wb") as f:
    f.write(raw)
  os.replace(tmp, path)


def put(params, key: str, value, raw: bytes, block: bool = False) -> None:
  _write(params, key, lambda: params.put(key, value, block=block), raw)


def put_bool(params, key: str, value: bool, block: bool = False) -> None:
  _write(params, key, lambda: params.put_bool(key, value, block=block), b"1" if value else b"0")


def put_json(params, key: str, value: dict, block: bool = False) -> None:
  put(params, key, value, json.dumps(value).encode(), block)
