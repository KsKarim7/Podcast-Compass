"""Limits that both the UI and the parser enforce."""

MAX_UPLOAD_MB = 2
MIN_CHARS = 200
MAX_CHARS = 150_000

# A segment has to be big enough that a quote inside it is a real locator, and small
# enough that a chapter start is precise. 120 words is roughly 45-55 seconds of speech.
WORDS_PER_SEGMENT = 120

# Above this share of unreadable cues we stop trusting the file's structure.
MAX_MALFORMED_CUE_RATIO = 0.2

LIMITS_TEXT = (
    "Paste a transcript, or upload .txt, .vtt or .srt — up to "
    f"{MAX_UPLOAD_MB} MB and {MAX_CHARS:,} characters (about 3 hours of speech). "
    ".vtt and .srt give you timestamps; plain text does not."
)
