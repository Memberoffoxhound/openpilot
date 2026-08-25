Spoken briefing on the **first drive of the local day** (GPS day + coords), or **every drive** if that toggle is on.

## Use Grok

1. Theme → **Grok voice** → On. Home shows a 50px Grok mark after Wi-Fi/LTE.
2. Scan the QR (or open `http://<c4-ip>:8088/grok` on the same Wi-Fi).
3. On the LAN Grok page pick a provider and paste a key. It stays on the device (`DONT_LOG`).
   - **xAI** — [console.x.ai](https://console.x.ai). Chat `grok-4-fast`, voice Ara TTS.
   - **OpenAI** — [platform.openai.com](https://platform.openai.com). Chat `gpt-4o-mini`, voice `tts-1`.
   - **Groq** — [console.groq.com](https://console.groq.com). Chat Llama 3.3 70B. Add an OpenAI key too if you want spoken audio (Groq has no TTS).
4. Theme → weather & news: **Off / Nice / Unhinged**. Unhinged is NSFW; confirm on enable.
5. Topics: up to 6, autocomplete on the Grok page. Default is weather + `npr`.
6. Theme → **briefing length** 60 / 90 / 120 s. **briefing on wifi only** skips LTE.
7. Theme → **briefing schedule**: **once a day** (default) or **every drive**. Every drive waits ~10s after onroad, same as the first-drive path. Use it to test reliability.
8. Theme → **preview** speaks a short Ara sample. Tap the **home Grok mark** for a full on-demand briefing (test hook). Neither consumes the day / this drive.

While Grok writes and speaks, a **60px round Grok bug** sits top-right onroad (same translucent dm_background as the DM / compass bugs). The mark starts dark and fills bottom-up like an old iOS app install, with a round progress ring.

The active provider writes the briefing from weather + your topics. TTS speaks that text only — no canned scripts. weather_news_d enhances the WAV (warmth + loudness + 48 kHz) then soundd plays `/data/wxnews.wav` from a background decode so the 20 Hz audio thread does not stall.

Topic aliases: `npr`, `cnn`, `comma` (blog.comma.ai), `reddit` or `reddit:commaai`, `x` or `x:ApteraMotors`. Anything else is a Google News search (`Aptera Motors`).

## LTE

Almost all of the bytes are the **TTS WAV**. Chat, RSS, and weather are noise next to it.

24 kHz 16-bit mono PCM from Ara:

| Duration | WAV on the wire | Chat + RSS + weather | **Per briefing** |
|---|---|---|---|
| 60 s | ~2.8 MB | ~0.05–0.25 MB | **~3.0 MB** |
| 90 s | ~4.1 MB | ~0.05–0.25 MB | **~4.3 MB** |
| 120 s | ~5.5 MB | ~0.05–0.25 MB | **~5.7 MB** |
| Theme preview (~10 s) | ~0.5 MB | ~10 KB | **~0.5 MB** |

Chat itself is ~5–30 KB (grok-4-fast). A long reasoning dump can push that toward 100 KB. Still <5% of the WAV.

| Cadence (60 s briefing) | Month |
|---|---|
| Once a day | **~90 MB** |
| Every drive, 4 drives/day | **~360 MB** |
| Every drive, 8 drives/day | **~720 MB** |
| Preview once a day extra | +~15 MB |

Wi-Fi only uses none of the SIM. Logs print `weather_news: lte chat=… tts=… total=…` after each briefing.

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
| `GrokProvider` | `xai` (default) / `openai` / `groq`. |
| `XaiApiKey` | xAI key. `DONT_LOG`. LAN `/grok` only. |
| `OpenaiApiKey` | OpenAI key. `DONT_LOG`. |
| `GroqApiKey` | Groq key. `DONT_LOG`. |
| `WeatherNewsMode` | `0` off, `1` nice, `2` aggressive. Default nice. |
| `WeatherNewsTopics` | Newline-separated topics, max 6. Default `npr`. |
| `WeatherNewsDuration` | `60` / `90` / `120` seconds. Default 60. |
| `WeatherNewsWifiOnly` | Skip fetch + TTS on cellular. Default off. |
| `WeatherNewsEveryDrive` | `0` first drive of the local day, `1` start of every drive. Default off. |
| `WeatherNewsOnDemand` | Home Grok-mark tap. Full briefing, no day consume. Test hook. |
| `WeatherNewsPreview` | `nice` or `aggressive`. Cleared on manager start. |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD` after a wav is queued. |
| `WeatherNewsStatus` | live button / onroad bug while a cycle runs |

`weather_news_d` is `always_run` and optional — a crash does not block engage.