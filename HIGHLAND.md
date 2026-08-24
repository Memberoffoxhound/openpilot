> User-facing README: [README.md](README.md). This file is Highland working notes only.

# S3XYPilot — Highland

Working branch. Version **0.11.12**. Repo name is `openpilot` so `installer.comma.ai/Memberoffoxhound/Highland` works.

`master` is an unmodified comma.ai/openpilot mirror. Highland is the Tesla fork. Sync comma diffs onto `master`, then cherry-pick onto Highland.

## Onroad

Theme → onroad UI = **stock** (comma HUD) or **custom**. Custom: Tesla-blue lanes, compass (theme → compass size). Small is 60px on the left between DM and the wheel and hides while MAX is up. Large is 90px top-right and stays while engaged. Green fan = heading, letter in the hub, torque-bar ring. GPS-backed. Custom UI only.

Home footer: Tesla **T + TACC** when openpilot long is off; comma **+ LONG** when it’s on; experimental atom beside LONG when experimental is on.

Home stats: **Today** (resets daily, Chicago local) and **Week** (resets Sunday). Distance / distance-engaged, whole miles, no space before `mi`/`km`. Labels match the version row; values sit one step smaller. Both shrink if the row would clip. First boot / install reseeds Today and Week from onboard qlogs so a Highland install still shows this week.

## Toggles

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph after Tesla BSM is clear. Warning + slide-to-enable. Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot). |
| `LaneColor` | Tesla blue | Custom UI only. `0` comma green, `1` Tesla blue. |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. One at a time. |
| `LudicrousEnabled` | off | Once per drive, not on a mid-drive reboot. Personal-use Spaceballs clip. |
| `BuckleSound` | off | Once, offroad or onroad. Rearm after a drive ≥20 min, else after 3 hours. |
| Delorean (`/data/delorean_sound`) | off | 88mph clip on going onroad. Once per drive after 1.5s stable. Personal use. |
| `WeatherNewsMode` | nice | Off / Nice / Unhinged. First drive of the Chicago-local day. Theme + LAN preview. |

## Screenshots

Hold the display 3s (don’t drag). White flash + shutter. PNG in `/data/media/0/screenshots`. LAN dashboard **Shots** tab (1px white frame). SSH/SFTP same path.

## LAN console

`http://<c4-ip>:8088` — settings, files, shots, clips (offroad, local routes), stats, updates. No password. Local Wi-Fi only. Not comma Connect.

Connect livestream is **stock** (parked). Custom on-road WebRTC viewer was removed so Connect stays compatible.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
