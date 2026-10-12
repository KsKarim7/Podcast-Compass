"""Decode input, work out what format it is, and pull out subtitle cues.

Format is decided by content rather than by file extension, because pasted text has no
extension and we want one rule for both paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from . import config, messages

Format = Literal["vtt", "srt", "text"]


class InputError(Exception):
    """Carries a message written for the person who submitted the transcript."""


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ParsedTranscript:
    detected: Format
    cues: tuple[Cue, ...]
    text: str
    malformed_cues: int
    fell_back_to_text: bool

    @property
    def has_timestamps(self) -> bool:
        return bool(self.cues)


# One timing line, e.g. "00:00:01.000 --> 00:00:04.500" or "01:23,000 --> 01:25,000".
# The hour field is optional because plenty of real files leave it out.
_TIME = r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
TIMING_LINE = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")
SRT_TIMING_LINE = re.compile(rf"^\s*{_TIME.replace('[.,]', ',')}\s*-->")

# Inline voice and styling tags: <v Speaker>, </v>, <c.yellow>, <00:00:01.000>
INLINE_TAG = re.compile(r"</?[a-zA-Z][^>]*>|<\d{1,3}:\d{2}:\d{2}[.,]\d{1,3}>")


def decode_bytes(data: bytes) -> str:
    """UTF-16 by its byte-order mark, then UTF-8, then one cp1252 attempt.

    The order is the point. cp1252 has only five undefined bytes, so it decodes UTF-16
    into mojibake rather than failing, and subtitle files exported on Windows are often
    UTF-16. Silently accepting garbage is worse than rejecting the file.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass

    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise InputError(messages.BAD_ENCODING)


ALLOWED_EXTENSIONS = ("txt", "vtt", "srt")


def read_upload(name: str, data: bytes) -> str:
    """Check the extension, then decode.

    Streamlit's uploader has its own type filter, but its documentation calls that
    best-effort rather than a guarantee, so the name is checked again here. This lives
    in the package rather than in the app module so it can be tested without importing
    the Streamlit script.
    """
    extension = name.rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise InputError(
            messages.UNSUPPORTED_FILE_TYPE.format(
                extension=f".{extension}" if extension else "unnamed"
            )
        )
    return decode_bytes(data)


def normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def detect_format(text: str) -> Format:
    lines = text.lstrip("﻿").splitlines()
    for line in lines:
        if line.strip():
            if line.strip().upper().startswith("WEBVTT"):
                return "vtt"
            break
    for line in lines[:20]:
        if SRT_TIMING_LINE.match(line):
            return "srt"
    return "text"


def validate_length(text: str) -> None:
    stripped = text.strip()
    if not stripped:
        raise InputError(messages.EMPTY_INPUT)
    if len(stripped) < config.MIN_CHARS:
        raise InputError(messages.TOO_SHORT.format(count=len(stripped)))
    if len(stripped) > config.MAX_CHARS:
        raise InputError(messages.TOO_LONG.format(count=len(stripped)))


def _parse_time(match: re.Match[str], offset: int) -> float:
    hours, minutes, seconds, fraction = match.groups()[offset : offset + 4]
    return (
        int(hours or 0) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(fraction.ljust(3, "0")) / 1000
    )


def _clean_cue_text(lines: list[str]) -> str:
    joined = " ".join(line.strip() for line in lines)
    return INLINE_TAG.sub("", joined).strip()


def parse_cues(text: str) -> tuple[list[Cue], int]:
    """Return the cues we could read and a count of the blocks we could not.

    A block is a run of lines separated by a blank line. We look for a timing line
    anywhere in the block, so cue identifiers and NOTE lines do not matter.
    """
    cues: list[Cue] = []
    malformed = 0

    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if lines[0].strip().upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue

        timing_index = next(
            (i for i, ln in enumerate(lines) if TIMING_LINE.match(ln)), None
        )
        if timing_index is None:
            malformed += 1
            continue

        match = TIMING_LINE.match(lines[timing_index])
        assert match is not None
        start = _parse_time(match, 0)
        end = _parse_time(match, 4)
        body = _clean_cue_text(lines[timing_index + 1 :])
        if not body:
            continue
        cues.append(Cue(start=start, end=end, text=body))

    cues.sort(key=lambda cue: cue.start)
    return cues, malformed


def strip_markup(text: str) -> str:
    """Whatever is left when cue structure is removed: used when we fall back to text."""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        if TIMING_LINE.match(stripped) or stripped.isdigit():
            continue
        kept.append(INLINE_TAG.sub("", stripped))
    return "\n".join(kept)


def parse_transcript(raw_text: str) -> ParsedTranscript:
    text = normalise_newlines(raw_text).lstrip("﻿")
    validate_length(text)
    detected = detect_format(text)

    if detected == "text":
        return ParsedTranscript(
            detected="text",
            cues=(),
            text=text.strip(),
            malformed_cues=0,
            fell_back_to_text=False,
        )

    cues, malformed = parse_cues(text)

    if not cues:
        # No cue survived. If words remain once the markup is gone we are better off
        # treating the file as plain text than refusing something readable.
        remainder = strip_markup(text)
        if len(remainder.strip()) >= config.MIN_CHARS:
            return ParsedTranscript(
                detected="text",
                cues=(),
                text=remainder.strip(),
                malformed_cues=malformed,
                fell_back_to_text=True,
            )
        raise InputError(messages.NO_CUES_AT_ALL)

    total_blocks = len(cues) + malformed
    if malformed / total_blocks > config.MAX_MALFORMED_CUE_RATIO:
        raise InputError(messages.DAMAGED_CUES.format(good=len(cues), total=total_blocks))

    return ParsedTranscript(
        detected=detected,
        cues=tuple(cues),
        text="\n".join(cue.text for cue in cues),
        malformed_cues=malformed,
        fell_back_to_text=False,
    )
