# Research

All provider facts below were read on **2026-10-12**, from official documentation except where a
figure is attributed to a signed-in provider console or to our own API tests. Free-tier limits and
model availability change often, so each documented figure links to the page it came from. Figures
we could not confirm on a provider-owned page or by calling the API ourselves are marked
`[UNVERIFIED]`.

## 1. LLM provider comparison

We need one text model that reliably returns JSON matching a Pydantic schema, accepts a full
podcast transcript in one request, and runs on a free tier with no billing account.

| | **Google Gemini** (`gemini-3.8-flash`) | **Groq** (`openai/gpt-oss-120b`) | **OpenAI** (paid reference only) |
|---|---|---|---|
| JSON / structured output | JSON Schema via `response_format` on `interactions.create`; the Python SDK converts a Pydantic model with `model_json_schema()`. Only a [subset of JSON Schema](https://ai.google.dev/gemini-api/docs/structured-output) is supported and "very large or deeply nested schemas may be rejected" | `json_schema` with `strict: true` (constrained decoding) on `gpt-oss-20b`, `gpt-oss-120b`, `qwen/qwen3.8-27b`. Every property must be required, `additionalProperties` must be `false`, and [optional fields are unsupported](https://console.groq.com/docs/structured-outputs) — use `anyOf` with `null`. Streaming and tool use cannot be combined with structured outputs | Not researched — paid reference only |
| Context window | [1M tokens, 64k max output](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) | [131,072 tokens, 65,536 max output](https://console.groq.com/docs/model/openai/gpt-oss-120b) | Not researched |
| Free-tier rate limits | Not in the docs — see the table below for the figures we read from the AI Studio console | Not clearly labelled in the docs — see the table below | No free tier for text tokens |
| Typical latency | Not published; to be measured in P3 | [~500 tokens/sec](https://console.groq.com/docs/model/openai/gpt-oss-120b) throughput; end-to-end latency not published, to be measured in P3 | Not researched |
| Python SDK | `google-genai`, [2.3.0 or later](https://ai.google.dev/gemini-api/docs/interactions) for the Interactions API | [`pip install groq`](https://console.groq.com/docs/quickstart), key from `GROQ_API_KEY` | `openai` |
| Free-tier data use | Google "uses the content you submit … to provide, improve, and develop" its products, "human reviewers may read, annotate, and process your API input and output", and the terms say **"Do not submit sensitive, confidential, or personal information to the Unpaid Services"** ([terms](https://ai.google.dev/gemini-api/terms)). The pricing page's free plan card reads "Content used to improve our products" | "By default, Groq does not retain customer data for inference requests"; reliability/abuse logs kept "up to 30 days" with an opt-out, and Zero Data Retention is available to all customers ([data page](https://console.groq.com/docs/your-data)). That page makes no statement either way about training on customer data `[UNVERIFIED]`. The general [website privacy policy](https://groq.com/privacy-policy) does not mention model training, but does claim a legitimate interest in using information to "improve, and develop the Services" | Not applicable |
| Cost beyond free tier | [$0.75 / $3.75 per 1M in/out](https://ai.google.dev/gemini-api/docs/pricing) through 2026-12-31, then $1.50 / $7.50 from 2027-01-01 | [$0.15 / $0.60 per 1M in/out](https://console.groq.com/docs/model/openai/gpt-oss-120b), cached input $0.075 | [gpt-5-nano $0.05 / $0.40; gpt-5-mini $0.25 / $2.00](https://developers.openai.com/api/docs/pricing) |
| Known issues | The Gemini 2.5 family is [limited to projects that already used it](https://ai.google.dev/gemini-api/docs/models); new projects are pointed at 3.5 Flash-Lite or 3.8 Flash. `minimal` thinking level errors on 3.8 Flash. Free-tier models can return a transient 503 under load (we saw one, below). Google now recommends the Interactions API for all new projects (see below) | Structured-output strict mode covers only a few models, and the rate-limit documentation is internally inconsistent (above) | No free tier |

### Free-tier rate limits

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

**Impact.** A 30–40 minute episode is roughly 8K tokens, so tokens per minute is the binding
constraint, not requests. Groq's free limit of 8K TPM and Gemma's 16K TPM cannot process a normal
episode in a single call — they would force us to chunk the transcript, which breaks the one-call
design and makes cross-episode summaries harder. `gemini-3.8-flash` has the token headroom but only
20 requests per day, shared between our own testing, the demo recording and every reviewer who
opens the live URL; that is not enough to survive assessment. The two Flash Lite models have both
the token headroom and 500 RPD. The ~8K token estimate is our own figure and we will replace it
with a real token count from the sample transcript in P3.

Being listed in the console does not prove a model is callable: the console showed
`gemini-2.5-flash` with limits, but it returns 404 for new accounts (see below).

### Interactions API

Google's [Interactions API](https://ai.google.dev/gemini-api/docs/interactions) is "recommended for
all new projects" and is where future models and features launch; the older `generateContent`
"remains fully supported". The structured-output docs and the REST example on the
[API key page](https://ai.google.dev/gemini-api/docs/api-key) both now use `interactions`, so if we
pick Gemini we should write against `client.interactions.create()` rather than `generate_content`.

### Our key tests (2026-10-12)

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
backoff plus a fallback model on a separate quota. Carried forward to the reliability section of the
engineering notes.

Since 2026-05-28, "all new API keys created in Google AI Studio are automatically created as auth
keys" ([API key page](https://ai.google.dev/gemini-api/docs/api-key)); these are the keys that print
with an `AQ.` prefix. That page documents the key *type* but not the string format. Developer-forum
reports attribute `401 UNAUTHENTICATED / ACCESS_TOKEN_TYPE_UNSUPPORTED` failures to older clients
that expect the previous `AIza` format `[UNVERIFIED — forum reports, not official docs]`. Our key
works through `google-genai`, which is consistent with those reports.

### Open items for the decision in P1.3

- **Candidate shape:** `gemini-3.5-flash-lite` as primary with `gemini-3.1-flash-lite` as fallback.
  They hold separate quotas, so the fallback survives the primary's 500 RPD and the kind of 503 we
  already saw. Needs a quality spot-check against `gemini-3.8-flash` before we commit.
- **Design implication:** one generation call per episode, returning overview, chapters and quiz in
  a single structured response; a revision is then one further call for the targeted section only.
  This follows from the rate limits above — requests per day, not tokens, is what we have to spend
  carefully.
- **Gemini free-tier terms need a visible UI notice:** inputs are used to improve Google products,
  human reviewers may read them, and the terms say not to submit sensitive, confidential or personal
  information. Users must see this before they paste a transcript.
- Confirm the Groq free-plan figures from console account settings if Groq stays a candidate; the
  documentation's Free/Developer labelling does not settle it.

## 2. Hosting and transcription

Checked 2026-10-12. We need a host that runs a Streamlit app on a free tier with no billing
account, keeps one API key server-side, and stays reachable for reviewers for at least two weeks.

| | **Streamlit Community Cloud** | **Hugging Face Spaces** |
|---|---|---|
| Runs Streamlit? | Yes, it is the first-party host | **Not as a native SDK.** The [config reference](https://huggingface.co/docs/hub/spaces-config-reference) says `sdk` "Can be either `gradio`, `docker`, or `static`" and `sdk_version` is "the version of Gradio to use". A Streamlit app would have to be a Docker Space |
| Free tier | [690MB–2.7GB memory, 0.078–2 CPU cores, up to 50GB storage](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app), listed as of February 2024 and "may change at any time without notice" | CPU Basic is [2 vCPU, 16GB RAM, 50GB non-persistent disk at no hourly cost](https://huggingface.co/docs/hub/spaces-overview) — but "Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts". Only static Spaces are free for everyone |
| Sleep / wake | Sleeps after [12 hours with no traffic](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app); anyone with view access wakes it with a "Yes, get this app back up!" button | On free hardware a Space will ["go to sleep" and stop executing after a period of time if unused](https://huggingface.co/docs/hub/spaces-overview); the period is not given `[UNVERIFIED]` |
| Secrets | Saved in the app's settings and read with `st.secrets`; `.streamlit/secrets.toml` is local-only and ["should never be committed to your repository"](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management) | Settings-page secrets, private and unreadable after being set, exposed to the app as environment variables; a secrets scanner warns on hard-coded values ([overview](https://huggingface.co/docs/hub/spaces-overview)) |
| Repo visibility | App visibility follows the repo, and ["You are only allowed one private app at a time"](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app). Our repo is public, so this does not bind us | Public, protected or private; protected needs a paid plan |
| Upload limit | Streamlit's own [`maxUploadSize` default is 200](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) MB | Same Streamlit setting would apply inside a Docker Space; no Spaces-specific request limit documented `[UNVERIFIED]` |
| Logs | "Manage app" → Cloud logs, downloadable; rebooting also clears the app's memory | Not covered on the overview page `[UNVERIFIED]` |

**Impact.** Hugging Face Spaces is not a free option for this app. Streamlit is no longer a Spaces
SDK, so we would have to build a Docker Space, and creating a Docker Space requires a PRO plan on a
personal account. That conflicts with free-tier-only, so Streamlit Community Cloud is the only one
of the two we can actually deploy on. Its 12-hour sleep is the main consequence to plan for: a
reviewer arriving after a quiet night sees a wake-up screen first, so the README and the submission
email should say so.

Note a documentation inconsistency: Hugging Face still publishes a
[Streamlit Spaces page](https://huggingface.co/docs/hub/spaces-sdks-streamlit) describing
`sdk: streamlit`, but it cites Streamlit 1.25.0 and links to retired Streamlit docs paths, and the
current config reference does not list `streamlit` as a valid SDK. We treat the config reference as
authoritative.

### Transcription (stretch goal only)

Audio upload is a stretch goal, so this is a note for later, not a recommendation to build it now.

| | **Groq Whisper** | **Gemini audio input** |
|---|---|---|
| File limits | [25 MB free tier, 100 MB dev tier](https://console.groq.com/docs/speech-to-text); larger files via a `url` parameter instead of upload. Minimum billed length 10 seconds | [20 MB total inline request size](https://ai.google.dev/gemini-api/docs/audio) including prompt and files, or the Files API for larger; up to 9.5 hours per prompt |
| Formats | flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm | WAV, MP3, AIFF, AAC, OGG, FLAC, MPEG, M4A, L16, Opus, ALAW, MULAW, WebM |
| Timestamps | API-derived: `response_format=verbose_json` with `timestamp_granularities[]` of `word` and/or `segment` (segment is the default) | **No documented structured segment field** — timestamps come from the model's text output, or from a response schema you define yourself |
| Cost | `whisper-large-v3` $0.111/hour, `whisper-large-v3-turbo` $0.04/hour | Audio counts as input tokens at [32 tokens per second](https://ai.google.dev/gemini-api/docs/audio) (1,920/minute), so it draws on the same free-tier token quota |

**Impact.** Only Groq Whisper returns timestamps that come from the transcription itself. Gemini
would have the model write the times, which our own rule forbids — invented timestamps are exactly
the failure the brief asks us to avoid. So if we ever add audio, transcription and generation would
come from different providers: Groq for segments, Gemini for text. The 25 MB free-tier cap is the
other constraint: at a typical 128 kbps podcast bitrate that is roughly 26 minutes of audio by our
own arithmetic, so a 40-minute episode would exceed it and need the `url` parameter. This is a
second reason to keep audio out of the 48-hour scope.

Groq's speech-to-text page also contradicts itself: its Python example comment says to set
`response_format` to `json` for timestamps while the parameter table requires `verbose_json`. The
table is the one to follow.

## Sources

- [Gemini models](https://ai.google.dev/gemini-api/docs/models) — current model IDs; the 2.5 family is restricted to prior users, which explains our 404.
- [What's new in Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) — 1M context, 64k output, thinking levels.
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) — tier definitions, and that free-tier numbers live in AI Studio rather than the docs.
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) — free tier covers 3.8 Flash; paid rates and the 2026-12-31 introductory cutoff.
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) — Pydantic to JSON Schema, and that only a subset of JSON Schema works.
- [Interactions API](https://ai.google.dev/gemini-api/docs/interactions) — the recommended entry point for new projects; `generateContent` is legacy but supported.
- [Gemini API additional terms](https://ai.google.dev/gemini-api/terms) — unpaid-tier content is used for product improvement and may be read by humans.
- [Using Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key) — auth keys since 2026-05-28; never ship keys in client code, proxy through a backend.
- [Groq supported models](https://console.groq.com/docs/models) — production model IDs and context windows.
- [Groq gpt-oss-120b](https://console.groq.com/docs/model/openai/gpt-oss-120b) — price, context, and the only throughput figure either provider publishes.
- [Groq rate limits](https://console.groq.com/docs/rate-limits) — per-model limits, and the inconsistency we flagged.
- [Groq structured outputs](https://console.groq.com/docs/structured-outputs) — strict mode model list and the no-optional-fields constraint that will shape our Pydantic schemas.
- [Your data in GroqCloud](https://console.groq.com/docs/your-data) — no retention by default, 30-day abuse logs, ZDR for all customers.
- [Groq privacy policy](https://groq.com/privacy-policy) — no training language, but a stated legitimate interest in developing and improving the Services; narrower than the data page, so worth re-reading before we publish a privacy claim.
- [Groq quickstart](https://console.groq.com/docs/quickstart) — SDK package name and key environment variable.
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing) — paid baseline, and confirmation there is no free text-token tier.
- [Streamlit Community Cloud: manage your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app) — per-app resource ceilings, the 12-hour sleep, and where logs live.
- [Streamlit secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management) — `st.secrets` plus the instruction never to commit `secrets.toml`, which is what our `.gitignore` and example file have to enforce.
- [Streamlit share your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app) — app visibility follows the repo, one private app at a time.
- [Streamlit config.toml reference](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) — `maxUploadSize` defaults to 200 MB, so our own input cap has to be set deliberately rather than inherited.
- [Spaces overview](https://huggingface.co/docs/hub/spaces-overview) — CPU Basic specs, settings-page secrets, free-hardware sleep, and that Gradio and Docker Spaces need a paid plan.
- [Spaces config reference](https://huggingface.co/docs/hub/spaces-config-reference) — `sdk` accepts only `gradio`, `docker` or `static`; this is what rules Spaces out for us.
- [Groq speech-to-text](https://console.groq.com/docs/speech-to-text) — 25 MB free-tier cap, formats, and `verbose_json` segment timestamps.
- [Gemini audio](https://ai.google.dev/gemini-api/docs/audio) — 20 MB inline limit, 32 tokens/second, and that segment timestamps are not a documented API field.
