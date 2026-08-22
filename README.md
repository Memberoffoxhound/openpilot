# S3XYPilot

A Tesla-first fork of [comma.ai/openpilot](https://github.com/commaai/openpilot), built for **stalkless** Model 3 / Y (Highland and similar).

Based on **openpilot 0.11.12 `master`** as of **August 17, 2026**. This branch versions as **0.1.10.24**.

This is a **hobby project**. It is not intended for mainstream use. **Do not expect any semblance of support.** It was done for fun, to learn the ins and outs of programming for openpilot, and is heavily vibe coded with [Grok Build](https://grok.x.ai). **Install at your own risk.**

It should run on a **comma 3X**, but there are **no UI elements tailored to it**. The UI is built for **comma 4**.

Installer: [`installer.comma.ai/Memberoffoxhound/Highland`](https://installer.comma.ai/Memberoffoxhound/Highland)

---

## What this fork adds

Emphasis is an **alpha, local-only** web dashboard and **WebRTC livestream**. Nothing here talks to comma Connect for the stream.

### Stalkless Tesla

- **Engage / disengage** with the **right scroll-wheel button**
- **Virtual torque blending** with **cooperative steering** (on by default) — light wheel torque adds angle while engaged, classic openpilot feel, instead of a hard override. Still disengages if torsion-bar torque is high (~5 Nm)

### Alpha local dashboard + livestream

LAN only. Same Wi-Fi as the device. **Not** comma Prime LTE. **Not** comma TURN.

| | URL | What |
| --- | --- | --- |
| **On-Air livestream** | `http://<device-ip>:5001/` | WebRTC. Wide + driver cam, PiP / 3D / HUD. Wi-Fi or a non-Prime SIM. Toggle **On-Air** on the home screen or Settings → livestream |
| **Dashboard (PWA)** | `http://<device-ip>:8088/` | Settings, files under `/data`, updates, drive stats, local clips. No login. Alpha |

Connect parked livestream is unchanged. On-Air **turns off** if you leave Wi-Fi onto a comma Prime SIM so this fork does not bill comma for the stream.

### Other Highland bits

- **Auto Lane Change** — off by default. Stock is wheel-nudge. On is nudgeless after Tesla BSM is clear, engaged, over 25 mph. Enabling shows the warning cards + slide-to-confirm
- **Custom onroad UI** — Tesla-blue lanes, 8-way compass while engaged
- **Last / Week** trip miles and **distance** engaged %
- Home wordmark **S3XYPilot**, white Tesla T boot spinner
- Calibration card shows **pitch / yaw / roll**

Working branch is **`Highland`**. Repo stays named `openpilot` so the comma installer URL works.

---

## How to install

**Install at your own risk.** Read the whole chapter before you type the URL.

### Custom software URL

On the comma, when it asks for a software URL:

```
installer.comma.ai/Memberoffoxhound/Highland
```

Same thing: username **`Memberoffoxhound`**, branch **`Highland`**.

GitHub: [Memberoffoxhound/openpilot](https://github.com/Memberoffoxhound/openpilot) · branch [`Highland`](https://github.com/Memberoffoxhound/openpilot/tree/Highland)

Tesla car interface: [TeslaPilot-opendbc `Highland`](https://github.com/Memberoffoxhound/TeslaPilot-opendbc/tree/Highland)

### Warnings

- **Hobby. Not a product.** No support, no warranty, no “it should just work.”
- **You are the driver.** Hands on the wheel. You intervene. Auto lane change and cooperative steering do not change that.
- **Alpha dashboard and livestream.** Local Wi-Fi only. Pages can go blank, lag, or vanish. Do not point them at the internet.
- **Do not run On-Air on comma Prime LTE.** The toggle blocks it. Don’t try to work around that.
- **comma 4 UI.** comma 3X may boot it; the home screen, themes, and On-Air chrome are not built for that display.
- **Vibe coded.** Written with Grok Build as a learning project. Expect sharp edges.
- **You can get banned from comma servers** if a fork nerfs driver monitoring, nerfs actuation checks, or ships a broken panda safety. This fork does not touch those three. See [SAFETY.md](SAFETY.md). That is not a comma endorsement.
- **Local laws are yours.** Alpha software for research. MIT license, no warranty.

If any of that is a problem, install stock openpilot from [`openpilot.comma.ai`](https://openpilot.comma.ai) instead.

---

## User data

By default this software still uploads driving data to **comma** servers, same as openpilot. You can view it in [comma connect](https://connect.comma.ai/). You can turn uploads off in settings.

The **dashboard and On-Air stream are local**. They do not go through comma Connect.

---

## Licensing

Released under the [MIT License](LICENSE). This tree is a fork of [openpilot](https://github.com/commaai/openpilot). comma’s notice still applies:

> Any user of this software shall indemnify and hold harmless Comma.ai, Inc. and its directors, officers, employees, agents, stockholders, affiliates, subcontractors and customers from and against all allegations, claims, actions, suits, demands, damages, liabilities, obligations, losses, settlements, judgments, costs and expenses (including without limitation attorneys’ fees and costs) which arise out of, relate to or result from any use of this software by user.
>
> **THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. THIS IS NOT A PRODUCT.**
> **YOU ARE RESPONSIBLE FOR COMPLYING WITH LOCAL LAWS AND REGULATIONS.**
> **NO WARRANTY EXPRESSED OR IMPLIED.**
