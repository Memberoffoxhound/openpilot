# S3XYPilot — Highland

Working branch for Tesla Model 3 Highland (2024+) on S3XYPilot.

Internally this is still openpilot (repo name `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works). The C4 home wordmark is **S3XYPILOT**. Version is **0.4.20.69-FUELON**.

Fork of [commaai/openpilot](https://github.com/commaai/openpilot). Tesla car interface lives in [TeslaPilot-opendbc](https://github.com/Memberoffoxhound/TeslaPilot-opendbc/tree/Highland).

Surgical ports only — this is **not** a sunnypilot merge.

comma server-ban rules and the Highland checklist live in [TESLAPILOT_SAFETY.md](TESLAPILOT_SAFETY.md).

## Boot (Comma 4)

White Tesla T is the boot mark. Same file openpilot already loads:

- `openpilot/selfdrive/assets/images/spinner_comma.png` — 848×848 RGBA Tesla T (this branch)
- `openpilot/selfdrive/assets/images/spinner_track.png` — stock tick ring (unchanged)

On mici the spinner draws both at 140×140. The track rotates 360°/s. Install/update progress still paints the 268×10 bar under the disc (`TEXTURE_SIZE` 140, `PROGRESS_BAR_WIDTH` 268).

## Features (from dzid26/sunnypilot `vtb-sla`)

- **Cooperative steering** — light steering-wheel torque adds angle while engaged instead of requiring a full override. Stiffer as speed increases. Disengages if torsion-bar torque exceeds 5 Nm.
- **Cancel cruise with steering button** — on stalkless Highland, the steering-wheel scroll cancel is seen via `DAS_accState == 13` and raised as `ButtonType.cancel`.

## Nudgeless lane change (from sunnypilot)

Blinker starts the lane change while **engaged** and **over 25 mph**. Tesla DAS blind-spot is checked first.

**Toggles → Auto Lane Change** (Comma 4: first card in the toggles scroller). Tap the value to cycle:

Nudgeless → Nudge (stock, steer to confirm) → 0.5 s → 1 s → 1.5 s → … → 5 s → wrap.

**Toggles → BSM delay** holds the auto change until the Tesla blind-spot has been clear ~1 s. Greyed out when the mode is Nudge, because auto is off.

Behavior:

- Gate: `lateral_active` (openpilot engaged). Blinker is ignored when disengaged.
- Speed floor: **25 mph** (stock openpilot is 20).
- BSM: `DAS_status DAS_blindSpotRearLeft/Right` already in TeslaPilot-opendbc Highland `carstate.py` → `leftBlindspot` / `rightBlindspot`. Occupied BSM blocks the change. After it clears, wait ~1 s more (`AutoLaneChangeBsmDelay`).
- Brake during the wait cancels that auto attempt. A previous auto change in the same blinker hold will not fire another; cancel the blinker and re-signal.
- A real steering nudge still works immediately once BSM is clear, in every mode except Off.

| Param | Type | Default | Meaning |
| --- | --- | --- | --- |
| `AutoLaneChangeTimer` | INT | `1` | `-1` off (hidden), `0` stock nudge, `1` nudgeless, `2`–`11` = 0.5–5.0 s in 0.5 s steps |
| `AutoLaneChangeBsmDelay` | BOOL | `1` | wait until BSM is clear, then ~1 s |

## Camera calibration

**Device → Reset Calibration** shows the live mount angles (roll, pitch, yaw) on the control itself (stock only hid pitch/yaw in the expandable description).

- Comma 4: grey value on the card, three lines (`P 2.1° down` / `Y 0.4° left` / `R 0.3° cw`). `uncalibrated` until the first valid blocks.
- tici: same three values next to the RESET chip.

Roll/pitch/yaw come from `CalibrationParams` → `extrinsicsCalibration.rpyCalib[0,1,2]`. +pitch is down, +yaw is left, +roll is clockwise looking forward. Reset still clears calibration, torque, delay, and LiveParametersV2.

## Theme

**Settings → theme** (Comma 4 main menu card, same 64pt title + corner icon as toggles/device). Opens a subsection page with **lane color**.

- **lane color** — engaged lane lines (the two closest lines on the C4 model view).
  - `tesla blue` (default) — Tesla Autopilot visualization blue `#3E8CEB`
  - `comma green` — stock openpilot `#00FF40`

| Param | Type | Default | Meaning |
| --- | --- | --- | --- |
| `LaneColor` | INT | `1` | `0` comma green, `1` Tesla Autopilot blue |

Live while driving; no restart.

## Onroad livestream (1080p)

Stock openpilot kills livestream at **ignition** (`IsLiveStreaming` is `CLEAR_ON_IGNITION_ON`). That is why Connect dies the moment you go onroad.

Highland:

- `IsLiveStreaming` survives ignition
- `webrtcd` stays running (not gated offroad)
- `athenad.startStream` works onroad; 60s encoder grace so Connect reconnect is instant
- ICE is not pinned to the current wifi IP (wifi→LTE no longer tears the socket)
- Dashcam `encoderd` **pauses** while watching. Route video for that window is missing
- Stream is **1920×1080 H264** at up to 8 Mbps (steps down to 5 / 2 Mbps). H264 so Safari/iPhone can decode it

Watch: iPhone **Safari** → [connect.comma.ai](https://connect.comma.ai) → device → live view. If the picture blips at ignition, tap reconnect — do not leave the page. Close the live view to resume dashcam.

## Driving-model picker — not ported

sunnypilot’s **model picker** (community driving NNs: GWM, DTR, etc.) is **not** a small drop-in. It needs:

- custom cereal `ModelManagerSP` (stock TeslaPilot cereal has no such type)
- `modelManagerD` daemon + fetcher + `ModelManager_ActiveBundle` params
- sunnylink catalog (`REQUIRED_JSON_VERSION = 17`)
- modeld custom runners (`ModelRunnerTypeCache`, tinygrad vs stock)
- tici-heavy `ModelsLayout` UI — not the Comma 4 536×240 OLED

TeslaPilot Highland already tracks commaai/openpilot **master**, so you get the latest **stock comma** driving model. Community models need a sunnypilot-based fork, not a surgical port.

The other “model picker” in sunnypilot is the **vehicle platform selector** (`car_list.json` / ~350 cars). TeslaPilot is Tesla-only; that UI is not useful here.
