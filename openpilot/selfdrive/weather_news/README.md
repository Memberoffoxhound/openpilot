# S3XYPilot Weather Lady + Elon News

Full integration on **Highland** for Comma 4 / 2026 Model 3 Highland.

## What it does

- **First drive of the day only**: ~10 s after going onroad, one weather forecast + overnight note + 2 Elon-company news bites.
- **Personable** mode (default): warm, friendly weather lady.
- **Aggressive / Ara** mode: foul-mouthed, innuendo-heavy delivery styled after Grok Ara + classic MF’n Pebble weather.
- **Preview anytime** (including offroad) from the LAN console or SSH.

## Voice (Grok Ara)

True neural Ara is not on-device. Personality is carried by:

1. **Aggressive scripts** — swearing, innuendo, attitude (`weather_lady.py` / `news_bites.py`).
2. **Prosody** — espeak-ng → WAV → `aplay`:
   - Ara: `en-us+m3`, pitch 26, speed 178, amplitude 200
   - Personable: `en-us+f3`, pitch 58, speed 142, amplitude 170

If espeak-ng/espeak is missing, text still logs. On a stock C4 image install espeak-ng if needed:

```bash
sudo apt-get update && sudo apt-get install -y espeak-ng alsa-utils
```

## LAN console (deviceweb :8088)

**Settings → Weather Lady**

| Control | Effect |
|---------|--------|
| Enable weather + news | Master on/off |
| Ara / aggressive voice | Daily-cycle mode |
| Preview personable | One-shot sample now |
| Preview Ara | One-shot foul sample now |

Also on the Status tab: last run date + preview buttons.

API: `POST /api/weather/preview` with `{"mode":"personable"|"aggressive"}`.

## Params

| Param | Values | Default |
|-------|--------|---------|
| `WeatherNewsEnable` | `1` / `0` | on |
| `WeatherNewsAggressive` | `1` / `0` | off (personable) |
| `WeatherNewsPreview` | `personable` / `aggressive` | (empty) |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` | set automatically |

SSH preview:

```bash
echo -n aggressive > /data/params/d/WeatherNewsPreview
```

## Process

Registered in `system/manager/process_config.py` as `weather_news_d` with `always_run` so previews work parked.

Cereal: `deviceState`, `selfdriveState`, `gpsLocationExternal`, `liveLocationKalman` for onroad + location.

## Data use

~2–3 MB per daily cycle (Open-Meteo + Google News RSS). One cycle per day when enabled.

## Install

```
installer.comma.ai/Memberoffoxhound/Highland
```

After update/reboot the process starts with the manager. Open `http://<device-ip>:8088` on LAN to toggle and preview.
