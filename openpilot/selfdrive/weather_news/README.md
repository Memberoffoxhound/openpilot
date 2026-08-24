# weather_news

Spoken forecast + two Tesla/SpaceX/xAI news bites on the **first drive of the local day**.

Theme → weather & news: **Off / Nice / Unhinged**. Preview speaks the selected voice (parked ok) and does not consume the day. The preview button is lit for Nice and Unhinged, dim while Off.

soundd plays `/data/wxnews.wav` when `/data/wxnews_play` is set — same path as buckle / 88mph. espeak-ng: system binary, else a one-shot Debian arm64 extract under `/data/weather_news`.

| Param | |
|---|---|
| `WeatherNewsMode` | `0` off, `1` nice, `2` aggressive. Default nice. |
| `WeatherNewsPreview` | `nice` or `aggressive`. Cleared on manager start. |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` after a wav is queued. |

`weather_news_d` is `always_run` and optional — a crash does not block engage. Onroad is `deviceState.started` stable 2s, then 10s. Forecast coords and the calendar day both come from GPS (device clock is UTC; 15° ≈ 1h). Open-Meteo + Google News RSS, ~2–3 MB per day when not Off.
