"""WeatherNewsMode: 0 off, 1 nice, 2 aggressive (UI: Unhinged)."""

from openpilot.common.params import Params

OFF, NICE, AGGRESSIVE = 0, 1, 2
LABELS = ("off", "nice", "unhinged")


def get(params: Params | None = None) -> int:
  params = params or Params()
  try:
    v = params.get("WeatherNewsMode", return_default=True)
    if v is None:
      return NICE
    return max(OFF, min(AGGRESSIVE, int(v)))
  except Exception:
    return NICE


def set(mode: int, params: Params | None = None) -> None:
  params = params or Params()
  params.put("WeatherNewsMode", max(OFF, min(AGGRESSIVE, int(mode))), block=True)


def request_preview(params: Params | None = None) -> bool:
  params = params or Params()
  mode = get(params)
  if mode == OFF:
    return False
  params.put("WeatherNewsPreview", "aggressive" if mode == AGGRESSIVE else "nice", block=True)
  try:
    params.put("WeatherNewsStatus", "queued", block=True)
  except Exception:
    pass
  return True


def status_text(params: Params | None = None) -> str:
  params = params or Params()
  try:
    v = params.get("WeatherNewsStatus")
    return str(v).strip() if v else ""
  except Exception:
    return ""
