"""Dated live/pending overlay helpers."""
from __future__ import annotations

from datetime import datetime, timedelta

from openpilot.selfdrive.ui.layouts.settings.trip_seed import _f, chicago_now, day_id


def empty_live() -> dict:
  return {"route": "", "day": "", "m": 0.0, "e": 0.0, "streak_m": 0.0}


def empty_pending() -> dict:
  return {"day": "", "m": 0.0, "e": 0.0}


def normalize_live(raw) -> dict:
  live = empty_live()
  if not isinstance(raw, dict):
    return live
  live["route"] = str(raw.get("route") or "")
  live["day"] = str(raw.get("day") or "")
  live["m"] = _f(raw, "m")
  live["e"] = _f(raw, "e")
  live["streak_m"] = _f(raw, "streak_m")
  return live


def normalize_pending(raw) -> dict:
  pending = empty_pending()
  if not isinstance(raw, dict):
    return pending
  pending["day"] = str(raw.get("day") or "")
  pending["m"] = max(0.0, _f(raw, "m"))
  pending["e"] = max(0.0, _f(raw, "e"))
  return pending


def yesterday_id(today: str | None = None) -> str:
  raw = today or day_id()
  try:
    d = datetime.strptime(raw, "%Y-%m-%d").date()
  except ValueError:
    d = chicago_now().date()
  return (d - timedelta(days=1)).isoformat()


def overlay_day(stamp: str, today: str, allow_today_guess: bool) -> str:
  if stamp:
    return stamp
  return today if allow_today_guess else yesterday_id(today)


def add_pending(dst: dict, meters: float, eng: float, day: str = "") -> dict:
  pending = normalize_pending(dst)
  meters = max(0.0, float(meters or 0))
  eng = max(0.0, float(eng or 0))
  if meters <= 0 and eng <= 0:
    return pending
  src_day = str(day or pending.get("day") or day_id())
  pending["m"] = _f(pending, "m") + meters
  pending["e"] = _f(pending, "e") + eng
  if not pending.get("day"):
    pending["day"] = src_day
  return pending


def day_bucket(days: dict, key: str) -> dict:
  b = days.get(key)
  if not isinstance(b, dict):
    b = {"m": 0.0, "e": 0.0}
    days[key] = b
  return b


def commit_overlay(days: dict, months: dict, prev_days: dict, key: str,
                   extra_m: float, extra_e: float) -> tuple[float, float]:
  extra_m = max(0.0, float(extra_m or 0))
  extra_e = max(0.0, float(extra_e or 0))
  if not key or (extra_m <= 0 and extra_e <= 0):
    return 0.0, 0.0
  b = day_bucket(days, key)
  prev_b = prev_days.get(key) if isinstance(prev_days.get(key), dict) else {}
  want_m = _f(prev_b, "m") + extra_m
  want_e = _f(prev_b, "e") + extra_e
  add_m = max(0.0, want_m - _f(b, "m"))
  add_e = max(0.0, want_e - _f(b, "e"))
  if add_m <= 0 and add_e <= 0:
    return 0.0, 0.0
  b["m"] = _f(b, "m") + add_m
  b["e"] = _f(b, "e") + add_e
  mb = day_bucket(months, key[:7])
  mb["m"] = _f(mb, "m") + add_m
  mb["e"] = _f(mb, "e") + add_e
  return add_m, add_e
