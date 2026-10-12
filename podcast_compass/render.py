"""Display strings, kept separate from Streamlit so the wording is testable.

Nothing here imports streamlit. app.py decides which widget shows each string.
"""

from __future__ import annotations

from .grounding import VerifiedChapter
from . import messages
from .parsing import ParsedTranscript
from .segments import format_timestamp
from .text import plural

NO_TIMESTAMP_NOTICE = (
    "This transcript has no timestamps, so chapters show titles only. Upload a .vtt or "
    ".srt file to get times — we read them from the subtitle cues rather than asking the "
    "model, which is why we cannot invent them here."
)

DATA_USE_NOTICE = (
    "This demo uses Gemini's free tier. Google's terms say free-tier inputs are used to "
    "improve Google's products and may be read by human reviewers. Do not paste "
    "confidential or personal content. Use only transcripts you have permission to process."
)

UNVERIFIED_CHAPTER_NOTE = "unverified, we could not confirm where this starts"

FORMAT_NAMES = {"vtt": "WebVTT", "srt": "SubRip", "text": "plain text"}


def detection_line(parsed: ParsedTranscript, segment_count: int) -> str:
    """What was detected and what it means for timestamps."""
    name = FORMAT_NAMES[parsed.detected]
    if parsed.cues:
        line = f"Detected: {name}, {len(parsed.cues)} cues, timestamps available"
    elif parsed.fell_back_to_text:
        line = f"Detected: {messages.NO_CUES_FELL_BACK}"
    else:
        line = f"Detected: {name}, no timestamps"

    line += f" · {plural(segment_count, 'segment')}"
    if parsed.malformed_cues:
        line += f" · {plural(parsed.malformed_cues, 'unreadable cue')} skipped"
    return line


def chapter_heading(item: VerifiedChapter) -> str:
    """A time only when we verified the chapter and the source had cues."""
    if item.verified and item.start_seconds is not None:
        return f"[{format_timestamp(item.start_seconds)}] {item.chapter.title}"
    if not item.verified:
        return f"{item.chapter.title} — {UNVERIFIED_CHAPTER_NOTE}"
    return item.chapter.title


def evidence_caption(segment_id: str, quote: str) -> str:
    return f'{segment_id}: "{quote}"'


def answer_feedback(chosen_index: int, correct_index: int) -> str:
    return "Correct" if chosen_index == correct_index else "Not quite"
