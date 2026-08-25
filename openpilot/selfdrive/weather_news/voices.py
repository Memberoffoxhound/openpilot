"""Weather news TTS picker. Scale is how human it sounds, not quality of the script."""

from openpilot.common.params import Params

IDS = ("gps", "high", "human")
LABELS = ("gps · 3/10", "high · 5/10", "human · 8/10")
DEFAULT = "high"
BLURB = {
  "gps": "3/10 human · GPS. Fast, small.",
  "high": "5/10 human · newsreader. Default.",
  "human": "8/10 human · a person. Heavier. First tap downloads ~150 MB.",
}


def get(params: Params | None = None) -> str:
  params = params or Params()
  try:
    v = params.get("WeatherNewsVoice")
    s = str(v).strip().lower() if v else ""
  except Exception:
    s = ""
  return s if s in IDS else DEFAULT


def set(vid: str, params: Params | None = None) -> None:
  params = params or Params()
  params.put("WeatherNewsVoice", vid if vid in IDS else DEFAULT, block=True)


def display(vid: str | None = None, params: Params | None = None) -> str:
  v = vid if vid in IDS else get(params)
  return LABELS[IDS.index(v)]


def id_from_display(label: str) -> str:
  if label in LABELS:
    return IDS[LABELS.index(label)]
  return DEFAULT
