# S3XYPilot

Tesla-first fork for **stalkless Model 3 / Y**. A hobby project. The extras are small quality-of-life things a comma 4 Tesla driver will actually use — especially without stalks. No support. Install at your own risk.

Driven on a **2026 Model 3 Highland**.

Based on openpilot 0.11.12. This branch versions as **0.11.12.24**.

Installer: [`installer.comma.ai/Memberoffoxhound/Highland`](https://installer.comma.ai/Memberoffoxhound/Highland)

## Branches

- **`master`** — unmodified [comma.ai/openpilot](https://github.com/commaai/openpilot). Stock reference. Sync comma’s diffs here, then cherry-pick onto Highland.
- **`Highland`** — S3XYPilot. Install this branch.

## What Highland adds

Stalkless Teslas don’t have a cruise stalk. Highland puts **engage / disengage on the right scroll-wheel button** and keeps **cooperative steering** (virtual torque blending) on by default, so it still feels like stock comma.

- Footer shows **TACC** (Tesla cruise), **openpilot long**, or **experimental**
- Auto Lane Change — off by default; Tesla stock BSM; warning + confirm
- Custom onroad UI — Tesla-blue lanes, compass, this-trip engaged %
- Home — Today / Week miles and distance engaged %
- 3s press on the display takes a screenshot (`/data/media/0/screenshots`, also the LAN dashboard **Shots** tab)
- LAN dashboard at `http://<device-ip>:8088/` (local Wi-Fi, no login, alpha)
- comma Connect livestream is **stock** (parked only)

Theme extras, off by default: ludicrous overlay, buckle sound.

comma 4 UI. comma 3X may boot; the UI is not tailored to it.

## Tesla compatibility

Same Tesla platforms as stock comma. **2026 Model 3 Highland is not on comma’s list yet; this fork is driven on one and it works.**

| Car | Years | Notes |
|---|---|---|
| Model 3 HW3 | 2019–23 | [comma official](https://docs.comma.ai/CARS/) |
| Model 3 HW4 | 2024–26 | official through 2025; **2026 Highland confirmed on this fork** |
| Model Y HW3 | 2020–23 | comma official |
| Model Y HW4 | 2024–25 | comma official |

HW3 uses Tesla A harness, HW4 uses Tesla B. Alpha longitudinal is TACC vs openpilot gas/brake.

S / X / Cybertruck are not supported. 2026 Model Y is untested here.

## Install

```
installer.comma.ai/Memberoffoxhound/Highland
```

Username `Memberoffoxhound`, branch `Highland`. The GitHub repo is named `openpilot` so that installer URL works.

You are the driver. This fork does not change driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).

Stock install: [`openpilot.comma.ai`](https://openpilot.comma.ai)
