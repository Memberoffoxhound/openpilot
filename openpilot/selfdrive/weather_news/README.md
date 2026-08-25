# weather_news

Spoken briefing on the **first drive of the local day** (GPS day + coords).

## Use Grok

1. Theme → **Grok voice** → On. Home shows a 50px Grok mark after Wi-Fi/LTE.
2. Scan the QR (or open `http://<c4-ip>:8088/grok` on the same Wi-Fi).
3. Paste an API key from [console.x.ai](https://console.x.ai). It stays on the device (`XaiApiKey`, never logged).
4. Theme → weather & news: **Off / Nice / Unhinged**. Unhinged is NSFW; confirm on enable.
5. On `/grok`, set **daily topics** (one per line). Default is `npr` (NPR world). Weather is always included.
6. Theme → **preview** speaks a short Ara sample. Tap the **home Grok mark** for a full on-demand briefing (test hook). Neither consumes the day.

Grok `grok-4.6` writes the briefing. Ara TTS (`POST /v1/tts`, `voice_id=ara`) speaks it. soundd plays `/data/wxnews.wav`. No on-device synthesizers.

Topic aliases: `npr`, `cnn`, `comma` (blog.comma.ai), `reddit` or `reddit:commaai`, `x` or `x:ApteraMotors`. Anything else is a Google News search (`Aptera Motors`).

## LTE

Almost all of the bytes are the WAV.

| Event | On the wire |
|---|---|
| Daily briefing | ~3–4 MB (60–80 s, 24 kHz PCM) |
| Theme preview | ~0.3 MB (~6 s) |
| RSS (NPR + extra topics) | ~50–150 KB |
| Grok chat | ~10 KB |
| Open-Meteo | ~5 KB |

One briefing/day ≈ **90–120 MB/month**. Preview every day adds ~10 MB. Wi-Fi uses none of the SIM.

## Free TTS (few queries)

Ara is paid xAI (~$15 / 1M chars). A briefing is ~1k chars, so a dollar covers hundreds of days.

If you do not want an xAI bill, these free tiers cover this volume:

| API | Free enough? | Notes |
|---|---|---|
| [Microsoft Edge TTS](https://github.com/rany2/edge-tts) | Yes, no key | Same network-TTS idea as Ara. Not wired here. |
| [Google Cloud TTS](https://cloud.google.com/text-to-speech) | ~1M WaveNet chars/month | GCP account. |
| [Azure Neural TTS](https://learn.microsoft.com/azure/ai-services/speech-service/text-to-speech) | 500k chars/month | Azure account. |
| [ElevenLabs](https://elevenlabs.io) | ~10k chars/month | Tight if you preview a lot. |

This fork stays on Grok Ara. Do not re-add Piper/Kokoro on the C4.

| Param | |
|---|---|
| `GrokVoiceEnabled` | master switch. Off = silent, no home mark. |
| `XaiApiKey` | xAI key. `DONT_LOG`. LAN `/grok` only. |
| `WeatherNewsMode` | `0` off, `1` nice, `2` aggressive. Default nice. |
| `WeatherNewsTopics` | Newline-separated topics. Default `npr`. |
| `WeatherNewsOnDemand` | Home Grok-mark tap. Full briefing, no day consume. Test hook. |
| `WeatherNewsPreview` | `nice` or `aggressive`. Cleared on manager start. |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` after a wav is queued. |
| `WeatherNewsStatus` | live button text while a cycle runs |

`weather_news_d` is `always_run` and optional — a crash does not block engage.
