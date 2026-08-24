# Sexypilot

Tesla-first fork for **stalkless Model 3 / Y**. Hobby project. No support. Install at your own risk.

Driven on a **2026 Model 3 Highland**. Based on openpilot 0.11.12. This branch versions as **0.11.12**.

Installer: [`installer.comma.ai/Memberoffoxhound/Highland`](https://installer.comma.ai/Memberoffoxhound/Highland)

## Branches

- **`master`** — unmodified [comma.ai/openpilot](https://github.com/commaai/openpilot) mirror.
- **`Highland`** — Sexypilot. Install this.
- **`K5`** — comma master + Auto Lane Change (confirm slider). For the Kia.

## Highland

Stalkless Teslas have no cruise stalk. Engage / disengage is the **right scroll-wheel button**. Cooperative steering stays on.

- Footer: **TACC** / **openpilot long** / **experimental**. Experimental is off and hidden on stock TACC. Tap the atom to toggle when OP long is on.
- Auto Lane Change — off by default; Tesla stock BSM; warning + confirm; 25 mph min
- Custom onroad UI — Tesla-blue lanes, compass (small left or large top-right; theme toggle)
- Home — Today / Week miles and distance-engaged %
- 3s display hold → screenshot (`/data/media/0/screenshots`)
- LAN dashboard `http://<device-ip>:8088/` (local Wi-Fi, no login, alpha)
- comma Connect livestream is **stock** (parked only)

Theme extras, **off by default**: ludicrous overlay, buckle sound (once; rearm after a 20 min drive, else 3 hours), Delorean 88mph clip (on going onroad).

comma 4 UI. comma 3X may boot; UI is not tailored to it.

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

Username `Memberoffoxhound`, branch `Highland`. Repo is named `openpilot` so that installer URL works.

You are the driver. This fork does not change driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).

Stock install: [`openpilot.comma.ai`](https://openpilot.comma.ai)
