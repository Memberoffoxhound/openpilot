import time
import requests
from dataclasses import asdict, dataclass, field

from openpilot.common.params import Params


WEBRTCD_PORT = 5001

# PrimeType from prime_state.py. Magenta/Blue/Purple include comma cellular data.
# Lite is bring-your-own SIM.
_COMMA_DATA_PRIME = {1, 3, 4, 5}  # MAGENTA, BLUE, MAGENTA_NEW, PURPLE


def livestream_network_ok(params: Params | None = None) -> bool:
  """Wi-Fi / unmetered, or cellular on a non-Prime (BYO) SIM. Not comma's LTE plan."""
  params = params or Params()
  if not params.get_bool("NetworkMetered"):
    return True
  try:
    prime = int(params.get("PrimeType") or 0)
  except (TypeError, ValueError):
    prime = 0
  return prime not in _COMMA_DATA_PRIME


def on_air_block_reason(params: Params | None = None, network_none: bool = False) -> str | None:
  """Why On-Air cannot enable. None = allowed. 'offline' | 'prime'."""
  if network_none:
    return "offline"
  if livestream_network_ok(params):
    return None
  return "prime"


@dataclass
class StreamRequestBody:
  sdp: str
  cameras: list[str]
  enabled: bool
  bridge_services_in: list[str] = field(default_factory=list)
  bridge_services_out: list[str] = field(default_factory=list)


def post_stream_request(body: StreamRequestBody) -> dict:
  t_start = time.monotonic()
  try:
    resp = requests.post(f"http://localhost:{WEBRTCD_PORT}/stream", json=asdict(body), timeout=10)
    t_end = time.monotonic()
    ret = resp.json()
    ret["time"] = (t_end - t_start) * 1000
    return ret
  except requests.ConnectTimeout as e:
    raise Exception("device took too long to respond.") from e
  except requests.ConnectionError as e:
    raise Exception("livestream encoder is not up yet. retry in a few seconds.") from e


def wait_for_webrtcd(max_retries: float = 30) -> None:
  attempts = 0
  while attempts < max_retries:
    try:
      if requests.get(f"http://localhost:{WEBRTCD_PORT}/schema", timeout=1).ok:
        return
    except requests.ConnectionError:
      attempts += 1
      time.sleep(0.5)
  raise TimeoutError("livestreaming service did not initialize in time.")
