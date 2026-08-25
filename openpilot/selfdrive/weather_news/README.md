# weather_news

Spoken forecast + two Tesla/SpaceX/xAI news bites on the **first drive of the local day**.

Theme → weather & news: **Off / Nice / Unhinged**. Preview speaks the selected voice (parked ok) and does not consume the day. The preview button is lit for Nice and Unhinged, dim while Off.

**Unhinged is NSFW.** Same voice and speed as Nice — just explicit. Enabling it on Theme or LAN requires a confirmation: not for kids, not for passengers who didn't ask.

soundd plays `/data/wxnews.wav` when `/data/wxnews_play` is set — same path as buckle / 88mph.

Voice picker on Theme: **gps · 3/10** (Piper lessac-medium), **high · 5/10** (lessac-high, default), **human · 8/10** (Kokoro). Unhinged is still the script. First tap of an uninstalled voice downloads it into `/data/weather_news` and the button shows queued → downloading voice → installing → ready. Piper/Kokoro run `nice(10)`. espeak-ng is fallback only if Piper cannot run.

Preview button shows status while it works: queued → fetching weather → getting news → downloading voice (first time) → rendering → playing.

| Param | |
|---|---|
| `WeatherNewsMode` | `0` off, `1` nice, `2` aggressive. Default nice. |
| `WeatherNewsVoice` | `gps` / `high` / `human`. Default high. |
| `WeatherNewsPreview` | `nice` or `aggressive`. Cleared on manager start. |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` after a wav is queued. |
| `WeatherNewsStatus` | live button text while a cycle or install runs |

`weather_news_d` is `always_run` and optional — a crash does not block engage. Onroad is `deviceState.started` stable 2s, then 10s. Forecast coords and the calendar day both come from GPS (device clock is UTC; 15° ≈ 1h). Open-Meteo + Google News RSS, ~2–3 MB per day when not Off.
