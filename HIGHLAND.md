> User-facing README: [README.md](README.md). This file is Highland working notes only.

# S3XYPilot — Highland

Working branch. Version **0.11.12.24**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror. Highland is the Tesla fork. Sync comma diffs onto `master`, then cherry-pick onto Highland.

## Onroad

Theme → onroad UI = **stock** (comma HUD) or **custom**. Custom: Tesla-blue lanes, 60px DM-style compass on the left between DM and the wheel (green fan = heading, letter in the hub, torque-bar ring). Compass is GPS-backed and only draws while engaged.

Home footer: Tesla **T + TACC** when openpilot long is off; comma **+ LONG** when it’s on; experimental atom beside LONG when experimental is on.

Home stats: **Today** (resets daily, Chicago local) and **Week** (resets Sunday). Distance / distance-engaged, whole miles, no space before `mi`/`km`. Labels match the version row; values sit one step smaller. Both shrink if the row would clip. First boot / install reseeds Today and Week from onboard qlogs so a Highland install still shows this week.

## Toggles

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph after Tesla BSM is clear. Warning + slide-to-enable. |
| `LaneColor` | Tesla blue | Custom UI only. `0` comma green, `1` Tesla blue. |
| `LudicrousEnabled` | off | Once per drive, not on a mid-drive reboot. Personal-use Spaceballs clip. |
| `BuckleSound` | off | Same once-per-drive rule. |
| Delorean (`/data/delorean_sound`) | off | 88mph clip on first Drive or Reverse. Once per drive. Personal use. |

## Screenshots

Hold the display 3s (don’t drag). White flash + shutter. PNG in `/data/media/0/screenshots`. LAN dashboard **Shots** tab (1px white frame). SSH/SFTP same path.

## LAN console

`http://<c4-ip>:8088` — settings, files, shots, clips (offroad, local routes), stats, updates. No password. Local Wi-Fi only. Not comma Connect.

Connect livestream is **stock** (parked). Custom on-road WebRTC viewer was removed so Connect stays compatible.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
