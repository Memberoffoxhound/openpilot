"""The one store: per-day totals in the DriveSummaryLast param, and every number the UI shows from it.

  {"v": 2, "days": {"2026-10-29": [m, e], ...}, "life": [m, e], "record_m": m, "streak_max": n,
   "last": drive, "open": [drive, ...]}

m is meters driven, e meters engaged. days keeps DAYS_KEEP days; life, record_m (best stretch) and
streak_max outlive that. open: drives not in days yet (the one in progress, or one that ended on a
stale clock), so a UI restart or another process still sees them.

A drive is stamped when it ends: "end" (UTC seconds), "off" (the zone's UTC offset then, seconds) and
"ok" (the clock was valid). Its day is the local date at end + off, so a later zone change never moves it.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo

from openpilot.common.params_compat import get_json, put_json

PARAM = "DriveSummaryLast"
VER = 2
DAYS_KEEP = 400
STREAK_E = 1.0                       # meters engaged for a day to count toward the streak


def offset(wall: float, tz: tzinfo | None = None) -> int:
  """UTC offset of tz (None: the system zone) at wall, in seconds."""
  return int(datetime.fromtimestamp(wall, UTC).astimezone(tz).utcoffset().total_seconds())


def day_key(end: float, off: int) -> str:
  return datetime.fromtimestamp(end + off, UTC).date().isoformat()


def stamp(drive: dict, wall: float, tz: tzinfo | None = None, ok: bool = True) -> dict:
  return {**drive, "end": wall, "off": offset(wall, tz), "ok": ok}


def engaged_pct(eng: float, meters: float) -> int:
  return int(round(100.0 * eng / meters)) if meters > 1 else 0


def _try(fn, *args):
  try:
    return fn(*args)
  except Exception:
    return None


def _pair(v) -> list[float]:
  return [float(v[0]), float(v[1])]


def _day(k: str, v) -> list[float]:
  date.fromisoformat(k)
  return _pair(v)


def _drive(d) -> dict:
  return {**d, "m": float(d["m"]), "e": float(d["e"]), "best_m": float(d.get("best_m") or 0),
          "end": float(d["end"]), "off": int(d["off"]), "ok": bool(d.get("ok"))}


def load(params) -> dict:
  """The store, or a fresh one if it's missing, from another version or unreadable. A bad entry drops alone."""
  raw = _try(get_json, params, PARAM) or {}
  data = {"v": VER, "days": {}, "life": [0.0, 0.0], "record_m": 0.0, "streak_max": 0, "open": []}
  if raw.get("v") != VER:
    return data
  for k, v in _try(lambda: list(raw["days"].items())) or []:
    if (pair := _try(_day, k, v)) is not None:
      data["days"][k] = pair
  data["life"] = _try(_pair, raw.get("life")) or data["life"]
  data["record_m"] = _try(float, raw.get("record_m")) or 0.0
  data["streak_max"] = _try(int, raw.get("streak_max")) or 0
  data["open"] = [d for o in _try(list, raw.get("open")) or [] if (d := _try(_drive, o))]
  if (last := _try(_drive, raw.get("last"))) is not None:
    data["last"] = last
  return data


def save(params, data: dict) -> None:
  put_json(params, PARAM, data)


def add_drive(data: dict, drive: dict) -> dict:
  """A new store with a stamped drive counted on its local day, days older than DAYS_KEEP dropped."""
  m, e = drive["m"], drive["e"]
  k = day_key(drive["end"], drive["off"])
  cut = (date.fromisoformat(k) - timedelta(days=DAYS_KEEP)).isoformat()
  days = {d: v for d, v in data["days"].items() if d > cut}
  m0, e0 = days.get(k, (0.0, 0.0))
  days[k] = [round(m0 + m, 1), round(e0 + e, 1)]
  return {**data, "days": days, "life": [round(data["life"][0] + m, 1), round(data["life"][1] + e, 1)],
          "record_m": round(max(data["record_m"], drive["best_m"]), 1),
          "streak_max": max(data["streak_max"], streaks(days, date.fromisoformat(k))[1]), "last": drive}


def streaks(days: dict, today: date) -> tuple[int, int]:
  """(current, longest) runs of consecutive days engaged. Current ends today, or yesterday until today counts."""
  on = {date.fromisoformat(k) for k, (_, e) in days.items() if e > STREAK_E}
  longest = 0
  for d in on:
    if d - timedelta(days=1) not in on:      # a run starts here
      n = 1
      while d + timedelta(days=n) in on:
        n += 1
      longest = max(longest, n)
  d, cur = today if today in on else today - timedelta(days=1), 0
  while d in on:
    d, cur = d - timedelta(days=1), cur + 1
  return cur, longest


def view(data: dict, open_drives=(), at: datetime | None = None, tz: tzinfo | None = None) -> dict:
  """Day, Week (from Sunday), the week's days, six months, lifetime, streaks, best stretch, in tz
  (None: the system zone). Open drives count today."""
  now = (at or datetime.now(UTC)).timestamp()
  for d in open_drives:
    data = add_drive(data, stamp(d, now, tz))
  days, today = data["days"], date.fromisoformat(day_key(now, offset(now, tz)))
  sunday = today - timedelta(days=(today.weekday() + 1) % 7)
  week = []
  for k in ((sunday + timedelta(days=i)).isoformat() for i in range(7)):
    m, e = days.get(k, (0.0, 0.0))
    week.append({"id": k, "m": m, "e": e})
  ym = today.year * 12 + today.month - 1
  months = []
  for i in range(5, -1, -1):
    mk = f"{(ym - i) // 12:04d}-{(ym - i) % 12 + 1:02d}"
    sel = [v for k, v in days.items() if k.startswith(mk)]
    months.append({"id": mk, "m": sum(v[0] for v in sel), "e": sum(v[1] for v in sel), "current": i == 0})
  tm, te = days.get(today.isoformat(), (0.0, 0.0))
  wm, we = sum(d["m"] for d in week), sum(d["e"] for d in week)
  (lm, le), (cur, longest) = data["life"], streaks(days, today)
  return {"today_m": tm, "today_e": te, "today_pct": engaged_pct(te, tm),
          "week_m": wm, "week_e": we, "week_pct": engaged_pct(we, wm), "week_days": week, "today_i": (today - sunday).days,
          "months": months,
          "life_m": lm, "life_e": le, "pct": engaged_pct(le, lm), "longest_m": data["record_m"],
          "streak_days": max(data["streak_max"], longest), "streak_now": cur}
