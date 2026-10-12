"""Display strings, kept separate from Streamlit so the wording is testable.

Nothing here imports streamlit. app.py decides which widget shows each string.
"""

from __future__ import annotations

from .grounding import GroundedResult, VerifiedChapter
from .parsing import ParsedTranscript
from .segments import format_timestamp

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
        line = (
            "Detected: subtitle markup we could not read, so this was treated as "
            "plain text — no timestamps"
        )
    else:
        line = f"Detected: {name}, no timestamps"

    line += f" · {segment_count} segments"
    if parsed.malformed_cues:
        line += f" · {parsed.malformed_cues} unreadable cue(s) skipped"
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


def as_markdown(result: GroundedResult, *, title: str = "Episode companion") -> str:
    """The copy/download payload. One function so both buttons agree."""
    lines = [f"# {title}", "", "## Summary", "", result.summary, "", "## Themes", ""]
    lines += [f"- {theme}" for theme in result.themes]
    lines += ["", "## Key takeaways", ""]
    for takeaway in result.takeaways:
        lines.append(f"- {takeaway.text}")
        lines.append(
            f"  - Evidence {evidence_caption(takeaway.evidence.segment_id, takeaway.evidence.quote)}"
        )
    lines += ["", "## Chapters", ""]
    if not result.has_timestamps:
        lines += [f"_{NO_TIMESTAMP_NOTICE}_", ""]
    for item in result.chapters:
        lines.append(f"### {chapter_heading(item)}")
        lines.append("")
        lines.append(item.chapter.explanation)
        lines.append("")
    lines += ["## Quiz", ""]
    for number, question in enumerate(result.quiz, 1):
        lines.append(f"**{number}. {question.question}**")
        lines.append("")
        for index, option in enumerate(question.options):
            marker = "x" if index == question.correct_index else " "
            lines.append(f"- [{marker}] {option}")
        lines.append("")
        lines.append(f"Answer: {question.options[question.correct_index]}")
        lines.append("")
        lines.append(question.explanation)
        lines.append("")
        lines.append(
            f"Evidence {evidence_caption(question.evidence.segment_id, question.evidence.quote)}"
        )
        lines.append("")
    return "\n".join(lines).strip() + "\n"
