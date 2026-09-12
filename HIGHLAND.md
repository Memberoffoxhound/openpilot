> User-facing README: [README.md](README.md). This file is Highland working notes only.

# S3XYPilot — Highland

Working branch. Version **0.11.23**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror. Do **not** merge master wholesale into Highland. That pull (bc500d0) bumped AGNOS 19.6 → 19.7, retargeted `agnos.json` at a 4.7 GB system image, and is what made the on-device updater hang. Cherry-pick only the files you need.

AGNOS on this branch is pinned to **19.6** (`launch_env.sh` + `openpilot/common/hardware/comma/agnos.json`). Keep those two in lockstep.

## Tesla 3-bit steering (opendbc#3389)

Cherry-picked onto `TeslaPilot-opendbc` Highland. Not in comma master yet.

Tesla widened `DAS_steeringControlType` from 2 bits to 3 bits (new value `4 = FSD`). Sending the old 2-bit `ANGLE_CONTROL` made the car read LKAS. Crossing a lane line then tripped `invalidLkasSetting` until park.

This car's EPS `E4H015.05.0` is **3-bit** (not in `LEGACY_DAS_STEERING_FW`). Pack/read type `1` as 3-bit.

After an openpilot update, also pull the opendbc submodule — the installer pin does not move by itself:

```
cd /data/openpilot/opendbc_repo && git fetch origin Highland && git checkout Highland && git pull
```

Then reboot so panda rebuilds `tesla.h`.

DBC must say `SG_ DAS_steeringControlType : 23|3@0+` and `VAL_ ... 4 "FSD"`.

## Git LFS

`.lfsconfig` points at **comma's GitLab LFS**, not GitHub. The Comma 4 updater can only download LFS objects that already live there.

**Nothing custom on this fork needs LFS.** Measured on device:

| File | Size | Why it exists |
|---|---:|---|
| `icons_mici/settings/theme.png` | 623 B | Theme row |
| `icons_mici/usb.png` | 1.5 KB | Home USB |
| `icons_mici/tesla_t.png` | 5.7 KB | Wordmark / T |
| `sounds/shutter.wav` | 13 KB | Screenshot |
| `icons_mici/chestnut_orange.png` | 13 KB | Home loading |
| `fonts/TESLA.ttf` | 22 KB | S3XYPilot wordmark |
| `images/spinner_comma.png` | 23 KB | Boot spinner |
| `sounds/88mph.wav` | 937 KB | Delorean easter egg |

Those stay **normal git blobs** (see `.gitattributes` exceptions). If you add another Highland-only png/wav/ttf, add a `-filter=lfs` line for it. Do not `git add --renormalize` them onto LFS.

The only LFS objects this branch should pull are **comma's models**, already on GitLab:

| File | Size |
|---|---:|
| `dmonitoring_model.onnx` | 7.5 MB |
| `driving_supercombo.onnx` | 58 MB |
| `big_driving_supercombo.onnx` | 731 MB |

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

A 2026 Model 3 Highland is hardcoded to `TESLA_MODEL_3` (stock 2024–25 HW4). Empty EPS ISO-TP uses this car’s `E4H015.05.0` FW and never falls through to MOCK. Stock master sets `alphaLongitudinalAvailable = True`.

- Visible on development branches (`AlphaLongitudinalEnabled` is `DEVELOPMENT_ONLY`).
- Can change onroad while not engaged. Cannot while engaged.
- Change requests an onroad cycle (`OnroadCycleRequested`) so panda safety reinits.

Tesla stock ACC until this is on. Experimental is gated on openpilot long.

The Sep 10 master merge is what made cold-start fingerprint fall through to MOCK (empty ISO-TP, VIN query Tesla does not answer). The pin + EPS seed in `launch_env.sh` / `card.py` restore the pre-merge behavior. Do not drop those when pulling comma files.

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

Panda Tesla safety **does** change with the 3-bit PR (`opendbc/safety/modes/tesla.h` on TeslaPilot-opendbc Highland). Driver monitoring is untouched. See [SAFETY.md](SAFETY.md).
