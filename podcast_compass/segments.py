"""Numbered segments, which are the unit every citation refers to.

Cues are usually only a few words long. Merging them up to a target word count makes a
cited quote a real locator and keeps the number of ids manageable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .parsing import Cue, ParsedTranscript


@dataclass(frozen=True)
class Segment:
    id: str
    text: str
    start: float | None
    end: float | None


def segment_id(index: int) -> str:
    return f"S{index:03d}"


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _word_count(text: str) -> int:
    return len(text.split())


def segments_from_cues(cues: list[Cue] | tuple[Cue, ...]) -> list[Segment]:
    segments: list[Segment] = []
    buffer: list[Cue] = []
    words = 0

    def flush() -> None:
        nonlocal buffer, words
        if not buffer:
            return
        segments.append(
            Segment(
                id=segment_id(len(segments) + 1),
                text=" ".join(cue.text for cue in buffer),
                start=buffer[0].start,
                end=buffer[-1].end,
            )
        )
        buffer = []
        words = 0

    for cue in cues:
        buffer.append(cue)
        words += _word_count(cue.text)
        if words >= config.WORDS_PER_SEGMENT:
            flush()
    flush()
    return segments


def segments_from_text(text: str) -> list[Segment]:
    """Pack paragraphs to the same target size, splitting one only if it is too long.

    Unlike cues there is no boundary we have to respect, so an over-long paragraph can
    be split on a word boundary.
    """
    segments: list[Segment] = []
    buffer: list[str] = []
    words = 0

    def flush() -> None:
        nonlocal buffer, words
        if not buffer:
            return
        segments.append(
            Segment(
                id=segment_id(len(segments) + 1),
                text=" ".join(buffer).strip(),
                start=None,
                end=None,
            )
        )
        buffer = []
        words = 0

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue

        paragraph_words = paragraph.split()
        if words and words + len(paragraph_words) > config.WORDS_PER_SEGMENT:
            flush()

        while len(paragraph_words) > config.WORDS_PER_SEGMENT:
            take = config.WORDS_PER_SEGMENT - words
            buffer.append(" ".join(paragraph_words[:take]))
            words += take
            paragraph_words = paragraph_words[take:]
            flush()

        if paragraph_words:
            buffer.append(" ".join(paragraph_words))
            words += len(paragraph_words)
            if words >= config.WORDS_PER_SEGMENT:
                flush()

    flush()
    return segments


def build_segments(parsed: ParsedTranscript) -> list[Segment]:
    if parsed.cues:
        return segments_from_cues(parsed.cues)
    return segments_from_text(parsed.text)


def segment_lookup(segments: list[Segment]) -> dict[str, Segment]:
    return {segment.id: segment for segment in segments}


def render_for_prompt(segments: list[Segment]) -> str:
    """The transcript as the model sees it: an id per line, and a time when we have one."""
    lines = []
    for segment in segments:
        marker = f" [{format_timestamp(segment.start)}]" if segment.start is not None else ""
        lines.append(f"{segment.id}{marker} {segment.text}")
    return "\n".join(lines)
