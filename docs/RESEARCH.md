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
