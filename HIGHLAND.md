# TeslaPilot — Highland

Working branch for Tesla Model 3 Highland (2024+) on TeslaPilot.

Fork of [commaai/openpilot](https://github.com/commaai/openpilot). Tesla car interface lives in [TeslaPilot-opendbc](https://github.com/Memberoffoxhound/TeslaPilot-opendbc/tree/Highland).

## Features (from dzid26/sunnypilot `vtb-sla`)

- **Cooperative steering** — light steering-wheel torque adds angle while engaged instead of requiring a full override. Stiffer as speed increases. Disengages if torsion-bar torque exceeds 5 Nm.
- **Cancel cruise with steering button** — on stalkless Highland, the steering-wheel scroll cancel is seen via `DAS_accState == 13` and raised as `ButtonType.cancel`.
