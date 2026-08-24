# DELAMAIN 0.11.2.1

**2026-08-20** · Tesla Model 3 Highland (2024+) · Comma 4  
Based on [openpilot 0.11.2](https://github.com/commaai/openpilot/blob/master/RELEASES.md) (2026-08-12).

Install: `installer.comma.ai/Memberoffoxhound/Highland`

Home wordmark is **DELAMAIN**. Boot mark is the white Tesla T with the stock spinner ring and install bar.

---

## On-device toggles

| Where | Control | Default | What it does |
| --- | --- | --- | --- |
| **Toggles → auto lane change** | on/off | **off** | Off = stock openpilot (nudge the wheel). On = blinker starts the change while engaged **over 25 mph**, after Tesla **stock BSM** is clear. Enabling walks warning cards, then **slide to enable**. |
| **Settings → theme → lane color** | tesla blue / comma green | **tesla blue** | Color of the two closest lane lines while engaged. Live, no restart. |
| **Settings → livestream** (clapper) or **home On-Air badge** | On-Air | **off** | Local Wi-Fi viewer on the phone. Off is stock Connect (parked only). |
| **Device → reset calibration** | (display) | — | Live **pitch / yaw / roll** on the button. Reset still clears calibration. |

Auto lane change warning (full text):

> Auto Lane Change uses Tesla's stock blind spot monitoring to check for a vehicle in the adjacent lane prior to merging. You are still responsible for ensuring the lane of travel is clear and agree to intervene as necessary.

---

## DELAMAIN additions

### Auto lane change
Nudgeless lane change with Tesla BSM, default off, confirm slider. You stay responsible for the lane.

### Theme
Main-menu **theme** card (paintbrush icon). Lane lines: Tesla Autopilot blue `#3E8CEB` or comma green `#00FF40`.

### Calibration
Reset Calibration shows **P / Y / R** on the card (`down`/`left`/`cw`).

### On-Air local livestream
Wi-Fi or non-Prime SIM only. Does **not** use comma Connect, TURN, or Prime LTE.

- Phone, same network: `http://<device-ip>:5001/`
- **720p** H.264 **VBR up to 6 Mbps** (4 / 2 if the link drops)
- **WebRTC** (Connect's `/stream`) on LAN
- Dashcam **keeps recording** for Connect while you watch locally
- **HUD on/off** — clipper-style overlay on the **narrow road cam** (MAX, speed, path, lead)
- Driver cam beside the map, trip card full width (miles, % engaged, street)
- **3D** — pan/pinch passenger stitch (wide + driver at the A-pillar)
- Auto-reconnect if you leave and come back

On-Air **off** = stock Connect behavior. On-Air **on** = local viewer; Connect is not taxed.

Cooperative steering and stalkless cancel (Highland steering-wheel scroll) are also in this branch.

---

## From comma openpilot 0.11.2 (2026-08-12)

This fork is 0.11.2 plus the above. Stock 0.11.2 includes:

- New driving model (big model, 880M parameters)
- Big models on an external GPU (chestnut)
- Live stream cameras from comma Connect *(parked / offroad; our On-Air is the onroad local path)*
- Generate dashcam clips from comma Connect
- Remote comma body control from comma Connect
- New alert sounds
- CUPRA Born 2021–2023
- Volkswagen ID.4 2021–2025

Also in the 0.11 line (already in 0.11.2):

- **0.11.1** — new driver monitoring model, better driver-cam ISP, C4 thermal policy, Acura MDX 2022–24, Rivian R1S/R1T 2025
- **0.11.0** — driving model trained in a learned simulator, C4 standby power −77%, Experimental-mode longitudinal gains

---

## Not in this fork

- sunnypilot **model picker** / community NNs
- Extra vehicle selector (this branch is Tesla Highland)
- Connect onroad livestream (stock Connect stays parked-only so we don't hit their servers)

Safety notes: [SAFETY.md](SAFETY.md). Feature map: [HIGHLAND.md](HIGHLAND.md).
