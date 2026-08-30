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
| Delorean (`/data/delorean_sound`) | off | 88mph on going onroad. 1.5s stable, ignore <10s ignition blips. |
| `DrivingModelSelected` | `release` | Active driving model id. `release` / `release-egpu` use the bundled pkl. Master/favorite ids live under `/data/sexypilot/models/{id}/`. |
| `DrivingModelInstallStatus` | `{}` | On-demand download/compile progress. Cleared on manager start. |

## Driving model selector

Settings → **driving model** (first C4 widget). Home branch label shows the selected model name.

- Openpilot Release is always available (bundled). No prefetch of master ONNX.
- Model updater pulls the last 3 comma master bumps of `driving_supercombo.onnx`.
- Star a master model to keep it (5 regular + 5 eGPU). Unstarred masters rotate out of the last-3 window and their files are pruned.
- eGPU / Chestnut models only appear when Chestnut is present, with an eGPU badge. Separate 3+5 pools.
- Select or star starts download + on-device compile. Progress is shown in the widget. Switch requests an onroad cycle.
- Compile uses stock `compile_modeld.py`. Shape mismatch falls back to the bundled model.

## Trip files

| Path | Role |
|---|---|
| `/data/trip_meter.json` + `TripMeter` param | Live Today/Week. Boot reads this. |
| `/data/trip_seed_cache.json` | Per-segment meters, filled parked after a drive. |
| `/data/trip_stats.json` | Lifetime miles, all-time day streak, longest stretch, monthly totals. Survives qlog purge. |

Chicago local for day/week. UI thread never LogReader.

## Alpha longitudinal (stock)

A 2026 Model 3 Highland fingerprints as `TESLA_MODEL_3`. Stock master sets `alphaLongitudinalAvailable = True`.

- Visible on development branches (`AlphaLongitudinalEnabled` is `DEVELOPMENT_ONLY`).
- Can change onroad while not engaged. Cannot while engaged.
- Change requests an onroad cycle (`OnroadCycleRequested`) so panda safety reinits.

Tesla stock ACC until this is on. Experimental is gated on openpilot long.

## Screenshots / LAN

Hold display 3s → `/data/media/0/screenshots`. `deviceweb` on **8088**, no auth.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
