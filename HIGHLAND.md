# TeslaPilot — Highland

Working branch for Tesla Model 3 Highland (2024+) on TeslaPilot.

Fork of [commaai/openpilot](https://github.com/commaai/openpilot). Tesla car interface lives in [TeslaPilot-opendbc](https://github.com/Memberoffoxhound/TeslaPilot-opendbc/tree/Highland).

## Boot (Comma 4)

White Tesla T is the boot mark. Same file openpilot already loads:

- `openpilot/selfdrive/assets/images/spinner_comma.png` — 848×848 RGBA Tesla T (this branch)
- `openpilot/selfdrive/assets/images/spinner_track.png` — stock tick ring (unchanged)

On mici the spinner draws both at 140×140. The track rotates 360°/s. Install/update progress still paints the 268×10 bar under the disc (`TEXTURE_SIZE` 140, `PROGRESS_BAR_WIDTH` 268).

## Features (from dzid26/sunnypilot `vtb-sla`)

- **Cooperative steering** — light steering-wheel torque adds angle while engaged instead of requiring a full override. Stiffer as speed increases. Disengages if torsion-bar torque exceeds 5 Nm.
- **Cancel cruise with steering button** — on stalkless Highland, the steering-wheel scroll cancel is seen via `DAS_accState == 13` and raised as `ButtonType.cancel`.
