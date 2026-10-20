"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
Ported to Highland (Memberoffoxhound/openpilot) from zoompilot develop
(openpilot/sunnypilot/jetlink_adapter). Highland changes, in short:
  - lives at openpilot/selfdrive/jetlink_adapter (no sunnypilot tree here)
  - Highland's model manager (openpilot/selfdrive/modelmanager) is a cut-down
    port of sunnypilot's: Keys.big_model / Keys.catalog are its params, as on
    zoompilot, and catalog_selector is its REQUIRED_JSON_VERSION (20). Until
    it has fetched a catalog, get() answers one listing jetlink's default
  - in_control reads carState/carControl only (no MADS / carControlSP)
  - warp and model constants come from stock selfdrive/modeld
  - get/put/remove fall back to the raw params files when the params library
    on the device predates the Jetlink keys (UnknownKeyName), so a stale
    prebuilt params_pyx.so can never crash-loop anything (cf. 583cce9)

jetlink on this fork: the one module that holds every openpilot import
jetlink needs, and the functions the hooks call.

jetlink (the jetlink_repo submodule) runs the large driving model on an
attached Jetson, Mac or iPhone and never imports openpilot. It defines what it
needs as an interface (jetlink.openpilot.interface.Openpilot), and Adapter
below implements it. The hooks in manager, modeld, hardwared, the model
manager and the UI call the functions at the bottom, which answer as if the
link were off when jetlink is not checked out, or speaks another API.

comma's chestnut board is not jetlink's business: modeld, hardwared and the
UI handle it natively, and jetlink keeps the link off while one is fitted.

manager imports this module to build the process list, and runs it as
jetlinkd, the resident gadget owner, which stays at about 10 MB for the whole
drive. So the top level is the standard library only; everything else is
imported where it is used. tests/test_adapter.py holds the line.
"""
from __future__ import annotations

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

# comma's chestnut, running and in its ROM (common.hardware.usb): the comma's
# USB-C port hosts one and is never held as a jetlink device beside it. The
# hardware package is too heavy for the owner, so they are written out here
CHESTNUT_IDS = frozenset({(0xADD1, 0x0001), (0x3801, 0x0001), (0x174C, 0x2464), (0x174C, 0x2463)})

# what Adapter.in_control() reads (Highland: no MADS, so no carControlSP)
IN_CONTROL = ('carState', 'carControl')

OWNER_LOG = Path('/data/log/jetlink-owner.log')

_AGNOS = os.path.isfile('/AGNOS')


def _params_dir() -> Path:
  """The params store's directory, by params.cc and hw.h's rule: PARAMS_ROOT,
  else /data/params on a device and ~/.comma<OPENPILOT_PREFIX>/params
  elsewhere, then /<OPENPILOT_PREFIX, or d>. Per call, so it follows a prefix
  as Params does; the environment only, so it never raises."""
  prefix = os.environ.get('OPENPILOT_PREFIX', '')
  root = os.environ.get('PARAMS_ROOT')
  if root is None:
    root = '/data/params' if _AGNOS else os.path.join(os.environ.get('HOME', ''), '.comma' + prefix, 'params')
  return Path(root) / os.environ.get('OPENPILOT_PREFIX', 'd')


def owner_config():
  """What jetlinkd needs: data only, so the owner imports nothing heavy."""
  from jetlink.openpilot.interface import Keys, OwnerConfig

  from openpilot.common.basedir import BASEDIR
  # the provisioning run starts in the checkout with the checkout on its path,
  # where launch_chffrplus.sh links jetlink_repo/jetlink in as jetlink
  return OwnerConfig(params_dir=_params_dir(), keys=Keys(**KEYS._asdict()), chestnut_ids=CHESTNUT_IDS,
                     adapter=__name__, cwd=Path(BASEDIR), env={'PYTHONPATH': BASEDIR}, log_file=OWNER_LOG)


def main() -> None:
  """jetlinkd: hold the USB gadget until manager stops this process."""
  # boot-time guard: AGNOS's ADB gadget (g1) holds the USB controller while
  # AdbEnabled is set, and jetlink-root.sh refuses to take it from g1, so the
  # phone never sees a device. jetlinkd only runs with the link on
  release_adb()
  from jetlink.openpilot.owner import main as run_owner
  run_owner(owner_config())


def adapter() -> Adapter:
  """The adapter, for jetlink's entry points that run as their own process:
  the provisioning run."""
  return Adapter()


class Adapter:
  """jetlink.openpilot.interface.Openpilot over this fork."""

  def __init__(self):
    from jetlink.openpilot.interface import Keys

    from openpilot.common.basedir import BASEDIR
    from openpilot.common.swaglog import cloudlog
    self.keys = Keys(**KEYS._asdict())
    self.log = cloudlog
    self.basedir = Path(BASEDIR)
    # one Params per store: constructing one costs 144 us on the comma against
    # 110 us for the read, and the UI reads several five times a second. By
    # store, since a test or a bench runs under its own prefix
    self._stores: dict[Path, object] = {}
    # in_control's, made on modeld's first frame
    self._sm = None

  # -- params ---------------------------------------------------------------

  def params_dir(self) -> Path:
    return _params_dir()

  def _params(self):
    where = _params_dir()
    store = self._stores.get(where)
    if store is None:
      from openpilot.common.params import Params
      store = self._stores[where] = Params()
    return store

  def get(self, key: str):
    # read from hardwared and the UI's threads, which UnknownKeyName (a
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

  # -- the device -------------------------------------------------------------

  def chestnut_present(self) -> bool:
    from openpilot.selfdrive.modeld.helpers import chestnut_present
    return chestnut_present()

  def camera(self) -> tuple[int, int, int, int]:
    # this device's road camera, which names the warp modeld loads
    from openpilot.common.hardware import HARDWARE
    from openpilot.common.transformations.camera import _ar_ox_fisheye, _os_fisheye
    from openpilot.common.transformations.model import MEDMODEL_INPUT_SIZE
    camera = _os_fisheye if HARDWARE.get_device_type() == "mici" else _ar_ox_fisheye
    return camera.width, camera.height, *MEDMODEL_INPUT_SIZE

  def warp_path(self, cam_w: int, cam_h: int, model_w: int, model_h: int) -> Path:
    # Highland: stock modeld's small-model warp, which scons compiles into
    # selfdrive/modeld/models (SConscript, compile_warp.py). One per camera
    from openpilot.selfdrive.modeld.helpers import MODELS_DIR
    return Path(MODELS_DIR) / f'driving_warp_{cam_w}x{cam_h}_tinygrad.pkl'

  def model_root(self) -> Path:
    # Highland has no model manager, so no Paths.model_root(); the same place
    # sunnypilot uses. jetlink keeps its downloads under <root>/jetlink
    if _AGNOS:
      return Path('/data/media/0/models')
    from openpilot.common.hardware.hw import Paths
    return Path(Paths.comma_home()) / 'media' / '0' / 'models'

  @property
  def catalog_selector(self) -> int:
    # the model manager's REQUIRED_JSON_VERSION, as zoompilot's adapter returns
    from openpilot.selfdrive.modelmanager import REQUIRED_JSON_VERSION
    return REQUIRED_JSON_VERSION

  # -- modeld -----------------------------------------------------------------

  def model_face(self):
    """comma's large model's face: stock modeld's Parser, constants and action
    function (Highland has no modeld_v2)."""
    from jetlink.openpilot.interface import ModelFace

    from openpilot.selfdrive.modeld.constants import ModelConstants
    from openpilot.selfdrive.modeld.modeld import LAT_SMOOTH_SECONDS, LONG_SMOOTH_SECONDS, get_action_from_model
    from openpilot.selfdrive.modeld.parse_model_outputs import Parser
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    return ModelFace(parser=Parser, frame_size=lambda w, h: get_nv12_info(w, h)[3], desire_len=ModelConstants.DESIRE_LEN,
                     constants=ModelConstants, lat_smooth_seconds=LAT_SMOOTH_SECONDS,
                     long_smooth_seconds=LONG_SMOOTH_SECONDS, get_action_from_model=get_action_from_model)

  def in_control(self) -> bool:
    """Is openpilot or MADS in control? The joining model asks before every
    frame and swaps its large model in only while not. selfdrived's own
    answer (enabled or mads.enabled, what accelerator_events is handed), as
    controlsd republishes it, off a SubMaster of the adapter's. MADS counts
    with its lateral paused (a stop, a blinker, the brake): it steers again on
    its own. A service late or invalid counts as in control; without carState
    a card that died would have the swap land on stale controls. A rule that
    fails holds the swap off, never modeld."""
    try:
      if self._sm is None:
        from openpilot.cereal import messaging
        self._sm = messaging.SubMaster(list(IN_CONTROL))
      sm = self._sm
      sm.update(0)
      result = not (sm.all_alive(IN_CONTROL) and sm.all_valid(IN_CONTROL)) or bool(sm['carControl'].enabled)
    except Exception as e:
      _failed('in_control', e)
      return True
    _failed_hooks.pop('in_control', None)
    return result

  def event(self, name: str, **fields) -> None:
    self.log.event(name, **fields)


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


# -- what the hooks call ------------------------------------------------------

# jetlink's answers when it cannot run here: not checked out, or a package this
# build cannot use. The link off, by Jetlink method; a callable is handed the
# hook's arguments
_DEFAULTS = {'enabled': False, 'status': None, 'reason': None, 'prepare': False, 'attach': None,
             'request_shutdown': False, 'shutdown_pending': False, 'model_state': None,
             'should_extend_catalog': False, 'extend_catalog': lambda catalog: catalog}

# jetlink for this process, or why it cannot run here ('' with no checkout);
# None until first use
_bound = None
_binding = threading.Lock()


def _api():
  """jetlink for this process, bound to the adapter on first use, or None when
  it cannot run here. Kept, the null answer included: Python does not cache a
  failed import, and searching the path again on every UI and hardwared call
  costs more than the call. One per process: prepare() and attach() have to
  reach the same one."""
  global _bound
  if _bound is None:
    with _binding:
      if _bound is None:
        _bound = _bind()
  return None if isinstance(_bound, str) else _bound


def _bind():
  try:
    import jetlink
    if getattr(jetlink, '__file__', None) is None:
      return ''   # an empty jetlink_repo, which Python takes for a namespace package
    import jetlink.openpilot as jl
  except ModuleNotFoundError as e:
    if e.name == 'jetlink':
      return ''   # no checkout: the link does not exist on this device
    if (e.name or '').startswith('jetlink.'):
      return _unusable("jetlink package too old for this build", e)
    return _unusable(f"jetlink failed to load: {e}", e)
  except Exception as e:
    return _unusable(f"jetlink failed to load: {type(e).__name__}: {e}", e)
  api = getattr(jl, 'API', None)
  if api != API:
    return _unusable(f"jetlink package API {api}, this build expects {API}")
  try:
    return jl.bind(Adapter())
  except Exception as e:
    return _unusable(f"jetlink failed to start: {type(e).__name__}: {e}", e)


def _unusable(why: str, error: Exception | None = None) -> str:
  _log_failure(why, error)
  return why


# manager, hardwared, the model manager and the UI call in here on every
# device, link on or off, and modeld on every drive: whatever jetlink does
# wrong turns the link off and is logged, and never takes one of them down.
# jetlink's own readers never raise; this is the net under that promise.
# Hook -> the failure last logged for it, cleared by a call that works
_failed_hooks: dict[str, str] = {}


def _log_failure(what: str, error: Exception | None) -> None:
  try:
    from openpilot.common.swaglog import cloudlog
    cloudlog.error("jetlink: %s", what, exc_info=error)
  except Exception:
    pass


def _failed(name: str, error: Exception) -> None:
  # once per distinct error, as jetlink's readers log: the UI would log a
  # failing status five times a second
  text = f"{type(error).__name__}: {error}"
  if _failed_hooks.get(name) != text:
    _failed_hooks[name] = text
    _log_failure(f"{name}() failed", error)


def _hook(name: str, *args):
  """Jetlink.<name>(*args), or the link off (_DEFAULTS) when jetlink cannot run
  here or raises."""
  default = _DEFAULTS[name]
  try:
    api = _api()
    if api is not None:
      result = getattr(api, name)(*args)
      _failed_hooks.pop(name, None)
      return result
  except Exception as e:
    _failed(name, e)
  return default(*args) if callable(default) else default


def should_run(started: bool, params, CP) -> bool:
  """manager's rule for jetlinkd: the link is on and no chestnut is fitted.
  jetlinkd runs onroad too: a gadget whose owner exits leaves the bus.
  Highland: the setting is read first as a file, so with the toggle off
  jetlink is never even imported."""
  if link_mode_file() == 0:
    return False
  return _hook('enabled')


def link_mode_file() -> int:
  """The setting off the params file alone (no Params, no imports)."""
  v = file_get(KEYS.link)
  return v if isinstance(v, int) and 0 <= v < len(MODES) else 0


def status():
  """One snapshot for the UI and the panels (jetlink.openpilot.Status), or
  None when there is no jetlink here."""
  return _hook('status')


def reason() -> str | None:
  """Why the link the user turned on cannot run: hardwared's offroad alert.
  Files only, so hardwared can ask twice a second."""
  if _api() is None and _bound:
    # a package this build cannot use says why, to someone who turned the
    # link on. The setting as jetlink reads it, a file
    try:
      on = 0 < int((_params_dir() / KEYS.link).read_bytes()) < len(MODES)
    except (OSError, ValueError):
      on = False
    return _bound if on else None
  return _hook('reason')


def prepare(chestnut: bool) -> bool:
  """modeld, before config_realtime_process: will the link join this modeld?
  Never beside a chestnut, which runs the large model itself. The GPU's setup
  has to happen now, or its threads inherit the frame loop's realtime
  priority and core."""
  return not chestnut and link_mode_file() != 0 and _hook('prepare')


# What jetlink's joining model (joining.py) reads off the small model that
# sunnypilot's modeld_v2 keeps on its ModelState and Highland's stock one may
# not: name -> default. lat_delay is copied onto the large model at the swap
# (an AttributeError there kept every swap from landing, 2026-10-20); the rest
# are read through the joining model's properties. Highland's modeld sets
# lat_delay itself and writes it every frame; this is the net under that.
# numpy_inputs falls back to the ModelState's own host inputs (npy).
SMALL_MODEL_DEFAULTS = {'lat_delay': 0.0, 'PLANPLUS_CONTROL': 1.0, 'desire_key': 'desire_pulse'}


def fill_small(small) -> list[str]:
  """Give `small` whatever of SMALL_MODEL_DEFAULTS and numpy_inputs it lacks,
  so no swap or later read is an AttributeError on modeld's frame thread.
  Returns the names it set. Never raises."""
  filled = []
  try:
    for name, default in SMALL_MODEL_DEFAULTS.items():
      if not hasattr(small, name):
        setattr(small, name, default)
        filled.append(name)
    if not hasattr(small, 'numpy_inputs'):
      small.numpy_inputs = getattr(small, 'npy', {})
      filled.append('numpy_inputs')
  except Exception as e:
    _failed('fill_small', e)
  return filled


def attach(model, small, cam_w: int, cam_h: int):
  """modeld, once the camera is up and `small` is built: the model to run.
  The joining model, `small` driving until the link has joined, when
  prepare() said yes; `model` otherwise."""
  if small is None or link_mode_file() == 0:
    return model
  fill_small(small)
  joined = _hook('attach', small, cam_w, cam_h)
  return model if joined is None else joined


# the joining model's handovers as modeld last saw them
_handovers = 0


def handed_over(model) -> bool:
  """modeld, after every run(): did it change which model drives? The joining
  model counts its swaps and hand-backs; the stall of one is not lag, as for
  a chestnut's fallback, and nor are the drops of the frame it happens on."""
  global _handovers
  handovers = getattr(model, 'handovers', 0)
  changed, _handovers = handovers != _handovers, handovers
  return changed


def state(model) -> str:
  """modelDataV2SP.zoompilot.acceleratorState: the joining model's, else none."""
  return getattr(model, 'big_model_state', 'none')


def request_shutdown(reason: str = '') -> bool:
  """hardwared, once, when the comma is about to power off for good: ask for
  the far end to go down with it. Returns at once: True when the request now
  waits for jetlinkd, which shutdown_pending() follows."""
  return _hook('request_shutdown', reason)


def shutdown_pending() -> bool:
  """hardwared, every loop after request_shutdown(), until it puts DoShutdown:
  has jetlinkd still to take the request? A stat."""
  return _hook('shutdown_pending')


def model_state(ref: str) -> str | None:
  """The big-model list, when it opens: 'ready' when the Jetson has built the
  model, 'downloaded' when its file is on the comma, else None."""
  return _hook('model_state', ref)


def should_extend_catalog() -> bool:
  """Should the big-model catalog carry the models newer catalogs list?
  Hardware, not the link setting: the model manager drops a pick its catalog
  does not list."""
  return _hook('should_extend_catalog')


def extend_catalog(catalog: dict) -> dict:
  """The big-model catalog with those models folded in."""
  return _hook('extend_catalog', catalog)


# -- live state for the UI (Highland) -------------------------------------------
# zoompilot carries the joining model's state in modelDataV2SP, which Highland
# lacks. Instead modeld writes one small JSON file, once a second, and only when
# the joining model is attached (Jetlink on): tmpfs on the device, so no flash
# wear and nothing left after a reboot. The UI treats a file older than
# LIVE_STALE as no live state. Fields: state (STATES name), big, exec_ms_mean,
# exec_ms_max, over_budget (frames over BUDGET_MS in the window), frames, t.

BUDGET_MS = 50.0
LIVE_PERIOD = 1.0
LIVE_STALE = 3.0


def live_path() -> Path:
  override = os.environ.get('JETLINK_LIVE_PATH')
  if override:
    return Path(override)
  base = Path('/dev/shm') if os.path.isdir('/dev/shm') else Path('/tmp')
  return base / (f"jetlink_live{os.environ.get('OPENPILOT_PREFIX', '')}.json")


class _LiveWindow:
  def __init__(self):
    self.reset(0.0)

  def reset(self, now: float):
    self.start, self.n, self.total, self.max, self.over = now, 0, 0.0, 0.0, 0


_live = _LiveWindow()


def publish_live(model, execution_time: float, now: float | None = None) -> bool:
  """modeld, after every run(): fold this frame's time into the window and, once
  a second, write the live file. A no-op (one getattr) unless the joining model
  is attached. Never raises. True when it wrote."""
  state = getattr(model, 'big_model_state', None)
  if state is None:
    return False
  try:
    import time
    now = time.monotonic() if now is None else now
    if _live.start == 0.0:
      _live.reset(now)
    ms = float(execution_time) * 1000.0
    _live.n += 1
    _live.total += ms
    _live.max = max(_live.max, ms)
    _live.over += ms > BUDGET_MS
    if now - _live.start < LIVE_PERIOD:
      return False
    import json
    record = {'state': str(state), 'big': bool(getattr(model, 'chestnut', False)),
              'exec_ms_mean': round(_live.total / max(_live.n, 1), 1), 'exec_ms_max': round(_live.max, 1),
              'over_budget': _live.over, 'frames': _live.n, 't': time.monotonic()}
    _live.reset(now)
    path = live_path()
    tmp = path.with_name(f'.{path.name}.{os.getpid()}')
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)
    return True
  except Exception as e:
    _failed('publish_live', e)
    return False


def read_live(now: float | None = None) -> dict | None:
  """The live record, or None when missing, unreadable or stale. Never raises."""
  try:
    import json
    import time
    record = json.loads(live_path().read_text())
    now = time.monotonic() if now is None else now
    if not isinstance(record, dict) or now - float(record.get('t', 0)) > LIVE_STALE:
      return None
    return record
  except Exception:
    return None


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
