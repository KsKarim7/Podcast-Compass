# Research

Checked **2026-10-12**. Every figure links to its source; what we could not confirm on a
provider-owned page or by calling the API ourselves is marked `[UNVERIFIED]`. Full tables, our API
test log and the documentation contradictions we hit are in
[ENGINEERING.md section A](ENGINEERING.md#a-technology-comparison-detail).

## 1. Who this is for

Edison Research's [UK Podcast Consumer 2025](https://ssrs.com/insights/the-uk-podcast-consumer-2025/)
(7 August 2025) puts reach at 71% of UK adults 16+ having ever consumed a podcast, 51% in the last
month.

- **Students and self-learners** on educational or interview episodes, who want to revise and test
  themselves rather than listen again.
- **Researchers and journalists** who remember something was said and need the moment, quoted
  accurately.
- **Busy listeners** deciding whether a 90-minute episode is worth their time.

The one problem we solve best: **finding and trusting a specific claim in a long episode.** Podcast
apps already have search and chapter lists; they do not tell you where a claim came from. Every
takeaway, chapter and quiz answer cites the transcript segment it rests on, with a quote verified
against that segment, so a user can check us rather than trust us.

## 2. Technology choices

Gemini's free tier against Groq's for generation, OpenAI as a paid baseline; Streamlit Community
Cloud against Hugging Face Spaces for hosting.

| | Gemini free tier | Groq free tier | OpenAI |
|---|---|---|---|
| Structured JSON | [Pydantic to JSON Schema](https://ai.google.dev/gemini-api/docs/structured-output), subset of the spec | [`strict: true` decoding](https://console.groq.com/docs/structured-outputs), no optional fields | Paid reference |
| Context | [1M tokens](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) | [131,072](https://console.groq.com/docs/model/openai/gpt-oss-120b) | – |
| Binding free limit | 500 requests/day (Flash Lite); 20/day (`gemini-3.8-flash`) | 8K tokens/minute | [none free](https://developers.openai.com/api/docs/pricing) |
| Data use | Inputs ["used to improve our products"](https://ai.google.dev/gemini-api/terms); human review | [No retention by default](https://console.groq.com/docs/your-data); ZDR | – |
| Paid /1M | [$0.75 / $3.75](https://ai.google.dev/gemini-api/docs/pricing) | [$0.15 / $0.60](https://console.groq.com/docs/model/openai/gpt-oss-120b) | [$0.05 / $0.40](https://developers.openai.com/api/docs/pricing) |

Two findings decided it. A 30–40 minute episode is roughly 8K tokens (our estimate, to be replaced
by a real count from the sample transcript), so Groq's 8K tokens/minute cannot take one in a single
call. And `gemini-3.8-flash`, which has the context headroom, allows only 20 requests a day, shared
between our testing, the demo and every reviewer. The Flash Lite models have both.

Hugging Face Spaces is not a free option: the
[config reference](https://huggingface.co/docs/hub/spaces-config-reference) lists only `gradio`,
`docker` and `static` as SDK values, and [Docker Spaces require a paid plan](https://huggingface.co/docs/hub/spaces-overview).
Out on cost, so we left its undocumented details alone. Streamlit Community Cloud
[sleeps after 12 hours without traffic](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app);
any visitor can wake it.

## 3. Reliability

We make every claim checkable in code rather than asking the model to be careful.

- **Timestamps never come from the model** — they are parsed from VTT or SRT cues. Plain text input
  gets no timestamps and a visible notice saying why.
- **Segment IDs plus quotes.** The transcript is split into numbered segments first. Every takeaway,
  chapter start and quiz answer cites segment IDs and a short quote; the server checks the IDs
  exist, the quote appears in the cited segment, and chapter starts run in order. Failures are
  dropped or shown as unverified.
- **Schema validation.** Output is parsed into Pydantic models; malformed output gets one repair
  retry, then a clear error rather than a partial result.
- **Refusing unanswerable items.** The prompt answers only from the transcript, and a quiz question
  that cannot be grounded in a segment is dropped rather than guessed.
- **Transient failures are real.** `gemini-3.1-flash-lite` returned a 503 on our first call and
  succeeded a minute later unchanged — hence retry with backoff, then the fallback model.

Known limits: quote verification catches fabricated evidence, not a shallow summary, and a model can
cite a real segment that does not actually support its claim.

## 4. Responsible handling

- **Content permissions.** The sample transcript is ours; the UI tells users to submit only content
  they have the right to process.
- **Provider terms.** Gemini's unpaid tier uses inputs "to provide, improve, and develop" Google's
  products, allows human review, and says not to submit sensitive, confidential or personal
  information ([terms](https://ai.google.dev/gemini-api/terms)). A UI notice says so before anyone
  pastes a transcript — the clearest cost of the free tier.
- **No storage.** Transcripts live in session state only: no database, no logging of user content,
  nothing on disk server-side.
- **Secrets.** The key comes from Streamlit secrets, never hard-coded or sent to the browser.
  `.streamlit/secrets.toml` is git-ignored and only a placeholder example is committed, as
  Streamlit [requires](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

Two entries of the [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/) bite
hardest. **LLM01 Prompt Injection:** transcripts and revision instructions are both untrusted, so
both are passed as data, the system prompt states that transcript text cannot change the task, and
every output must still pass schema and quote validation — injected text cannot invent a citation
that survives verification. **LLM10 Unbounded Consumption:** we cap input size and generations per
session, plus a global cap so one visitor cannot burn the day's 500 requests. **LLM09
Misinformation** is section 3's job. These IDs are the 2025 edition's; a 2026 edition was published
2026-08-03 whose numbering we could not read from the project site `[UNVERIFIED]`.

The brief's own reference, the [OWASP API Security Project](https://api-security.owasp.org/), names
the same risk as [API4:2023 Unrestricted Resource Consumption](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption)
and asks for rate limiting, "a maximum size of data on all incoming parameters and payloads", and
spending limits on third-party integrations. The first two are ours to build; the third needs none,
since with no billing enabled the free-tier quota is itself the ceiling.

## 5. Recommendation

- **Host: Streamlit Community Cloud** — the only free option that runs Streamlit, since Spaces needs
  a paid plan for a Docker Space. The 12-hour sleep and wake button go in the README and the
  submission email so reviewers are not surprised.
- **Model: `gemini-3.5-flash-lite` primary, `gemini-3.1-flash-lite` fallback** on 429 and 503. Their
  quotas are separate, so the fallback survives both the primary's daily cap and the overload we
  observed. `gemini-3.8-flash` rejected on 20 requests/day; Groq on 8K tokens/minute.
- **One structured generation call per episode** — overview, chapters and quiz together. Revision
  regenerates only the targeted section, keeping edits cheap in the resource that is scarce.
- **Input: transcript only** — paste, `.txt`, `.vtt`, `.srt`, with our own cap well below
  Streamlit's 200 MB default.
- **A visible notice** that free-tier Gemini may use inputs to improve Google products, and that
  confidential or personal content should not be submitted.
- **Calls go through the Interactions API** (`client.interactions.create`), which Google
  [recommends for new projects](https://ai.google.dev/gemini-api/docs/interactions).

**Audio is out of scope**, listed as a next step: it needs a second provider, since Groq Whisper is
the only option whose timestamps come from the audio rather than a model, and its free tier caps
uploads at 25 MB — roughly 26 minutes at 128 kbps.
[OpenAI transcription](https://developers.openai.com/api/docs/guides/speech-to-text) was considered
and excluded: capable, but [no free tier](https://developers.openai.com/api/docs/pricing).

## Sources

Every source, with a note on what each taught us, is in
[ENGINEERING.md section A.7](ENGINEERING.md#a7-sources). The six that decided a locked choice:

- [Spaces config reference](https://huggingface.co/docs/hub/spaces-config-reference) and [overview](https://huggingface.co/docs/hub/spaces-overview) — `sdk` takes only `gradio`, `docker`, `static`, and Docker Spaces need a paid plan. This ruled Spaces out and chose our host.
- [Groq rate limits](https://console.groq.com/docs/rate-limits) — the 8K tokens/minute that ruled Groq out.
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) — no Free row published, so the numbers behind our model choice had to come from the AI Studio console.
- [Gemini terms](https://ai.google.dev/gemini-api/terms) — unpaid-tier inputs improve Google products and may be read by humans; the reason for our UI notice.
- [Interactions API](https://ai.google.dev/gemini-api/docs/interactions) — recommended for new projects, so this is the call we write against.
- [Edison Research, UK Podcast Consumer 2025](https://ssrs.com/insights/the-uk-podcast-consumer-2025/) — 71% ever and 51% monthly UK reach; the audience is measured, not assumed.
