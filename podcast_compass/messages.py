"""Every message a user can be shown when something goes wrong.

One module, so every failure has exactly one wording and tests can assert the exact text
rather than a substring. tests/test_errors.py has a test per message.

Rules these all follow:

* say what happened and what to do next;
* never include a stack trace, a provider URL, or any part of the key;
* where generation is unavailable, point at the example episode, which needs no API call
  and keeps the app useful rather than broken.
"""

from __future__ import annotations

from . import config

EXAMPLE_STILL_WORKS = "The example episode still works."

# --- input ------------------------------------------------------------------------
UNSUPPORTED_FILE_TYPE = (
    "We can read .txt, .vtt and .srt files. That one is {extension}."
)
EMPTY_INPUT = "That file has no text in it."
NOTHING_SUBMITTED = "Paste a transcript or upload a file first."
TOO_SHORT = (
    "That transcript is {count:,} words. We need at least "
    f"{config.MIN_WORDS} words to build chapters and a quiz."
)
TOO_LONG = (
    "That transcript is {count:,} characters. The limit is "
    f"{config.MAX_CHARS:,} — about 3 hours of speech. Try a shorter section."
)
BAD_ENCODING = (
    "We could not read that file's text encoding. Save it as UTF-8 and try again."
)
NO_CUES_FELL_BACK = (
    "We could not read any subtitle cues, so we treated this as plain text — "
    "chapters will have no times."
)
NO_CUES_AT_ALL = "We could not read any subtitle cues from that file."
DAMAGED_CUES = (
    "We could only read {good} of {total} cues in that file. It looks damaged — "
    "try re-exporting the subtitles."
)

# --- configuration ----------------------------------------------------------------
MISSING_KEY = (
    "This app is not configured with an API key, so generation is unavailable. "
    f"{EXAMPLE_STILL_WORKS}"
)
REJECTED_KEY = f"The configured API key was rejected. {EXAMPLE_STILL_WORKS}"

# --- provider ---------------------------------------------------------------------
QUOTA_EXHAUSTED = (
    "We have hit today's free-tier limit for this demo. "
    f"{EXAMPLE_STILL_WORKS} The limit resets daily."
)
MODEL_BUSY = (
    "The model is busy right now. We tried a second model and it is also unavailable — "
    "please try again in a minute."
)
TIMED_OUT = (
    f"That took longer than {config.REQUEST_TIMEOUT_MS // 1000} seconds, so we stopped "
    "waiting. A shorter transcript will be faster."
)
MALFORMED_TWICE = (
    "The model returned something we could not read, twice. Please try again."
)
UNKNOWN = "Something went wrong on our side. Please try again."

# --- grounding --------------------------------------------------------------------
GROUNDING_REJECTED = (
    "We could not verify enough of that result against your transcript, so we are not "
    "showing it."
)
GROUNDING_REJECTED_BECAUSE = (
    "We could not verify enough of that result against your transcript, so we are not "
    "showing it: {reason}."
)
REVISION_REJECTED = (
    "We could not verify that revision against your transcript, so we have kept the "
    "previous version."
)
REVISION_REJECTED_BECAUSE = (
    "We could not verify that revision against your transcript, so we have kept the "
    "previous version: {reason}."
)

# --- our own caps -----------------------------------------------------------------
SESSION_CAP = (
    "You have run {limit} generations in this session, which is this demo's limit. "
    f"{EXAMPLE_STILL_WORKS}"
)
DAILY_CAP = (
    "This demo is limited to {limit} requests a day to stay inside the free tier. "
    f"{EXAMPLE_STILL_WORKS} The limit resets daily."
)
TOO_SOON = "That was quick — wait a moment before generating again."


def all_messages() -> dict[str, str]:
    """Every message constant, for the test that checks none of them leak internals."""
    return {
        name: value
        for name, value in globals().items()
        if name.isupper() and isinstance(value, str)
    }
