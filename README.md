# Podcast Compass

Turns a podcast transcript into an episode overview, navigable chapters and an
interactive quiz, with every takeaway, chapter and quiz answer tied back to the part of
the transcript it came from.

## Limits and quotas

| Limit | Value | Enforced by |
|---|---|---|
| Upload size | 2 MB | Streamlit, before our code runs |
| Transcript length | 150,000 characters (about 3 hours of speech) | Checked after decoding |
| Minimum length | 200 characters | Checked after decoding |
| Generations per session | 10 | In-app counter |
| Requests per day | 400 | In-app counter, shared by all sessions |
| Minimum gap between generations | 4 seconds | In-app counter |

The daily cap counts **requests**, not user actions, because one action can cost up to
three requests: the first call, a call to the fallback model if the first is unavailable,
and one repair retry if the output will not parse. Capping actions instead could spend
three times the intended budget.

### What these caps cannot do

The counters live in the running app's own memory. Streamlit Community Cloud sleeps an
app after 12 hours without traffic and restarts it on redeploy, and the count resets
whenever that happens. If the platform ever runs more than one process for this app,
each would count separately.

So this is a guard against accidental overuse, not a hard limit. The real backstop is
the provider refusing further requests, which the app reports as the daily limit being
reached. We say this rather than implying the cap is enforced, because a reviewer should
be able to tell the difference between a guarantee and a safety net.

## Data use

This demo runs on Gemini's free tier. Google's terms state that free-tier inputs are
used to improve Google's products and may be read by human reviewers, so the app shows a
notice before any transcript is accepted and asks users not to submit confidential or
personal content. Nothing is stored server-side: a transcript lives in session state for
the length of the session and is never written to disk or logged.
