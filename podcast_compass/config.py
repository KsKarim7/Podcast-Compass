"""Limits that both the UI and the parser enforce."""

MAX_UPLOAD_MB = 2
MAX_CHARS = 150_000

# A segment has to be big enough that a quote inside it is a real locator, and small
# enough that a chapter start is precise. 120 words is roughly 45-55 seconds of speech.
WORDS_PER_SEGMENT = 120

# The user-facing minimum is counted in words, not characters, because what the app can
# produce depends on how many segments the transcript makes. Chapters must start at
# strictly increasing segments, so a single-segment transcript cannot have two chapters
# at all. 250 words guarantees three segments, which is enough to build something.
MIN_WORDS = 250

# An internal floor only, used when subtitle markup is stripped and we decide whether
# enough prose survived to treat the file as plain text.
MIN_CHARS = 200

# Above this share of unreadable cues we stop trusting the file's structure.
MAX_MALFORMED_CUE_RATIO = 0.2

# Models are named here, never at a call site, so a retirement is a config change.
# gemini-2.5-flash was withdrawn from new accounts while we were researching this.
PRIMARY_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.1-flash-lite"

REQUEST_TIMEOUT_MS = 45_000

# The SDK's own defaults are 5 attempts with delays growing to 60s, which would leave a
# user waiting a minute before the fallback model is tried.
RETRY_ATTEMPTS = 2
RETRY_INITIAL_DELAY_S = 0.5
RETRY_MAX_DELAY_S = 2.0
RETRY_STATUS_CODES = [408, 429, 500, 503, 504]

MAX_REVISION_CHARS = 300
MAX_QUESTION_CHARS = 300

# "Ask the podcast" embeds every segment once, then each question. The model is named here
# for the same reason as the generation models above.
EMBEDDING_MODEL = "gemini-embedding-001"
# The model returns 3072 numbers by default and can return fewer; 768 is plenty to tell a
# few hundred segments apart and uses a quarter of the memory. Shortened vectors are no
# longer unit length, so rag.py normalises every vector before it is indexed or searched.
EMBEDDING_DIMENSIONS = 768
# The API reference gives no per-call maximum; 100 texts keeps each request modest, and a
# transcript at the character limit (about 250 segments) takes three requests.
EMBED_BATCH_SIZE = 100
RETRIEVAL_TOP_K = 5

# Past this point a repair retry would push the worst case beyond what anyone will wait for.
REPAIR_BUDGET_S = 60.0

# Streamlit Community Cloud sleeps an app after this long without traffic.
SLEEP_HOURS = 12

LIMITS_TEXT = (
    "Paste a transcript, or upload .txt, .vtt or .srt — at least "
    f"{MIN_WORDS} words, and up to {MAX_UPLOAD_MB} MB or {MAX_CHARS:,} characters "
    "(about 3 hours of speech). .vtt and .srt give you timestamps; plain text does not."
)
