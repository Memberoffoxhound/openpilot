# TeslaPilot safety (comma server ban)

TeslaPilot is a surgical fork of [commaai/openpilot](https://github.com/commaai/openpilot).
comma will **ban the dongle from comma.ai servers** if a fork breaks the rules in
[docs/SAFETY.md](docs/SAFETY.md). This file is the Highland checklist against that document.

## comma rules (verbatim meaning)

1. **Do not disable or nerf [driver monitoring](https://github.com/commaai/openpilot/tree/master/openpilot/selfdrive/monitoring).**
2. **Do not disable or nerf [excessive actuation checks](https://github.com/commaai/openpilot/tree/master/openpilot/selfdrive/selfdrived/helpers.py).**
3. **If the fork modifies `opendbc/safety/`:**
   - it cannot use the openpilot trademark
   - it must keep the full [opendbc safety test suite](https://github.com/commaai/opendbc/tree/master/opendbc/safety/tests) and every test must pass, including new coverage for the fork's changes

## What TeslaPilot Highland actually changes

| Surface | Touched? | Notes |
| --- | --- | --- |
| `openpilot/selfdrive/monitoring` | **No** | Stock comma driver monitoring. Always-On DM toggle is stock. |
| `openpilot/selfdrive/selfdrived/helpers.py` | **No** | Stock excessive-actuation / longitudinal & lateral limits. |
| `opendbc/safety/` (panda safety) | **No** | TeslaPilot-opendbc Highland only edits `opendbc/car/tesla/` (coop steering, stalkless cancel, BSM wiring). `opendbc/safety/modes/tesla.h` blob matches commaai/opendbc. |
| `panda` submodule | **No** | Still `commaai/panda`. |
| Desire / lane change | Yes, Python | `desire_helper.py` + `auto_lane_change.py`. This is the planner desire, **not** panda torque/angle limits. Blinker+BSM still require engaged + 25 mph. A steering nudge still works. Brake cancels the auto attempt. |
| Toggles UI | Yes | Reads/writes `AutoLaneChangeTimer` and `AutoLaneChangeBsmDelay` only. |
| Boot mark | Yes | `spinner_comma.png` asset. Not safety. |

Cooperative steering lives in Tesla car interface Python (`opendbc/car/tesla/`). It adds angle **within** the existing panda Tesla safety mode. Torsion-bar torque above 5 Nm still disengages. That is not a panda-safety patch.

## CI that enforces this

- TeslaPilot `.github/workflows/fork-safety.yaml` — fails if Highland diverges from the comma merge-base on monitoring, `helpers.py`, or `opendbc/safety`.
- TeslaPilot-opendbc `.github/workflows/tests.yml` — stock `safety_tests` job runs `./opendbc/safety/tests/test.sh` (the suite comma requires). Highland pushes are included so the suite actually runs on this branch.

## What this does **not** claim

comma does not certify forks. Passing these checks means TeslaPilot is not doing the three things that get dongles banned. Drive with your hands on the wheel. Nudgeless lane change is a convenience on top of stock lateral control, not a license to look away.
