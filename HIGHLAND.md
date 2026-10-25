> User-facing README: [README.md](README.md). This file is Highland working notes only.

# TeslaPilot — Highland

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
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph, 0.75 s after the blinker, once Tesla BSM is clear. Warning + slide-to-enable. rav4kumar / sunnypilot. |
| `LaneColor` | tesla | `0` Openpilot green, `1` Tesla Autopilot blue (lanes, wheel, confidence, compass, DM). |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. |
| `VSlamEnabled` | on | Green-pill logger toggle. Off stops detect + log + toast. File `/data/vslam/enabled`. |
| `VSlamFilterEnabled` | on* | *Unfinished / observe-only.* Param + UI storage exist, but no planner consumer yet — Filter toggle hidden in WebUI/C4 until wired. Requires openpilot long (`AlphaLongitudinalEnabled`); locked off on TACC. File `/data/vslam/filter`. |
| `TeslaStepAside` | on | While Tesla Autosteer/FSD is selected (not TACC) or Autopilot/FSD/Summon is active, openpilot goes passive before CarParams: `noOutput`, relay never closes. 5 s alert, then display off (touch wakes). Back via onroad cycle once Tesla is idle on TACC 3 s and in P or cruise off. `TeslaSteppedAside` (cleared on ignition) is the per-drive state. See `selfdrive/car/tesla_step_aside.py`. |
| `ParkOffroad` | off | Settings "Go Offroad in Park" (warning + confirm; also turns on `DriveSummary`). Tesla: after the car has left Park this ignition cycle, Park held 3 s, not engaged → normal offroad transition (route ends, relay open). Only R or D brings it back onroad, as a new route. While latched, ignitionCan (Tesla stays in power state DRIVE in Park) never restarts onroad; only a real ignition cycle (off ≥ 5 s) clears it. Gear frames lost 2 s → stock ignition behavior until the next ignition cycle. Summon/Autopark keeps it offroad. `parkd` / `selfdrive/car/park_offroad.py`; hardwared `not_parked` condition. |
| `ParkOffroadActive` | — | parkd's latch (cleared on manager start only; parkd re-asserts it every second). |
| `DriveSummary` | off | "trip complete" card that hops in over the onroad page when a trip ends (stopped), before the stock scroll to home; slides back up after 10 s / tap (`SHOW_S`) as home scrolls in ≥ 0.1 mi / 30 s, plus the onroad STREAK circle (bottom-right; ring = progress to your best stretch `max_streak_m`; theme color). Any car. `selfdrive/ui/lib/drive_summary.py`; see PORTING.md. |
| `DriveSummaryLast` | — | JSON: last drive (distance, engaged, best stretch, timeline codes, shown flag) + 14 days of totals + `record_m`. |
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
- Tesla-style HUD: speed (IsMetric), upper-right map, TeslaPilot wordmark + Engaged/Disengaged
- Sets `IsLiveStreaming`. `webrtcd` runs when livestreaming (or notcar). Onroad video reuses `encoderd`; `stream_encoderd` only while offroad/livestream or on the body (see `process_config.livestream_encoder`). Signaling is proxied `deviceweb → 127.0.0.1:5001`.
- Mic toggle plays `rawAudioData` (16 kHz PCM) over SSE. Onroad only — `micd` is an iscar process.
- Fullscreen theater for phone screen-share (no separate Rotate control). Same PWA as the rest of deviceweb.

## Jetlink (branch `jetlink`)

Big model on a phone or computer plugged into the comma's USB-C port. Synced with zoompilot develop `93b6ca9`:

- `jetlink_repo` pinned at `d19b83b` (jetlink **v0.8.8**), what zoompilot develop pins.
- modeld picks the big model as zoompilot does: `chestnut_compiled() and (chestnut_present() or jetlink_adapter.chestnut_cable())`. `chestnut_cable()` is a cable on the USB-C port while the link is off, so an iPhone/USB link never waits 10 s for a chestnut.
- `selfdrive/jetlink_adapter`: jetlink's `Stock` adapter and `Hooks`, behind Highland's lazy gate. With **Settings → models → jetlink** off nothing imports jetlink.
- selfdrived: `jetlinkBigModelAvailable` / `jetlinkBigModelLost` / `jetlinkBigModelActive` (log.capnp @106–108; `teslaStepAside` is @105, after comma's `userBookmarkNotPaired` @104) plus `bigModelLoading` no-entry for about 1 s after a swap. None of them disengage.
- hardwared: param `Offroad_AcceleratorUnavailable` (offroad alert "Jetlink unavailable: …"); powers the accelerator off with the comma. `launch_chffrplus.sh` stops charging out of the USB-C port from boot while the link is on.
- UI, as zoompilot: the link drives the chestnut icons (`ChestnutState.WAITING` shows dim). The models panel holds active model / big model, the off/usb/iOS link toggle and charge phone. The data comes from jetlink's `Status` and its runtime record at `/dev/shm/jetlink/modeld.json`. There is no Highland live file and no Settings → jetlink page.
- Own additions kept: model manager, ADB released while the link holds the port, Tesla step-aside, `lat_delay` written for the joining model. No LFS for any of it.

## Upstream sync (Oct 2026)

`jetlink` = comma master `9fba666` merged once (one merge commit, no rebase), opendbc moved with panda to comma's pin `b3bd79a` plus the Tesla extras (`TeslaPilot-opendbc` `b04890d`). Tesla steering decode is comma's 3-bit-only one; panda safety is comma's, byte for byte. Experimental mode follows comma (always on with openpilot long); `LongModeBadge` stays.

AGNOS: `jetlink` runs comma's **20.1**. `jetlink-agnos19` is the same code with one commit on top that stays on **19.7** (no OS flash) and keeps comma's `modem` process, which AGNOS 20 moved into the OS. If 20.1 hangs at boot, install `jetlink-agnos19`.

## Git LFS

The branch installs with no LFS fetch. Every file comma keeps in LFS is a normal git blob here (`.gitattributes` exempts it), except `models/big_driving_tinygrad.pkl` (776 MB, over GitHub's 100 MB limit): that stays a pointer, is excluded in `.lfsconfig` (`fetchexclude`), and is pulled from comma's LFS store by the modeld build only when a chestnut is present (`big_model_source.ensure_big_pkl`). `chestnut_compiled()` is false for a pointer, so jetlink / the small model are used instead of a crash.

`python3 scripts/teslapilot_lfs.py` checks this (`--fix` converts newly added LFS files). `selfdrive/test/test_no_lfs_pointers.py` runs it in the test suite.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
