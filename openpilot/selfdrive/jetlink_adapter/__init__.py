"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
Ported to Highland (Memberoffoxhound/openpilot) from zoompilot develop 632b0b0
(openpilot/sunnypilot/jetlink_adapter/__init__.py), on jetlink b1d7041's Stock
base and Hooks. Highland changes, in short:
  - lives at openpilot/selfdrive/jetlink_adapter (no sunnypilot tree here)
  - Keys.big_model / Keys.catalog are Highland's model manager's params
    (openpilot/selfdrive/modelmanager), as on zoompilot, and catalog_selector
    its REQUIRED_JSON_VERSION (20). Until it has fetched a catalog, get()
    answers one listing jetlink's default
  - in_control is jetlink's Stock rule (carState, carControl, selfdriveState):
    no MADS / carControlSP; stock modeld's warp, model face and ModelState
    reset (Stock.small_reset), as Highland runs stock modeld
  - get/put/remove fall back to the raw params files when the params library
    on the device predates the Jetlink keys (UnknownKeyName), so a stale
    prebuilt params_pyx.so can never crash-loop anything (cf. 583cce9)
  - jetlinkd turns ADB off before the owner starts (release_adb)
  - with the Jetlink setting off, nothing in an always-running process
    (manager, modeld, hardwared, selfdrived, the UI) imports jetlink: each
    hook below reads the setting's params file first

jetlink (the jetlink_repo submodule) runs the large driving model on an
attached Jetson, Mac or iPhone. Its stock adapter (jetlink.openpilot.stock)
knows stock openpilot's paths; Adapter below is that with this fork's param
names. The hooks (jetlink.openpilot.hooks) never raise and answer as if the
link were off when jetlink is not checked out, or speaks another API.

comma's chestnut board is not jetlink's business: modeld, hardwared and the
UI handle it natively, and jetlink keeps the link off while one is fitted.

manager imports this module to build the process list, and runs it as
jetlinkd, the resident gadget owner, which stays at about 10 MB for the whole
drive. So the top level is the standard library only; everything else is
imported where it is used. tests/test_adapter.py holds the line.
"""
from __future__ import annotations

import functools
import os
import threading
from collections import namedtuple
from pathlib import Path

# the version of jetlink.openpilot's API this adapter is written to; any other
# is treated as jetlink being absent, with the reason as the offroad alert
API = 3

# the gadget owner, as manager names the process and selfdrived lists it
OWNER = 'jetlinkd'

# the Jetlink setting, stored as an index: jetlink.openpilot.MODES,
# written out so the panels build the setting without a jetlink checkout
MODES = ('off', 'usb', 'ios')

# the params jetlink reads and writes, all declared in params_keys.h. big_model
# and catalog are Highland's model manager's (openpilot/selfdrive/modelmanager),
# the keys zoompilot's adapter names: the pick ({ref, displayName, ...}) and the
# big-model catalog it caches
_Keys = namedtuple('_Keys', 'link offroad progress spec pointers big_model catalog charge_phone')
KEYS = _Keys(link='JetlinkLink', offroad='IsOffroad', progress='AcceleratorProgress', spec='JetlinkSpec',
             pointers='JetlinkModelPointers', big_model='ModelManager_ActiveBundleChestnut',
             catalog='ModelManager_ModelsCache_Chestnut', charge_phone='JetlinkChargePhone')

# every key this adapter declares in params_keys.h, and its type there
JSON_KEYS = frozenset({KEYS.progress, KEYS.spec, KEYS.pointers, KEYS.big_model, KEYS.catalog})
INT_KEYS = frozenset({KEYS.link})
BOOL_KEYS = frozenset({KEYS.charge_phone})

# the offroad alert reason() feeds (params_keys.h, alerts_offroad.json), zoompilot's name
OFFROAD_ALERT = 'Offroad_AcceleratorUnavailable'

# jetlink's power-off request (jetlink.comma.gadget.SHUTDOWN_REQUEST), written
# out: with the link off, shutdown_step() asks jetlink only while one is there
SHUTDOWN_REQUEST = Path('/dev/shm/jetlink-shutdown')

_AGNOS = os.path.isfile('/AGNOS')


def _params_dir() -> Path:
  """The params store's directory, by params.cc and hw.h's rule: PARAMS_ROOT,
  else /data/params on a device and ~/.comma<OPENPILOT_PREFIX>/params
  elsewhere, then /<OPENPILOT_PREFIX, or d>. Stock.params_dir() without
  jetlink. Per call, so it follows a prefix as Params does; the environment
  only, so it never raises."""
  prefix = os.environ.get('OPENPILOT_PREFIX', '')
  root = os.environ.get('PARAMS_ROOT')
  if root is None:
    root = '/data/params' if _AGNOS else os.path.join(os.environ.get('HOME', ''), '.comma' + prefix, 'params')
  return Path(root) / os.environ.get('OPENPILOT_PREFIX', 'd')


def link_mode_file() -> int:
  """The setting off the params file alone (no Params, no imports)."""
  v = file_get(KEYS.link)
  return v if isinstance(v, int) and 0 <= v < len(MODES) else 0


def _link_on() -> bool:
  """Is the Jetlink setting on? As jetlink reads it, a file, so that a jetlink
  this build cannot use tells only someone who turned the link on."""
  return link_mode_file() != 0


@functools.cache
def _adapter_class():
  from jetlink.openpilot.interface import Keys
  from jetlink.openpilot.stock import Stock

  class Adapter(Stock):
    """jetlink.openpilot.interface.Openpilot over Highland: stock openpilot
    but for what follows."""
    KEYS = Keys(**KEYS._asdict())

    @property
    def catalog_selector(self) -> int:
      # the model manager's REQUIRED_JSON_VERSION, as zoompilot's adapter returns
      from openpilot.selfdrive.modelmanager import REQUIRED_JSON_VERSION
      return REQUIRED_JSON_VERSION

    def get(self, key: str):
      # read from hardwared's and the UI's threads, which UnknownKeyName (a
      # params library older than the key) must not take down
      try:
        value = self._params().get(key)
      except Exception:
        value = file_get(key)
      if value is None and key == KEYS.catalog:
        return default_catalog()
      return value

    def put(self, key: str, value, *, block: bool = False) -> None:
      try:
        self._params().put(key, value, block=block)
      except Exception:
        file_put(key, value)

    def remove(self, key: str) -> None:
      try:
        self._params().remove(key)
      except Exception:
        file_remove(key)

    def chestnut_present(self) -> bool:
      # modeld's own test, the one it runs the big model on (as zoompilot)
      from openpilot.selfdrive.modeld.helpers import chestnut_present
      return chestnut_present()

    @classmethod
    def main(cls) -> None:
      # boot-time guard: AGNOS's ADB gadget (g1) holds the USB controller while
      # AdbEnabled is set, and jetlink-root.sh refuses to take it from g1, so
      # the phone never sees a device. jetlinkd only runs with the link on
      release_adb()
      super().main()

  return Adapter


def adapter():
  """The adapter, for jetlink's entry points that run as their own process:
  the provisioning run."""
  return _adapter_class()()


def owner_config():
  """What jetlinkd needs: data only, so the owner imports nothing heavy."""
  return _adapter_class().owner_config()


def main() -> None:
  """jetlinkd: hold the USB gadget until manager stops this process."""
  _adapter_class().main()


def __getattr__(name: str):
  # ja.Adapter, the class, made on first use: the top level stays the standard library
  if name == 'Adapter':
    return _adapter_class()
  raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_catalog() -> dict | None:
  """Until the model manager has fetched a catalog (a first boot offline):
  one listing only jetlink's default big model, so jetlink provisions that as
  it did before Highland had a model manager rather than waiting for a list."""
  try:
    from jetlink.registry.catalog import DEFAULT_BIG_MODEL_NAME, DEFAULT_BIG_MODEL_REF
    from openpilot.selfdrive.modelmanager import REQUIRED_JSON_VERSION
  except Exception:
    return None
  return {'bundles': [{'ref': DEFAULT_BIG_MODEL_REF, 'display_name': DEFAULT_BIG_MODEL_NAME, 'index': 0,
                       'minimum_selector_version': str(REQUIRED_JSON_VERSION)}]}


# -- params without the params library ---------------------------------------
# The byte format is params.cc's: b"1"/b"0" for a BOOL, decimal ASCII for an
# INT, the JSON text for a JSON. Written to a temp file and renamed over the
# key, as params.cc does, so jetlink's FileParams never reads a torn value.

def file_get(key: str):
  try:
    raw = (_params_dir() / key).read_bytes()
  except OSError:
    return None
  try:
    if key in JSON_KEYS:
      import json
      return json.loads(raw)
    if key in INT_KEYS:
      return int(raw)
    if key in BOOL_KEYS:
      return raw.strip() in (b'1', b'true', b'True')
    return raw
  except Exception:
    return None


def file_put(key: str, value) -> None:
  if key in JSON_KEYS:
    import json
    raw = json.dumps(value).encode()
  elif key in BOOL_KEYS:
    raw = b'1' if value else b'0'
  elif key in INT_KEYS:
    raw = str(int(value)).encode()
  else:
    raw = value if isinstance(value, bytes) else str(value).encode()
  where = _params_dir()
  where.mkdir(parents=True, exist_ok=True)
  tmp = where / f'.tmp_{key}_{os.getpid()}'
  with open(tmp, 'wb') as f:
    f.write(raw)
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, where / key)


def file_remove(key: str) -> None:
  try:
    (_params_dir() / key).unlink()
  except OSError:
    pass


def link_mode() -> int:
  """The Jetlink setting as an index into MODES; 0 (off) when unset, unknown
  to the params library, or unreadable. Never raises: the UI calls it."""
  try:
    from openpilot.common.params import Params
    value = Params().get(KEYS.link)
  except Exception:
    value = file_get(KEYS.link)
  try:
    value = int(value)
  except (TypeError, ValueError):
    return 0
  return value if 0 <= value < len(MODES) else 0


def set_link_mode(index: int) -> None:
  """Write the Jetlink setting; the raw file when Params rejects the key."""
  index = int(index) if 0 <= int(index) < len(MODES) else 0
  try:
    from openpilot.common.params import Params
    Params().put(KEYS.link, index, block=True)
  except Exception:
    file_put(KEYS.link, index)
  if index != 0:
    release_adb(link_on=True)


# -- ADB and the USB port -------------------------------------------------------
# ADB and Jetlink both need the comma's USB port. As in zoompilot
# (ui_state_zp._enforce_usb_port): the link on turns ADB off, and the developer
# panel greys the ADB toggle out. AGNOS tears its ADB gadget down when the
# param goes false; jetlink's owner retries the port every GADGET_HELD_RETRY
# (2 s) while that gadget still holds it.
ADB_KEY = 'AdbEnabled'


_adb_blocked_cache: list = [-1e9, False]   # [when read (monotonic), answer]


def adb_blocked(max_age: float = 0.0) -> bool:
  """The link is on, so ADB must stay off. File read only; never raises.
  max_age > 0 reuses an answer that young, for a per-frame UI check."""
  try:
    import time
    now = time.monotonic()
    if max_age > 0 and now - _adb_blocked_cache[0] < max_age:
      return _adb_blocked_cache[1]
    _adb_blocked_cache[:] = [now, link_mode_file() != 0]
    return _adb_blocked_cache[1]
  except Exception:
    return False


def release_adb(link_on: bool = False) -> bool:
  """With the link on, turn ADB off if it is on. True when it changed
  AdbEnabled. link_on skips reading the setting back (the toggle just wrote
  it). Never raises: the UI, the toggle and jetlinkd call it."""
  try:
    if not link_on and not adb_blocked():
      return False
    try:
      from openpilot.common.params import Params
      params = Params()
      if not params.get_bool(ADB_KEY):
        return False
      params.put_bool(ADB_KEY, False, block=True)
    except Exception:
      if (_params_dir() / ADB_KEY).read_bytes().strip() not in (b'1', b'true', b'True'):
        return False
      file_put(ADB_KEY, b'0')
    try:
      from openpilot.common.swaglog import cloudlog
      cloudlog.warning("jetlink: turned ADB off, Jetlink holds the USB port")
    except Exception:
      pass
    return True
  except Exception:
    return False


# -- the hooks ----------------------------------------------------------------

# this process's hooks, made on first use and kept, the link off included:
# Python does not cache a failed import. One per process, so that prepare()
# and attach() reach the same jetlink
_hooks = None
_making = threading.Lock()


def hooks():
  """jetlink.openpilot.hooks.Hooks over this adapter, or the link off."""
  global _hooks
  with _making:
    if _hooks is None:
      _hooks = _guard()
    return _hooks


def _guard():
  # inside a function, so a jetlink that fails to import lands here too
  try:
    import jetlink
    if getattr(jetlink, '__file__', None) is None:
      return _Off()   # an empty jetlink_repo, which Python takes for a namespace package
    from jetlink.openpilot.hooks import Hooks
  except ModuleNotFoundError as e:
    if e.name == 'jetlink':
      return _Off()   # no checkout: the link does not exist on this device
    if (e.name or '').startswith('jetlink.'):
      return _unusable("jetlink package too old for this build", e)
    return _unusable(f"jetlink failed to load: {e}", e)
  except Exception as e:
    return _unusable(f"jetlink failed to load: {type(e).__name__}: {e}", e)
  try:
    return Hooks(API, adapter, link_on=_link_on, log=_cloudlog)
  except Exception as e:
    return _unusable(str(e), e)   # another API, which it names


def _cloudlog():
  from openpilot.common.swaglog import cloudlog
  return cloudlog


def _unusable(why: str, error: Exception) -> _Off:
  try:
    _cloudlog().error("jetlink: %s", why, exc_info=error)
  except Exception:
    pass
  return _Off(why)


class _Off:
  """Every hook with the link off; reason() says why, to someone who turned
  the link on. The fork's own: jetlink's Off cannot answer for a jetlink that
  is missing or too old to have it, and one answer for every case keeps them
  alike. A wanted power-off goes ahead: no jetlink must keep a comma on to
  drain the car's battery."""
  # by hook; a callable is handed the hook's arguments
  ANSWERS = {'should_run': False, 'status': None, 'prepare': False, 'attach': lambda model, *_: model,
             'handed_over': False, 'state': 'none', 'shutdown_step': lambda wanted, reason='': wanted,
             'model_state': None, 'should_extend_catalog': False, 'extend_catalog': lambda catalog: catalog,
             'swap_events': None, 'runtime': None}

  def __init__(self, why: str = ''):
    self.why = why

  def reason(self) -> str | None:
    return self.why if self.why and _link_on() else None

  def __getattr__(self, name: str):
    if name not in self.ANSWERS:
      raise AttributeError(name)
    answer = self.ANSWERS[name]
    return answer if callable(answer) else lambda *args: answer


OFF = _Off()

# The hook lines' functions. Highland: those an always-running process calls
# (manager, modeld, hardwared, selfdrived, the UI) read the setting's file
# first and answer as the link off without importing jetlink; with it on, each
# is this process's hooks(), whose answers jetlink.openpilot.hooks documents.


def should_run(started: bool, params, CP) -> bool:
  """manager's rule for jetlinkd: the link is on and no chestnut is fitted.
  jetlinkd runs onroad too: a gadget whose owner exits leaves the bus."""
  return link_mode_file() != 0 and hooks().should_run(started, params, CP)


def status():
  """One snapshot for the UI and the panels (jetlink.openpilot.Status), or
  None with the link off or no jetlink here."""
  return hooks().status() if link_mode_file() != 0 else None


def reason() -> str | None:
  """Why the link the user turned on cannot run: hardwared's offroad alert.
  Files only, so hardwared can ask twice a second."""
  return hooks().reason() if link_mode_file() != 0 else None


def runtime():
  """What modeld runs, from its runtime record (jetlink.openpilot.status.Runtime),
  or None with the link off."""
  return hooks().runtime() if link_mode_file() != 0 else None


def prepare(chestnut: bool) -> bool:
  """modeld, before config_realtime_process: will the link join this modeld?
  Never beside a chestnut, which runs the large model itself."""
  return not chestnut and link_mode_file() != 0 and hooks().prepare(chestnut)


def attach(model, small, cam_w: int, cam_h: int):
  """modeld, once the camera is up and `small` is built: the joining model
  when prepare() said yes in this process, `model` otherwise."""
  if _hooks is None or small is None:
    return model
  return hooks().attach(model, small, cam_w, cam_h)


# the joining model's handovers as modeld last saw them
_handovers = 0


def handed_over(model) -> bool:
  """modeld, after every run(): did it change which model drives? Jetlink's
  own rule (Jetlink.handed_over), which reads the model alone: modeld asks
  every frame, link on or off, so it imports nothing."""
  global _handovers
  handovers = getattr(model, 'handovers', 0)
  changed, _handovers = handovers != _handovers, handovers
  return changed


def state(model) -> str:
  """The joining model's state (jetlink STATES), else none."""
  try:
    return str(getattr(model, 'big_model_state', 'none'))
  except Exception:
    return 'none'


def shutdown_step(wanted: bool, reason: str = '') -> bool:
  """hardwared, every loop from boot: ask the far end to power off with the
  comma once `wanted`, and say when the comma may go (True). With the link off
  and no request of jetlink's pending, `wanted` itself, without jetlink."""
  if link_mode_file() == 0 and _hooks is None and not SHUTDOWN_REQUEST.exists():
    return wanted
  return hooks().shutdown_step(wanted, reason)


def swap_events(tick_s: float):
  """selfdrived's swap-event tracker (jetlink.openpilot.hooks.SwapTracker),
  built once per selfdrived; None with the link off."""
  return hooks().swap_events(tick_s) if link_mode_file() != 0 else None


def model_state(ref: str) -> str | None:
  """The big-model list, when it opens: 'ready' when the Jetson has built the
  model, 'downloaded' when its file is on the comma, else None."""
  return hooks().model_state(ref)


def should_extend_catalog() -> bool:
  """Should the big-model catalog carry the models newer catalogs list?
  Hardware, not the link setting: the model manager drops a pick its catalog
  does not list."""
  return hooks().should_extend_catalog()


def extend_catalog(catalog: dict) -> dict:
  """The big-model catalog with those models folded in."""
  return hooks().extend_catalog(catalog)


def jetlink_available() -> bool:
  """Is a jetlink this build can use checked out here? (Binds nothing.)"""
  return not isinstance(hooks(), _Off)


HOOK_NAMES = (*_Off.ANSWERS, 'reason')


# -- the UI's view (Highland) ----------------------------------------------------
# As in zoompilot, the UI reads jetlink's own Status (status(), above) and the
# runtime record modeld's joining model writes (runtime(): jetlink's
# /dev/shm/jetlink/modeld.json); Highland writes no live file of its own.


def charge_phone() -> bool:
  try:
    from openpilot.common.params import Params
    return bool(Params().get_bool(KEYS.charge_phone))
  except Exception:
    return file_get(KEYS.charge_phone) is True


def set_charge_phone(on: bool) -> None:
  try:
    from openpilot.common.params import Params
    Params().put_bool(KEYS.charge_phone, bool(on), block=True)
  except Exception:
    file_put(KEYS.charge_phone, bool(on))
