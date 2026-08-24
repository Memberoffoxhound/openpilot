# S3XYPilot Weather Lady + Elon News

Highland integration for Comma 4.

## What it does

- **First drive of the day only** (America/Chicago date): ~10 s after onroad is stable, one forecast + overnight note + two Elon-company news bites.
- **Off / Nice / Unhinged** — three-state toggle. Unhinged is `aggressive` in code.
- **Preview** plays the selected voice anytime, including parked. Does not consume the day. The button is lit for Nice and Unhinged, dim while Off.

## Voice

True neural Ara is not on-device. Personality is scripts + espeak-ng prosody.

Audio is rendered to WAV and played by **soundd** (same path as buckle / 88mph). `aplay` is not used — it loses to soundd on the C4 speaker.

espeak-ng is resolved in order: system binary, then a cached extract under `/data/weather_news` bootstrapped once from Debian arm64 packages. No apt required.

## On-device (Theme)

Comma 4 uses Theme:

| Control | Effect |
|---------|--------|
| weather & news | Off / Nice / Unhinged |
| preview | Speaks the selected mode. Lit when not Off. |

LAN console (`:8088`) has the same 3-way + one Preview button.

## Params

| Param | Values | Default |
|-------|--------|---------|
| `WeatherNewsMode` | `0` off, `1` nice, `2` aggressive | nice |
| `WeatherNewsEnable` | mirror of mode != off | on |
| `WeatherNewsAggressive` | mirror of mode == 2 | off |
| `WeatherNewsPreview` | `personable` / `aggressive` | (empty) |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` Chicago | set after a wav is queued |

SSH preview:

```bash
echo -n aggressive > /data/params/d/WeatherNewsPreview
```

## Process

`weather_news_d` is `always_run` so parked previews work. Optional — a crash does not block engage.

Cereal: `deviceState`, `gpsLocationExternal`. Onroad = `deviceState.started` stable 2 s, not `IsOffroad`.

## Data use

~2–3 MB per daily cycle (Open-Meteo + Google News RSS). One cycle per day when not Off.
