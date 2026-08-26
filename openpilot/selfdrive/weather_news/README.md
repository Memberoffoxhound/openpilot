Spoken briefing **three times a day**: once in the morning (5am–noon), once in the afternoon (noon–7pm), once after 7pm. The window you start the drive in is the only one that runs — missed windows stay missed. Or **every drive** if that toggle is on.

## Use Grok or Gemini

1. Theme → **Grok voice** (or **Gemini voice** once Gemini is active) → On. Home shows a 50px mark after Wi-Fi/LTE.
2. Scan the QR (or open `http://<c4-ip>:8088/grok` on the same Wi-Fi). The LAN tab is **Voice**.
3. On the LAN Voice page pick a provider and paste a key. It stays on the device (`DONT_LOG`).
   - **xAI** — [console.x.ai](https://console.x.ai). Chat `grok-4-fast`, voice Ara TTS.
   - **Gemini** — [aistudio.google.com](https://aistudio.google.com). Chat `gemini-3.6-flash`. Spoken voice is Ara if an xAI key is also saved, otherwise OpenAI `tts-1`.
   - **OpenAI** — [platform.openai.com](https://platform.openai.com). Chat `gpt-4o-mini`, voice `tts-1`.
   - **Groq** — [console.groq.com](https://console.groq.com). Chat Llama 3.3 70B. Add an OpenAI key too if you want spoken audio (Groq has no TTS).
4. Theme → weather & news: **Off / Nice / Unhinged**. Unhinged is NSFW (crude roast, not sexual); confirm on enable. Same modes for Grok and Gemini.
5. Topics: up to 6, autocomplete on the Voice page. Default is weather + `npr`.
6. Theme → **briefing length** 60 / 90 / 120 s. **briefing on wifi only** skips LTE.
7. Theme → **briefing playback**: **Standard** (clean) or **Boosted** (default, louder for road noise, less C4 crackle). Voice only.
8. Theme → **briefing schedule**: **3x a day** (default) or **every drive**. 3x a day is morning / afternoon / after 7pm, one each, never stacked. Every drive waits ~10s after onroad. Use it to test reliability.
9. Theme → **preview** speaks a short sample. Tap the **home mark** for a full on-demand briefing (test hook). Neither consumes the window / this drive.

While the selected AI writes and speaks, a **60px round bug** sits top-right onroad (same translucent dm_background as the DM / compass bugs). Grok uses the Grok mark; Gemini uses the Gemini sparkle. The mark starts dark and fills bottom-up like an old iOS app install, with a round progress ring. Home uses the same loading animation while a briefing is generated.

The active provider writes the briefing from **current** weather at your GPS location (city is requested in the prompt) plus your topics. TTS speaks that text only — no canned scripts. weather_news_d enhances the WAV (standard or boosted, 48 kHz) then soundd plays `/data/wxnews.wav` from a background decode so the 20 Hz audio thread does not stall.

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

Chat itself is ~5–30 KB (grok-4-fast or gemini-3.6-flash). A long reasoning dump can push that toward 100 KB. Still <5% of the WAV.

| Cadence (60 s briefing) | Month |
|---|---|
| 3x a day | **~270 MB** |
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

This fork stays on Grok Ara (or OpenAI tts-1). Do not re-add Piper/Kokoro on the C4.

| Param | |
|---|---|
| `GrokVoiceEnabled` | master switch. Off = silent, no home mark. |
| `GrokProvider` | `xai` (default) / `gemini` / `openai` / `groq`. |
| `XaiApiKey` | xAI key. `DONT_LOG`. LAN `/grok` only. |
| `GeminiApiKey` | Gemini key. `DONT_LOG`. LAN `/grok` only. Never in the repo. |
| `OpenaiApiKey` | OpenAI key. `DONT_LOG`. |
| `GroqApiKey` | Groq key. `DONT_LOG`. |
| `WeatherNewsMode` | `0` off, `1` nice, `2` aggressive. Default nice. |
| `WeatherNewsTopics` | Newline-separated topics, max 6. Default `npr`. |
| `WeatherNewsDuration` | `60` / `90` / `120` seconds. Default 60. |
| `WeatherNewsWifiOnly` | Skip fetch + TTS on cellular. Default off. |
| `WeatherNewsPlayback` | `0` standard, `1` boosted. Default boosted. |
| `WeatherNewsEveryDrive` | `0` 3x/day slots, `1` start of every drive. Default off. |
| `WeatherNewsOnDemand` | Home mark tap. Full briefing, no window consume. Test hook. |
| `WeatherNewsPreview` | `nice` or `aggressive`. Cleared on manager start. |
| `WeatherNewsLastRunDate` | `YYYY-MM-DD:morning\|afternoon\|evening` after a wav is queued. |
| `WeatherNewsStatus` | live button / onroad bug while a cycle runs |

`weather_news_d` is `always_run` and optional — a crash does not block engage.