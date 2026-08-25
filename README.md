# S3XYPilot

Tesla-first fork for **stalkless Model 3 / Y**. Hobby project. No support. Install at your own risk.

Driven on a **2026 Model 3 Highland**. Based on openpilot 0.11.12. This branch versions as **0.11.12**.

Installer: [`installer.comma.ai/Memberoffoxhound/Highland`](https://installer.comma.ai/Memberoffoxhound/Highland)

## Branches

- **`master`** — unmodified [comma.ai/openpilot](https://github.com/commaai/openpilot) mirror.
- **`Highland`** — S3XYPilot. Install this.
- **`K5`** — comma master + Auto Lane Change (confirm slider). For the Kia.

## Highland

Stalkless Teslas have no cruise stalk. Engage / disengage is the **right scroll-wheel button**. Cooperative steering stays on.

You are the driver. This fork does not change driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).

comma 4 UI. comma 3X may boot; UI is not tailored to it.

### Onroad

<!-- docs/screenshots/onroad-custom.png -->
Custom HUD (Theme → onroad UI): Tesla-blue lanes, compass (small left or large top-right). Stock comma HUD is one tap away.

<!-- docs/screenshots/home.png -->
Footer: **TACC** / **openpilot long** / **experimental**. Experimental is off and hidden on stock TACC. Tap the atom to toggle when OP long is on.

Home stats: **Today** / **Week** miles and distance-engaged %.

### Driving

- Auto Lane Change — off by default; Tesla stock BSM; warning + confirm; 25 mph min. Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot).
- Cooperative steering — on. Based on dzid26's implementation of cooperative steering (VTB). AmyJeanes landed the sunnypilot Tesla Coop Steering path.
- Scroll-wheel disengage — stalkless cancel. Based on dkiiv's implementation of stalkless scroll-wheel cancel, pulled from dzid26's Tesla fork.

### Theme

<!-- docs/screenshots/theme.png -->
Theme extras, **off by default**: Delorean 88mph clip (on going onroad, after ignition settles).

<!-- docs/screenshots/weather-preview.png -->
**Grok voice** — Theme → grok voice On, then scan the QR (or open `http://<c4-ip>:8088/grok`) and paste an [xAI API key](https://console.x.ai). Ara speaks. A 50px Grok mark sits after the Wi-Fi/LTE icon on home while it is on. Tap the mark for a full on-demand briefing (test hook; does not consume the day).

**Weather & news** — first drive of the local day (GPS). Off / Nice / Unhinged. Unhinged is NSFW (confirm on enable). Weather is always in. Default news is **NPR world**. Add topics on the Grok tab (one per line): `npr`, `cnn`, `comma`, `reddit:commaai`, `x:ApteraMotors`, or any Google News query such as `Aptera Motors`. Theme → preview is a short Ara sample.

On LTE a daily briefing is about **3–4 MB** (almost all of it is the Ara WAV). RSS + Grok chat are tens of KB. A preview is about **0.3 MB**. One briefing a day is roughly **90–120 MB/month**.

Setup and free-TTS notes: [`openpilot/selfdrive/weather_news/README.md`](openpilot/selfdrive/weather_news/README.md).

### Device

3s display hold → screenshot (`/data/media/0/screenshots`).

<!-- docs/screenshots/lan-console.png -->
LAN dashboard `http://<device-ip>:8088/` — local Wi-Fi, no login. comma Connect livestream is **stock** (parked only).

Planned shots live in [`docs/screenshots/`](docs/screenshots/README.md).

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

Stock install: [`openpilot.comma.ai`](https://openpilot.comma.ai)

## Special thanks

These are not original to this fork. Huge thanks.

- **Automatic Lane Change** — based on [rav4kumar](https://github.com/rav4kumar)'s implementation of Automatic Lane Change in sunnypilot ([#653](https://github.com/sunnypilot/sunnypilot/pull/653)), with [Jason Wen / sunnyhaibin](https://github.com/sunnyhaibin).
- **Cooperative steering** — based on [dzid26](https://github.com/dzid26)'s implementation of cooperative steering (virtual torque blending, `vtb` / `vtb-sla`). [AmyJeanes](https://github.com/AmyJeanes) landed Tesla Coop Steering in sunnypilot using native LKAS ([opendbc #287](https://github.com/sunnypilot/opendbc/pull/287)).
- **Stalkless scroll-wheel disengage** — based on [dkiiv](https://github.com/dkiiv)'s implementation of stalkless cancel (`DAS_accState == 13` → `ButtonType.cancel`, [opendbc #3203](https://github.com/commaai/opendbc/pull/3203)). Pulled from [dzid26](https://github.com/dzid26)'s Tesla fork.
