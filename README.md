# S3XYPilot

Tesla-first fork for stalkless Model 3 / Y (Highland). Hobby project. No support. Install at your own risk.

Based on openpilot 0.11.12. This branch versions as **0.1.10.24**.

Installer: [`installer.comma.ai/Memberoffoxhound/Highland`](https://installer.comma.ai/Memberoffoxhound/Highland)

## Branches

- **`master`** — unmodified [comma.ai/openpilot](https://github.com/commaai/openpilot). Stock reference. Sync comma’s diffs here, then cherry-pick onto Highland.
- **`Highland`** — S3XYPilot Tesla fork. Install this branch only.

## What Highland adds

- Engage / disengage on the right scroll-wheel button
- Virtual torque blending / cooperative steering (default)
- Auto Lane Change (off by default; Tesla BSM; warning + confirm)
- Custom onroad UI: Tesla-blue lanes, compass, this-trip engaged %
- Home: Today / Week miles and distance engaged %
- Local dashboard at `http://<device-ip>:8088/` (LAN, no login, alpha)
- Connect parked livestream is stock

comma 4 UI. comma 3X may boot; UI is not tailored to it.

## Install

```
installer.comma.ai/Memberoffoxhound/Highland
```

Username `Memberoffoxhound`, branch `Highland`. Repo is named `openpilot` so the installer URL works.

You are the driver. This fork does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).

Stock install: [`openpilot.comma.ai`](https://openpilot.comma.ai)
