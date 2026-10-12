# Engineering notes

## A. Technology comparison (detail)

This is the long form of the comparison summarised in [RESEARCH.md](RESEARCH.md). All provider facts
were read on **2026-10-12**, from official documentation except where a figure is attributed to a
signed-in provider console or to our own API tests. Free-tier limits and model availability change
often, so each documented figure links to the page it came from. Figures we could not confirm on a
provider-owned page or by calling the API ourselves are marked `[UNVERIFIED]`.

### A.1 LLM providers

We need one text model that reliably returns JSON matching a Pydantic schema, accepts a full
podcast transcript in one request, and runs on a free tier with no billing account.

| | **Google Gemini** (`gemini-3.8-flash`) | **Groq** (`openai/gpt-oss-120b`) | **OpenAI** (paid reference only) |
|---|---|---|---|
| JSON / structured output | JSON Schema via `response_format` on `interactions.create`; the Python SDK converts a Pydantic model with `model_json_schema()`. Only a [subset of JSON Schema](https://ai.google.dev/gemini-api/docs/structured-output) is supported and "very large or deeply nested schemas may be rejected" | `json_schema` with `strict: true` (constrained decoding) on `gpt-oss-20b`, `gpt-oss-120b`, `qwen/qwen3.8-27b`. Every property must be required, `additionalProperties` must be `false`, and [optional fields are unsupported](https://console.groq.com/docs/structured-outputs) — use `anyOf` with `null`. Streaming and tool use cannot be combined with structured outputs | Not researched — paid reference only |
| Context window | [1M tokens, 64k max output](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) | [131,072 tokens, 65,536 max output](https://console.groq.com/docs/model/openai/gpt-oss-120b) | Not researched |
| Free-tier rate limits | Not in the docs — see A.2 for the figures we read from the AI Studio console | Not clearly labelled in the docs — see A.2 | No free tier for text tokens |
| Typical latency | Not published; we measure it ourselves during the build | [~500 tokens/sec](https://console.groq.com/docs/model/openai/gpt-oss-120b) throughput; end-to-end latency not published, measured during the build | Not researched |
| Python SDK | `google-genai`, [2.3.0 or later](https://ai.google.dev/gemini-api/docs/interactions) for the Interactions API | [`pip install groq`](https://console.groq.com/docs/quickstart), key from `GROQ_API_KEY` | `openai` |
| Free-tier data use | Google "uses the content you submit … to provide, improve, and develop" its products, "human reviewers may read, annotate, and process your API input and output", and the terms say **"Do not submit sensitive, confidential, or personal information to the Unpaid Services"** ([terms](https://ai.google.dev/gemini-api/terms)). The pricing page's free plan card reads "Content used to improve our products" | "By default, Groq does not retain customer data for inference requests"; reliability/abuse logs kept "up to 30 days" with an opt-out, and Zero Data Retention is available to all customers ([data page](https://console.groq.com/docs/your-data)). That page makes no statement either way about training on customer data `[UNVERIFIED]`. The general [website privacy policy](https://groq.com/privacy-policy) does not mention model training, but does claim a legitimate interest in using information to "improve, and develop the Services" | Not applicable |
| Cost beyond free tier | [$0.75 / $3.75 per 1M in/out](https://ai.google.dev/gemini-api/docs/pricing) through 2026-12-31, then $1.50 / $7.50 from 2027-01-01 | [$0.15 / $0.60 per 1M in/out](https://console.groq.com/docs/model/openai/gpt-oss-120b), cached input $0.075 | [gpt-5-nano $0.05 / $0.40; gpt-5-mini $0.25 / $2.00](https://developers.openai.com/api/docs/pricing) |
| Known issues | The Gemini 2.5 family is [limited to projects that already used it](https://ai.google.dev/gemini-api/docs/models); new projects are pointed at 3.5 Flash-Lite or 3.8 Flash. `minimal` thinking level errors on 3.8 Flash. Free-tier models can return a transient 503 under load (A.4). Google now recommends the Interactions API for all new projects (A.3) | Structured-output strict mode covers only a few models, and the rate-limit documentation is internally inconsistent (A.2) | No free tier |

### A.2 Free-tier rate limits

Neither provider publishes usable free-tier limits in its documentation. Gemini's
[rate limits page](https://ai.google.dev/gemini-api/docs/rate-limits) has no Free row at all and
says limits "can be viewed in Google AI Studio", so the Gemini figures below were read from the AI
Studio rate-limit console while signed in. Groq's [rate limits page](https://console.groq.com/docs/rate-limits)
shows tabs for Free and Developer plans but states the figures given are Developer base limits, and
its [model page](https://console.groq.com/docs/model/openai/gpt-oss-120b) gives different numbers
again (1K RPM / 250K TPM) for the same model.

| Model | RPM | TPM | RPD | TPD | Source |
|---|---|---|---|---|---|
| `gemini-3.8-flash` | 5 | 250K | 20 | – | AI Studio console, viewed 2026-10-12 |
| `gemini-3.5-flash-lite` | 15 | 250K | 500 | – | AI Studio console, viewed 2026-10-12 |
| `gemini-3.1-flash-lite` | 15 | 250K | 500 | – | AI Studio console, viewed 2026-10-12 |
| `gemma-4-31b` | 30 | 16K | 14.4K | – | AI Studio console, viewed 2026-10-12 |
| `openai/gpt-oss-120b` | 30 | 8K | 1K | 200K | [Groq rate limits](https://console.groq.com/docs/rate-limits) (mixed Free/Developer labelling) |
| `openai/gpt-oss-20b` | 30 | 8K | 1K | 200K | [Groq rate limits](https://console.groq.com/docs/rate-limits) (mixed Free/Developer labelling) |
| `qwen/qwen3.8-27b` | 30 | 8K | 1K | 200K | [Groq rate limits](https://console.groq.com/docs/rate-limits) (mixed Free/Developer labelling) |

A 30–40 minute episode is roughly 8K tokens, so tokens per minute is the binding constraint, not
requests. Groq's free limit of 8K TPM and Gemma's 16K TPM cannot process a normal episode in a
single call — they would force us to chunk the transcript, which breaks the one-call design and
makes cross-episode summaries harder. `gemini-3.8-flash` has the token headroom but only 20 requests
per day, shared between our own testing, the demo recording and every reviewer who opens the live
URL; that is not enough to survive assessment. The two Flash Lite models have both the token
headroom and 500 RPD. The ~8K token estimate is our own figure and we will replace it with a real
token count from the sample transcript.

Being listed in the console does not prove a model is callable: the console showed
`gemini-2.5-flash` with limits, but it returns 404 for new accounts (A.4).

### A.3 Interactions API

Google's [Interactions API](https://ai.google.dev/gemini-api/docs/interactions) is "recommended for
all new projects" and is where future models and features launch; the older `generateContent`
"remains fully supported". The structured-output docs and the REST example on the
[API key page](https://ai.google.dev/gemini-api/docs/api-key) both now use `interactions`, so we
write against `client.interactions.create()` rather than `generate_content`.

### A.4 Our key tests (2026-10-12)

Tested with the `google-genai` Python SDK. Both provider keys authenticate: `models.list` succeeded
on Gemini and on Groq.

| Model | Result |
|---|---|
| `gemini-3.8-flash` | `generate_content` OK |
| `gemini-3.5-flash-lite` | OK |
| `gemini-3.1-flash-lite` | First attempt 503 UNAVAILABLE, "This model is currently experiencing high demand… try again later"; OK on retry after ~1 minute |
| `gemini-2.5-flash` | 404, "no longer available to new users, use gemini-3.8-flash" |

The 404 matches the model page above, so we must only call models available to new accounts. The 503
is the more useful result: a free-tier model can be temporarily overloaded even with a valid key and
quota remaining, and it recovered on its own within a minute. That is a transient failure, not an
auth or quota failure, and it has to be handled differently from both — it argues for retry with
backoff plus a fallback model on a separate quota.

Since 2026-05-28, "all new API keys created in Google AI Studio are automatically created as auth
keys" ([API key page](https://ai.google.dev/gemini-api/docs/api-key)); these are the keys that print
with an `AQ.` prefix. That page documents the key *type* but not the string format. Developer-forum
reports attribute `401 UNAUTHENTICATED / ACCESS_TOKEN_TYPE_UNSUPPORTED` failures to older clients
that expect the previous `AIza` format `[UNVERIFIED — forum reports, not official docs]`. Our key
works through `google-genai`, which is consistent with those reports.

### A.5 Hosting

We need a host that runs a Streamlit app on a free tier with no billing account, keeps one API key
server-side, and stays reachable for reviewers for at least two weeks.

| | **Streamlit Community Cloud** | **Hugging Face Spaces** |
|---|---|---|
| Runs Streamlit? | Yes, it is the first-party host | **Not as a native SDK.** The [config reference](https://huggingface.co/docs/hub/spaces-config-reference) says `sdk` "Can be either `gradio`, `docker`, or `static`" and `sdk_version` is "the version of Gradio to use". A Streamlit app would have to be a Docker Space |
| Free tier | [690MB–2.7GB memory, 0.078–2 CPU cores, up to 50GB storage](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app), listed as of February 2024 and "may change at any time without notice" | CPU Basic is [2 vCPU, 16GB RAM, 50GB non-persistent disk at no hourly cost](https://huggingface.co/docs/hub/spaces-overview) — but "Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts". Only static Spaces are free for everyone |
| Sleep / wake | Sleeps after [12 hours with no traffic](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app); anyone with view access wakes it with a "Yes, get this app back up!" button | On free hardware a Space will ["go to sleep" and stop executing after a period of time if unused](https://huggingface.co/docs/hub/spaces-overview); the period is not given `[UNVERIFIED]` |
| Secrets | Saved in the app's settings and read with `st.secrets`; `.streamlit/secrets.toml` is local-only and ["should never be committed to your repository"](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management) | Settings-page secrets, private and unreadable after being set, exposed to the app as environment variables; a secrets scanner warns on hard-coded values ([overview](https://huggingface.co/docs/hub/spaces-overview)) |
| Repo visibility | App visibility follows the repo, and ["You are only allowed one private app at a time"](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app). Our repo is public, so this does not bind us | Public, protected or private; protected needs a paid plan |
| Upload limit | Streamlit's own [`maxUploadSize` default is 200](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) MB | Same Streamlit setting would apply inside a Docker Space; no Spaces-specific request limit documented `[UNVERIFIED]` |
| Logs | "Manage app" → Cloud logs, downloadable; rebooting also clears the app's memory | Not covered on the overview page `[UNVERIFIED]` |

Hugging Face Spaces is not a free option for this app. Streamlit is no longer a Spaces SDK, so we
would have to build a Docker Space, and creating a Docker Space requires a PRO plan on a personal
account. That conflicts with free-tier-only, so Streamlit Community Cloud is the only one of the two
we can actually deploy on. Because Spaces is ruled out on cost, we did not chase the three
unconfirmed Spaces details above any further.

Note a documentation inconsistency: Hugging Face still publishes a
[Streamlit Spaces page](https://huggingface.co/docs/hub/spaces-sdks-streamlit) describing
`sdk: streamlit`, but it cites Streamlit 1.25.0 and links to retired Streamlit docs paths, and the
current config reference does not list `streamlit` as a valid SDK. We treat the config reference as
authoritative.

### A.6 Transcription (not built)

Audio upload is out of scope for this build. This is the comparison we would start from if we added
it.

| | **Groq Whisper** | **Gemini audio input** | **OpenAI transcription** |
|---|---|---|---|
| File limits | [25 MB free tier, 100 MB dev tier](https://console.groq.com/docs/speech-to-text); larger files via a `url` parameter instead of upload. Minimum billed length 10 seconds | [20 MB total inline request size](https://ai.google.dev/gemini-api/docs/audio) including prompt and files, or the Files API for larger; up to 9.5 hours per prompt | [25 MB](https://developers.openai.com/api/docs/guides/speech-to-text); larger files must be compressed or split into 25 MB chunks |
| Formats | flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm | WAV, MP3, AIFF, AAC, OGG, FLAC, MPEG, M4A, L16, Opus, ALAW, MULAW, WebM | mp3, mp4, mpeg, mpga, m4a, wav, webm |
| Timestamps | API-derived: `response_format=verbose_json` with `timestamp_granularities[]` of `word` and/or `segment` (segment is the default) | **No documented structured segment field** — timestamps come from the model's text output, or from a response schema you define yourself | API-derived, but `timestamp_granularities[]` is supported only on `whisper-1`, and the page documents `word` granularity without explicitly documenting `segment` `[UNVERIFIED]`. `gpt-4o-transcribe-diarize` returns segments with `start`/`end` via `diarized_json` |
| Cost | `whisper-large-v3` $0.111/hour, `whisper-large-v3-turbo` $0.04/hour | Audio counts as input tokens at [32 tokens per second](https://ai.google.dev/gemini-api/docs/audio) (1,920/minute), so it draws on the same free-tier token quota | [whisper-1 $0.006/min, gpt-transcribe $0.0045/min](https://developers.openai.com/api/docs/pricing); no free tier listed |

OpenAI's transcription endpoint is a credible option on capability — its limits and formats are
close to Groq's — but it has no free tier, so the free-tiers-only rule excludes it before quality
or latency enters the discussion. That leaves Groq Whisper as the only option returning timestamps
derived from the transcription itself. Gemini would have the model write the times, which our
grounding rule forbids. So adding audio means adding a second provider: Groq for segments, Gemini
for text. The 25 MB free-tier cap is the other constraint: at a
typical 128 kbps podcast bitrate that is roughly 26 minutes of audio by our own arithmetic, so a
40-minute episode would exceed it and need the `url` parameter.

Groq's speech-to-text page also contradicts itself: its Python example comment says to set
`response_format` to `json` for timestamps while the parameter table requires `verbose_json`. The
table is the one to follow.

### A.7 Sources
- [Gemini models](https://ai.google.dev/gemini-api/docs/models) — model IDs; 2.5 family restricted to prior users, which explains our 404.
- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) — 1M context, 64k output.
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) — tier definitions; free-tier numbers live in AI Studio, not the docs.
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) — free tier covers Flash; paid rates and the 2026-12-31 cutoff.
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) — Pydantic to JSON Schema, and only a subset is supported.
- [Interactions API](https://ai.google.dev/gemini-api/docs/interactions) — recommended entry point; `generateContent` is legacy.
- [Gemini terms](https://ai.google.dev/gemini-api/terms) — unpaid-tier inputs improve Google products and may be read by humans.
- [Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key) — auth keys since 2026-05-28; never ship keys client-side.
- [Gemini audio](https://ai.google.dev/gemini-api/docs/audio) — 20 MB inline, 32 tokens/second, no segment timestamp field.
- [Groq gpt-oss-120b](https://console.groq.com/docs/model/openai/gpt-oss-120b) — price, context, and the only published throughput figure.
- [Groq rate limits](https://console.groq.com/docs/rate-limits) — per-model limits and the Free/Developer inconsistency.
- [Groq structured outputs](https://console.groq.com/docs/structured-outputs) — strict mode models; optional fields unsupported.
- [Your data in GroqCloud](https://console.groq.com/docs/your-data) — no retention by default, 30-day abuse logs, ZDR.
- [Groq speech-to-text](https://console.groq.com/docs/speech-to-text) — 25 MB free cap and `verbose_json` segment timestamps.
- [Groq models](https://console.groq.com/docs/models), [quickstart](https://console.groq.com/docs/quickstart), [privacy policy](https://groq.com/privacy-policy) — context windows, SDK name and key variable, and privacy wording we could not reconcile with the data page.
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing) — paid baseline; no free text-token tier, and transcription from $0.0045/min.
- [OpenAI speech-to-text](https://developers.openai.com/api/docs/guides/speech-to-text) — 25 MB cap, formats, and that `timestamp_granularities[]` is `whisper-1` only.
- [OWASP API Security Project](https://api-security.owasp.org/) and [API4:2023 Unrestricted Resource Consumption](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption) — rate limiting, payload size caps and spending limits, the brief's own reference.
- [Edison Research, UK Podcast Consumer 2025](https://ssrs.com/insights/the-uk-podcast-consumer-2025/) — 71% ever, 51% last month, 33% last week among UK adults 16+, published 7 August 2025. Edison Research now publishes under SSRS; the old edisonresearch.com URL redirects there.
- [Streamlit: manage your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app) — resource ceilings, 12-hour sleep, logs.
- [Streamlit secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management) — `st.secrets`; never commit `secrets.toml`.
- [Streamlit share your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app) — app visibility follows the repo.
- [Streamlit config.toml](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) — `maxUploadSize` defaults to 200 MB.
- [Spaces overview](https://huggingface.co/docs/hub/spaces-overview) — CPU Basic specs, secrets, sleep, and the paid-plan requirement.
- [Spaces config reference](https://huggingface.co/docs/hub/spaces-config-reference) — `sdk` accepts only `gradio`, `docker`, `static`.
- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/) — the 2025 entries we mapped mitigations against.
