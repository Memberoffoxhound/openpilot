# TESLAPILOT

2026 Model 3 Highland (HW4). Stalkless. Comma 4.

Based on comma `release-mici` (0.11.1 / AGNOS 18.4). Do not merge master.
Master bumps AGNOS and the first-boot updater hangs the comma logo.

```
installer.comma.ai/Memberoffoxhound/Highland
```

Flash the device with flash.comma.ai first. This branch will not write AGNOS.

## Car

- Fingerprint pinned to TESLA_MODEL_3. EPS FW seed E4H015.05.0 so empty ISO-TP cannot MOCK.
- 3-bit DAS_steeringControlType. 2-bit ANGLE_CONTROL is LKAS on this EPS.
- Cooperative steering stays on.
- Engage / disengage is the right scroll-wheel button.
- Alpha longitudinal is available. Off = Tesla TACC. On = openpilot gas/brake.
- Auto lane change is off by default. Tesla BSM. 25 mph floor.

## UI

TESLAPILOT wordmark. Tesla font. TACC / LONG icon on home. Driving stats.

No deviceweb. No vSlam.

You are the driver.
