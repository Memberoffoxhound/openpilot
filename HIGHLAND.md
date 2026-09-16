> User-facing README: [README.md](README.md). This file is Highland working notes only.

# S3XYPilot — Highland

Working branch. Version **0.11.23**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror. **HighlandStage** is Highland rebased onto current comma master (AGNOS **19.7**, comma tinygrad ONNX/warp).

## opendbc pin

`.gitmodules` points `opendbc_repo` at `Memberoffoxhound/TeslaPilot-opendbc` (same-org sibling, not commaai/opendbc — Tesla 3-bit / coop steering cannot live on comma's SHA).

Structure matches comma: gitlink SHA is what ships, not the branch tip. The SHA is **comma openpilot master's opendbc pin plus Tesla-only commits**:

- base: `a3d3b7c6` (commaai/opendbc, the pin in comma/openpilot master)
- extras: 3-bit `DAS_steeringControlType`, cooperative steering, scroll-wheel cancel, `TESLA_MODEL_3` fingerprint pin, cached EPS FW fallback, shallow cruise-return jerk

```bash
cd opendbc_repo
git fetch origin
git checkout <gitlink SHA>
cd ..
git add opendbc_repo
git commit -m "opendbc: bump Highland (comma pin + Tesla extras)"
```

Current gitlink: `43242f0a` (local HighlandStage until TeslaPilot-opendbc is pushed).

## Fingerprint

This branch **always fingerprints as `TESLA_MODEL_3`** (2025 Model 3 / HW4 docs) until updated fingerprinting semantics are figured out. FW is still queried so FSD 14 flags can apply. `FINGERPRINT` is also defaulted in `launch_env.sh`. See the README disclaimer: Highland Teslas only.

## Params

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph after Tesla BSM is clear. Warning + slide-to-enable. rav4kumar / sunnypilot. |
| `LaneColor` | tesla | `0` Openpilot green, `1` Tesla Autopilot blue (lanes, wheel, confidence, compass, DM). |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. |
| `VSlamEnabled` | on | Green-pill logger toggle. Off stops detect + log + toast. File `/data/vslam/enabled`. |
| `VSlamFilterEnabled` | on* | *Unfinished / observe-only.* Param + UI storage exist, but no planner consumer yet — Filter toggle hidden in WebUI/C4 until wired. Requires openpilot long (`AlphaLongitudinalEnabled`); locked off on TACC. File `/data/vslam/filter`. |
| Delorean (`/data/delorean_sound`) | off | 88mph on going onroad. 1.5s stable, ignore <10s ignition blips. |

## Trip files

| Path | Role |
|---|---|
| `/data/trip_meter.json` + `TripMeter` param | Live Today/Week. Boot reads this. |
| `/data/trip_seed_cache.json` | Per-segment meters, filled parked after a drive. |
| `/data/trip_stats.json` | Lifetime miles, all-time day streak, longest stretch, monthly totals. Survives qlog purge. |

Chicago local for day/week. UI thread never LogReader.
`live` and `pending` are stamped with a Chicago day. Home only adds them to Today when that stamp matches today.
Offroad fold commits leftover overlay into `days[]` and clears `pending`/`live` immediately. The device often loses power a few minutes after park, so park cache does not wait `HOT_SEC` or scan 200 days of qlogs. Recent qlogs (3 days) are folded after the commit if power lasts. Boot / statistics still do the long scan when parked.

## Alpha longitudinal (stock)

A Highland car is forced to `TESLA_MODEL_3`. Stock master sets `alphaLongitudinalAvailable = True`.

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
| `/data/vslam/traces/<id>.json` | 5s+event+5s vCruise vs planner vPlan + GPS (lat/lon) |

C4: Settings → vSlam (green-pill logger toggle + list + sparkline) and Settings → toggles. LAN: deviceweb `:8088` → **vSlam tracker**. Event list shows the mph drop up top-right with a mini spark under it. Map / spark is green when nominal, red→yellow during the slam (red = slowest slam speed, yellow = highest in the window).

On detect, C4 throws a 3s orange `userPrompt` toast: **vSlam logged**. Observe-only — stamped via `/data/vslam/alert_until`, not selfdrived / panda.

## Screenshots / LAN

Hold display 3s → `/data/media/0/screenshots`. `deviceweb` on **8088**, no auth.

### Live cameras

Hamburger → **Live cameras**. LAN WebRTC viewer for comma 4 feeds.

- Fcam (`road`) / Ecam (`wideRoad`) / Dcam (`driver`) / Combo (fcam + dcam postage stamp)
- Tesla-style HUD: speed (IsMetric), upper-right map, S3XYPilot wordmark + Engaged/Disengaged
- Sets `IsLiveStreaming`. `webrtcd` runs when livestreaming (or notcar). Onroad video reuses `encoderd`; `stream_encoderd` only while offroad/livestream or on the body (see `process_config.livestream_encoder`). Signaling is proxied `deviceweb → 127.0.0.1:5001`.
- Mic toggle plays `rawAudioData` (16 kHz PCM) over SSE. Onroad only — `micd` is an iscar process.
- Fullscreen theater for phone screen-share (no separate Rotate control). Same PWA as the rest of deviceweb.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
