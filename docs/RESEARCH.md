# Research

All provider facts below were read from official documentation on **2026-10-12**. Free-tier limits
and model availability change often, so each figure links to the page it came from. Figures we
could not confirm on a provider-owned page are marked `[UNVERIFIED]`.

## 1. LLM provider comparison

We need one text model that reliably returns JSON matching a Pydantic schema, accepts a full
podcast transcript in one request, and runs on a free tier with no billing account.

| | **Google Gemini** (`gemini-3.8-flash`) | **Groq** (`openai/gpt-oss-120b`) | **OpenAI** (paid reference only) |
|---|---|---|---|
| JSON / structured output | JSON Schema via `response_format` on `interactions.create`; the Python SDK converts a Pydantic model with `model_json_schema()`. Only a [subset of JSON Schema](https://ai.google.dev/gemini-api/docs/structured-output) is supported and "very large or deeply nested schemas may be rejected" | `json_schema` with `strict: true` (constrained decoding) on `gpt-oss-20b`, `gpt-oss-120b`, `qwen/qwen3.8-27b`. Every property must be required, `additionalProperties` must be `false`, and [optional fields are unsupported](https://console.groq.com/docs/structured-outputs) — use `anyOf` with `null`. Streaming and tool use cannot be combined with structured outputs | Not researched — paid reference only |
| Context window | [1M tokens, 64k max output](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) | [131,072 tokens, 65,536 max output](https://console.groq.com/docs/model/openai/gpt-oss-120b) | Not researched |
| Free-tier rate limits | **Not published.** The [rate limits page](https://ai.google.dev/gemini-api/docs/rate-limits) shows no RPM/TPM/RPD for the Free tier and says limits "can be viewed in Google AI Studio" `[UNVERIFIED]` | Pages disagree: the [model page](https://console.groq.com/docs/model/openai/gpt-oss-120b) gives 1K RPM / 250K TPM for the Developer plan, while the [rate limits page](https://console.groq.com/docs/rate-limits) shows 30 RPM / 1K RPD / 8K TPM / 200K TPD for the same model and states those are Developer base limits. Which numbers apply to the Free plan is `[UNVERIFIED]` | No free tier for text tokens |
| Typical latency | Not published `[UNVERIFIED]` | [~500 tokens/sec](https://console.groq.com/docs/model/openai/gpt-oss-120b) | Not researched |
| Python SDK | `google-genai`, [2.3.0 or later](https://ai.google.dev/gemini-api/docs/interactions) for the Interactions API | [`pip install groq`](https://console.groq.com/docs/quickstart), key from `GROQ_API_KEY` | `openai` |
| Free-tier data use | Google "uses the content you submit … to provide, improve, and develop" its products, "human reviewers may read, annotate, and process your API input and output", and the terms say **"Do not submit sensitive, confidential, or personal information to the Unpaid Services"** ([terms](https://ai.google.dev/gemini-api/terms)). The pricing page's free plan card reads "Content used to improve our products" | "By default, Groq does not retain customer data for inference requests"; reliability/abuse logs kept "up to 30 days" with an opt-out, and Zero Data Retention is available to all customers ([data page](https://console.groq.com/docs/your-data)). That page makes no statement either way about training on customer data `[UNVERIFIED]`. The general [website privacy policy](https://groq.com/privacy-policy) does not mention model training, but does claim a legitimate interest in using information to "improve, and develop the Services" | Not applicable |
| Cost beyond free tier | [$0.75 / $3.75 per 1M in/out](https://ai.google.dev/gemini-api/docs/pricing) through 2026-12-31, then $1.50 / $7.50 from 2027-01-01 | [$0.15 / $0.60 per 1M in/out](https://console.groq.com/docs/model/openai/gpt-oss-120b), cached input $0.075 | [gpt-5-nano $0.05 / $0.40; gpt-5-mini $0.25 / $2.00](https://developers.openai.com/api/docs/pricing) |
| Known issues | The Gemini 2.5 family is [limited to projects that already used it](https://ai.google.dev/gemini-api/docs/models); new projects are pointed at 3.5 Flash-Lite or 3.8 Flash. `minimal` thinking level errors on 3.8 Flash. Google now recommends the Interactions API for all new projects (see below) | Structured-output strict mode covers only a few models, and the rate-limit documentation is internally inconsistent (above) | No free tier |

### Interactions API

Google's [Interactions API](https://ai.google.dev/gemini-api/docs/interactions) is "recommended for
all new projects" and is where future models and features launch; the older `generateContent`
"remains fully supported". The structured-output docs and the REST example on the
[API key page](https://ai.google.dev/gemini-api/docs/api-key) both now use `interactions`, so if we
pick Gemini we should write against `client.interactions.create()` rather than `generate_content`.

### Our key tests (2026-10-12)

Both provider keys authenticate. On Gemini, `models.list` succeeded and `gemini-2.5-flash` returned
404 "no longer available to new users, use gemini-3.8-flash", which matches the model page above —
so we must only use models available to new accounts. The Groq key also returned `models.list`
successfully. The specific Gemini model we completed a generation call against is not yet recorded
`[UNVERIFIED]`.

Since 2026-05-28, "all new API keys created in Google AI Studio are automatically created as auth
keys" ([API key page](https://ai.google.dev/gemini-api/docs/api-key)); these are the keys that print
with an `AQ.` prefix. That page documents the key *type* but not the string format. Developer-forum
reports attribute `401 UNAUTHENTICATED / ACCESS_TOKEN_TYPE_UNSUPPORTED` failures to older clients
that expect the previous `AIza` format `[UNVERIFIED — forum reports, not official docs]`. Our key
works through `google-genai`, which is consistent with those reports.

### Open items for the decision in P1.3

- Neither provider publishes free-tier rate limits on a public page. Read the Gemini numbers from
  AI Studio and the Groq numbers from console account settings, both while signed in, and record
  them here before we commit to a provider.
- Gemini's free tier is explicitly told not to receive confidential content. That is acceptable for
  a demo on content we have permission to process, but it has to be stated in the UI and README.

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
