# DELAMAIN — Highland

Working branch for Tesla Model 3 Highland (2024+). Version **0.11.2.1**.

Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works. The C4 home wordmark is **DELAMAIN**.

Fork of [commaai/openpilot](https://github.com/commaai/openpilot). Tesla car interface: [opendbc Highland](https://github.com/Memberoffoxhound/TeslaPilot-opendbc/tree/Highland).

Surgical ports only — this is **not** a sunnypilot merge.

comma server-ban rules and the Highland checklist live in [SAFETY.md](SAFETY.md).

## Boot (Comma 4)

White Tesla T is the boot mark. Same file openpilot already loads:

- `openpilot/selfdrive/assets/images/spinner_comma.png` — 848×848 RGBA Tesla T (this branch)
- `openpilot/selfdrive/assets/images/spinner_track.png` — stock tick ring (unchanged)

On mici the spinner draws both at 140×140. The track rotates 360°/s. Install/update progress still paints the 268×10 bar under the disc (`TEXTURE_SIZE` 140, `PROGRESS_BAR_WIDTH` 268).

## Features (from dzid26/sunnypilot `vtb-sla`)

- **Cooperative steering** — light steering-wheel torque adds angle while engaged instead of requiring a full override. Stiffer as speed increases. Disengages if torsion-bar torque exceeds 5 Nm.
- **Cancel cruise with steering button** — on stalkless Highland, the steering-wheel scroll cancel is seen via `DAS_accState == 13` and raised as `ButtonType.cancel`.

## Auto lane change

**Toggles → Auto Lane Change** — off by default. Off is stock openpilot (steer to confirm). On is nudgeless: blinker starts the change while engaged over 25 mph, after Tesla BSM is clear (~1 s).

Enabling on the C4 walks through warning cards (swipe right-to-left) then a **slide to enable** confirm, same slider as reboot/reset.

| Param | Type | Default | Meaning |
| --- | --- | --- | --- |
| `AutoLaneChangeEnabled` | BOOL | `0` | off = wheel nudge; on = nudgeless + BSM |

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

## Onroad livestream (1080p VBR)

Stock openpilot kills livestream at **ignition**. Connect stays **parked-only** on this fork so we do not use comma TURN or Prime LTE.

Highland On-Air:

- `IsLiveStreaming` survives ignition
- `webrtcd` stays running
- ICE is not pinned to the current wifi IP
- Dashcam `encoderd` **pauses** while watching
- Stream is **1920×1080 H.264 VBR up to 8 Mbps** (steps 8 / 4 / 2 Mbps on packet loss)
- **LAN:** WebRTC (`/stream`, same path as Connect) — near real-time
- **Fallback / remote HTTP:** HLS, started only if WebRTC fails or someone hits `/hls/`
- Only on **Wi-Fi** (or unmetered) **or a non-Prime SIM**

### On-Air toggle

`LivestreamEnabled` (default **off**). Tap the **On-Air** badge on the home footer or **Settings → livestream**.

- **Off (gray):** stock Connect. Parked livestream only. Local page refused.
- **On (red):** `http://<c4-wifi-ip>:5001/` on the same Wi-Fi. HUD / 3D / FACE / map on the phone.

### Discord + internet (no phone relay)

Discord cannot ingest the C4 WebRTC feed. A **webhook** posts the watch URL when On-Air turns on. Friends open that URL; they do not go through your phone.

Params (set over SSH, persist):

```
# incoming webhook for a channel
params put DiscordWebhookUrl 'https://discord.com/api/webhooks/…'

# optional public HTTPS URL of the viewer (Cloudflare Tunnel, Tailscale Funnel, ngrok)
params put LivestreamPublicUrl 'https://your-tunnel.example'
```

Remote watchers should use **HLS in the page** (TCP). WebRTC ICE host candidates are LAN-only; do **not** point this at comma Connect/TURN.

Cloudflare Tunnel on the device (example, not bundled):

```
cloudflared tunnel --url http://127.0.0.1:5001
```

Loopback is allowed, so the tunnel can reach the viewer. 1080p × 3 cams can use a lot of **home upload** — expect a few Mbps to ~8 Mbps per camera.

Connect itself is unchanged: Athena `startStream` + WebRTC. On-Air only gates *onroad* and the LAN page.

The C4 hosts a page on **port 5001**. Phone and device on the same Wi-Fi, Safari:

```
http://<c4-wifi-ip>:5001/
```

C4 **Settings → Network** shows the IP. Guest-Wi-Fi client isolation will block it. On-Air must be on (home badge or Settings → livestream). If it's off, the page explains that instead of a raw 403.

- Splash, then **PiP** — wide cam letterboxed to the phone orientation, driver cam in the corner
- **3D** — wide + road stitch you can pan (drag) and pinch-zoom. Look behind for the driver cam
- HUD: encode bitrate, CPU temp, memory, Wi-Fi bars, viewers

HLS, not Connect. Comma's TURN/Athena are not in the path. Close the page; encoder stops after ~60s idle and dashcam resumes.

Watch from Connect still works the same (Wi-Fi, Safari → [connect.comma.ai](https://connect.comma.ai)). If you leave Wi-Fi onto a Prime SIM the Connect stream hangs up.

## Driving-model picker — not ported

sunnypilot’s **model picker** (community driving NNs: GWM, DTR, etc.) is **not** a small drop-in. It needs:

- custom cereal `ModelManagerSP` (stock cereal has no such type)
- `modelManagerD` daemon + fetcher + `ModelManager_ActiveBundle` params
- sunnylink catalog (`REQUIRED_JSON_VERSION = 17`)
- modeld custom runners (`ModelRunnerTypeCache`, tinygrad vs stock)
- tici-heavy `ModelsLayout` UI — not the Comma 4 536×240 OLED

Highland tracks commaai/openpilot **master**, so you get the latest **stock comma** driving model. Community models need a sunnypilot-based fork, not a surgical port.

The other “model picker” in sunnypilot is the **vehicle platform selector** (`car_list.json` / ~350 cars). This fork is Tesla-only; that UI is not useful here.
