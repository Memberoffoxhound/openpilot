> User-facing README: [README.md](README.md). This file is Highland working notes only.

# S3XYPilot — Highland

Working branch. Version **0.11.23**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror.

## Params

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph after Tesla BSM is clear. Warning + slide-to-enable. rav4kumar / sunnypilot. |
| `LaneColor` | tesla | `0` Openpilot green, `1` Tesla Autopilot blue (lanes, wheel, confidence, compass, DM). |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. |
| `VSlamEnabled` | on | Green-pill toggle. Off stops detect + log + toast. File `/data/vslam/enabled`. |
| Delorean (`/data/delorean_sound`) | off | 88mph on going onroad. 1.5s stable, ignore <10s ignition blips. |

## Trip files

| Path | Role |
|---|---|
| `/data/trip_meter.json` + `TripMeter` param | Live Today/Week. Boot reads this. |
| `/data/trip_seed_cache.json` | Per-segment meters, filled parked after a drive. |
| `/data/trip_stats.json` | Lifetime miles, all-time day streak, longest stretch, monthly totals. Survives qlog purge. |

Chicago local for day/week. UI thread never LogReader.
Today keeps a `pending` overlay across park and new routes until the qlog fold absorbs those miles. Park cache waits `HOT_SEC+5` (125s) so the drive that just ended is readable.

## Alpha longitudinal (stock)

A 2026 Model 3 Highland fingerprints as `TESLA_MODEL_3`. Stock master sets `alphaLongitudinalAvailable = True`.

- Visible on development branches (`AlphaLongitudinalEnabled` is `DEVELOPMENT_ONLY`).
- Can change onroad while not engaged. Cannot while engaged.
- Change requests an onroad cycle (`OnroadCycleRequested`) so panda safety reinits.

Tesla stock ACC until this is on. Experimental is gated on openpilot long.

## vSlam tracker

`vslam_d` (onroad only) logs every cruise-set drop ≥ 6 mph. Observe-only — no panda / actuation change.

Each event keeps **5 s before detect and 5 s after recovery** (or timeout / cruise-off). `vslam_d` holds the write until the post-recovery window is in the ring buffer.

| Path | Role |
|---|---|
| `/data/vslam/events.jsonl` | Event index (route, GPS, place, pre/slam/recover, local time, compact spark) |
| `/data/vslam/traces/<id>.json` | 5s+event+5s vCruise vs planner vPlan + GPS + G (lon/lat/|g|) |

C4: Settings → vSlam (green-pill logger toggle + list + sparkline) and Settings → toggles. LAN: deviceweb `:8088` → **vSlam tracker**. Event list shows the mph drop up top-right with a mini spark under it. Map / spark is green when nominal, red→yellow during the slam (red = slowest slam speed, yellow = highest in the window).

On detect, C4 throws a 3s orange `userPrompt` toast: **vSlam logged**. Observe-only — stamped via `/data/vslam/alert_until`, not selfdrived / panda.

## Screenshots / LAN

Hold display 3s → `/data/media/0/screenshots`. `deviceweb` on **8088**, no auth.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
