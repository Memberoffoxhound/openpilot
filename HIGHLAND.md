> User-facing README: [README.md](README.md). This file is Highland working notes only.

# S3XYPilot — Highland

Working branch. Version **0.11.23**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror. Highland is the Tesla fork on current comma master.

## Onroad

Theme → onroad UI = **stock** (comma HUD) or **custom**. Custom: Tesla Autopilot-blue lanes, compass (theme → compass size). Small is 60px on the left between DM and the wheel and hides while MAX is up. Large is 90px top-right and stays while engaged. Accent fan = heading, letter in the hub, torque-bar ring. GPS-backed. Custom UI only. Theme Tesla vs Openpilot paints lanes, wheel, confidence ball, compass fan, and DM cone.

Home footer: Tesla **T + TACC** when openpilot long is off; comma **+ LONG** when it’s on; experimental atom beside LONG when experimental is on.

Home stats: **Today** (resets daily, Chicago local) and **Week** (resets Sunday). Distance / distance-engaged, whole miles, no space before `mi`/`km`. Labels match the version row; values sit one step smaller. Both shrink if the row would clip. Totals live in `/data/trip_meter.json` and the `TripMeter` param so reboot and overlay do not zero them. Boot reads that cache when `week_id` is this Chicago Sunday — no qlog scan on Home. After a drive, while parked, a subprocess writes `/data/trip_seed_cache.json` (per-segment meters) so a later reseed (install, missing json) does not LogReader the week on the UI thread. Qlogs never overwrite live miles.

## Toggles

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph after Tesla BSM is clear. Warning + slide-to-enable. Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot). |
| `LaneColor` | tesla | Theme paint. `0` Openpilot (stock green), `1` Tesla (Autopilot blue on lanes, wheel, confidence, compass, DM). Wheel alpha matches the lanes. |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. One at a time. |
| Delorean (`/data/delorean_sound`) | off | 88mph on going onroad. 1.5s stable, ignore <10s ignition blips. Personal use. |

## Alpha longitudinal (stock)

A 2026 Model 3 Highland fingerprints as `TESLA_MODEL_3`. Stock openpilot master sets `alphaLongitudinalAvailable = True` for Tesla, so **you should have** Developer → alpha longitudinal.

Stock C4 behavior, which Highland mirrors:

- Visible on development branches only (`AlphaLongitudinalEnabled` is `DEVELOPMENT_ONLY`; Highland is not a release branch).
- You **can** enable/disable it **onroad while not engaged**.
- You **cannot** change it while engaged.
- Changing it requests an onroad cycle (`OnroadCycleRequested`) because panda safety has to reinit longitudinal.

Tesla stock ACC stays default until this is on. Experimental mode is gated on openpilot long.

## Screenshots

Hold the display 3s (don’t drag). White flash + shutter. PNG in `/data/media/0/screenshots`. Repo copies go in [`docs/screenshots/`](docs/screenshots/README.md).

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
