# S3XYPilot Weather Lady + Elon News

Full integration on the **Highland** branch for Comma 4 / 2026 Model 3 Highland.

## What it does

- **First drive of the day only**: ~10 s after going onroad, one weather forecast + overnight note + 2 Elon-company news bites.
- **Personable** mode (default): warm, friendly weather lady.
- **Aggressive / Ara** mode: foul-mouthed, innuendo-heavy delivery styled after Grok Ara + classic MF’n Pebble weather. Prosody is faster, lower, rougher via espeak-ng.
- **Preview anytime** (including offroad) so you can test voices without waiting for tomorrow.

## Params / toggles

| Param | Values | Default |
|-------|--------|---------|
| `WeatherNewsEnable` | `1` / `0` | on |
| `WeatherNewsAggressive` | `1` / `0` | off (personable) |
| `WeatherNewsPreview` | `personable` or `aggressive` | (empty) |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` | set automatically |

Write them under `/data/params/d/` or via Params if the key is registered.

### Preview example (SSH)

```bash
echo -n aggressive > /data/params/d/WeatherNewsPreview
# process picks it up within ~1 s and clears the flag
```

### Force personable daily mode

```bash
echo -n 0 > /data/params/d/WeatherNewsAggressive
echo -n 1 > /data/params/d/WeatherNewsEnable
```

## Voice notes (Grok Ara)

True neural Ara voice is not available on the device. Personality is carried by:

1. **Aggressive scripts** — swearing, innuendo, attitude.
2. **Prosody** — espeak-ng `en-us+m3`, pitch 28, speed 175 for aggressive; `en-us+f3`, pitch 55, speed 145 for personable.

If neither `espeak-ng` nor `espeak` is present, text still prints to the log.

## Process

Registered in `system/manager/process_config.py` as `weather_news_d` with `always_run` so previews work parked.

## Data use

~2–3 MB per daily cycle (Open-Meteo JSON + Google News RSS). One cycle per day when enabled.

## Install

Already on Highland. After update/reboot the process starts with the manager.

```
installer.comma.ai/Memberoffoxhound/Highland
```
