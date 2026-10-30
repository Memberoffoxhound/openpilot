> User-facing README: [README.md](README.md). This file is Highland working notes only.

# TeslaPilot — Highland

Working branch. Version **0.11.23**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror. **HighlandStage** is Highland rebased onto current comma master (AGNOS **19.7**, comma tinygrad ONNX/warp).

## opendbc pin

`.gitmodules` points `opendbc_repo` at `Memberoffoxhound/TeslaPilot-opendbc` (same-org sibling, not commaai/opendbc — Tesla 3-bit / coop steering cannot live on comma's SHA).

Structure matches comma: gitlink SHA is what ships, not the branch tip. The SHA is **comma openpilot master's opendbc pin plus Tesla-only commits**:

- base: `b3bd79a6` (commaai/opendbc, the pin in comma/openpilot master)
- extras: 3-bit `DAS_steeringControlType`, cooperative steering, scroll-wheel cancel, `TESLA_MODEL_3` fingerprint pin, cached EPS FW fallback

```bash
cd opendbc_repo
git fetch origin
git checkout <gitlink SHA>
cd ..
git add opendbc_repo
git commit -m "opendbc: bump Highland (comma pin + Tesla extras)"
```

Current gitlink: `c16441e` (`Highland-sync`).

## Fingerprint

This branch **always fingerprints as `TESLA_MODEL_3`** (2025 Model 3 / HW4 docs) until updated fingerprinting semantics are figured out. FW is still queried so FSD 14 flags can apply. `FINGERPRINT` is also defaulted in `launch_env.sh`. See the README disclaimer: Highland Teslas only.

## Params

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph, 0.75 s after the blinker, once Tesla BSM is clear. Warning + slide-to-enable. rav4kumar / sunnypilot. |
| `LaneColor` | tesla | `0` Openpilot green, `1` Tesla Autopilot blue (lanes, wheel, confidence, compass, DM). |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. |
| `TeslaStepAside` | on | While Tesla Autosteer/FSD is selected (not TACC) or Autopilot/FSD/Summon is active, openpilot goes passive before CarParams: `noOutput`, relay never closes. 5 s alert, then display off (touch wakes). Back via onroad cycle once Tesla is idle on TACC 3 s and in P or cruise off. `TeslaSteppedAside` (cleared on ignition) is the per-drive state. See `selfdrive/car/tesla_step_aside.py`. |
| `ParkOffroad` | off | "Go Offroad in Park" (warning confirm; also sets `DriveSummary`). After R/D this ignition cycle, Park held 3 s, not engaged → normal offroad. Only R/D returns onroad (new route); ignitionCan staying on never does. Ignition off ≥ 5 s clears it. No gear frames 2 s → stock until the next ignition cycle. Summon/Autopark stays offroad. `selfdrive/car/park_offroad.py` (parkd), hardwared `not_parked`. |
| `ParkOffroadState` | 0 | parkd's output: 0 none, 1 parking, 2 parked. Cleared on manager start only, re-asserted every second. |
| `DriveSummary` | off | Trip card as the onroad page when a trip ends (stopped, ≥ 0.1 mi / 30 s); stock scroll to home after 20 s (`SHOW_S`) or a tap; swipe back to see it until the next drive. With `ParkOffroad`: up at the first Park sample with brightness held, and R/D skips `ONROAD_DELAY` and the brightness ramp. Any car; see PORTING.md. |
| `DriveSummaryLast` | — | The one trip-stats store (JSON): 400 days of totals, lifetime, best stretch, best streak, last drive, drives not stored yet. See `selfdrive/ui/tripstats/README.md`. |
| `Timezone` | — | Time zone for trip-stats days, looked up from `LastGPSPosition` in the offline 190 KB map (`tzgrid.bin`). Empty until the first GPS fix, then the system zone is used. Written off the UI thread. There is no manual override. |

## Trip stats

Trip stats live in one param, `DriveSummaryLast`, written by one recorder in the UI (`selfdrive/ui/tripstats`). Home's Day / Week, the card, Statistics and the web page all read the same numbers from it. There are no qlog scans, no `/data` files and no background jobs.

A drive is saved every 30 s while it runs. If power is cut, it closes at its last save, and its card comes up once at the next start as "last trip summary".

Days follow the device's time zone. GPS gives the position, `tzgrid.bin` turns it into a zone, and the zone goes in `Timezone`. With no GPS fix yet, the system zone is used. Each drive is saved with its end time and the zone offset at that moment, so a later zone change never moves it. A drive that ends on a wrong clock waits until the clock is valid. Weeks start Sunday. Details: `selfdrive/ui/tripstats/README.md`.

Older builds left `/data/trip_stats.json`, `/data/trip_seed_cache.json`, `/data/trip_meter.json` and
`/data/trip_*.lock` behind. Nothing reads them now, and they are safe to delete.

## Alpha longitudinal (stock)

A Highland car is forced to `TESLA_MODEL_3`. Stock master sets `alphaLongitudinalAvailable = True`.

- Visible on development branches (`AlphaLongitudinalEnabled` is `DEVELOPMENT_ONLY`).
- Can change onroad while not engaged. Cannot while engaged.
- Change requests an onroad cycle (`OnroadCycleRequested`) so panda safety reinits.

Tesla stock ACC until this is on. Experimental is gated on openpilot long.

## Screenshots / LAN

Hold display 3s → `/data/media/0/screenshots`. Web GUI `system/webgui` on **8089**, runs at boot (manager `RestartingPythonProcess`, always_run), no auth: stats, screenshots, UI screen recording.

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
