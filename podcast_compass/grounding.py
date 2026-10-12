"""Check the model's claims against the transcript before anyone reads them.

Every function here is pure: it takes a parsed result and the segment lookup, and returns
new objects. That is what makes this testable without a key, and it is the part of the app
that stands between a model's invention and a user believing it.

Timestamps are attached here, from the parsed cues, and only to chapters that passed. The
model never supplies a time.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .models import Chapter, EpisodeResult, Evidence, QuizQuestion, Takeaway
from .segments import Segment
from .text import plural

# Characters a model routinely substitutes when it "quotes" text.
_PUNCTUATION = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    " ": " ",
    "…": "...",
}
_WHITESPACE = re.compile(r"\s+")

MIN_QUOTE_WORDS = 3


def normalise(text: str) -> str:
    """Forgive punctuation and spacing, nothing else.

    Deliberately not a fuzzy match. Edit-distance matching would start accepting
    paraphrase, which is exactly the failure this check exists to catch.
    """
    folded = unicodedata.normalize("NFKC", text)
    for source, target in _PUNCTUATION.items():
        folded = folded.replace(source, target)
    return _WHITESPACE.sub(" ", folded).strip().casefold()


def quote_is_grounded(evidence: Evidence, segments: dict[str, Segment]) -> bool:
    segment = segments.get(evidence.segment_id)
    if segment is None:
        return False
    quote = normalise(evidence.quote)
    if len(quote.split()) < MIN_QUOTE_WORDS:
        # A one- or two-word "quote" matches almost anything and proves nothing.
        return False
    return quote in normalise(segment.text)


@dataclass
class VerifiedChapter:
    chapter: Chapter
    start_seconds: float | None
    verified: bool
    reason: str = ""


@dataclass
class ValidationReport:
    takeaways_kept: int = 0
    takeaways_dropped: int = 0
    quiz_kept: int = 0
    quiz_dropped: int = 0
    chapters_verified: int = 0
    chapters_flagged: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def dropped_total(self) -> int:
        return self.takeaways_dropped + self.quiz_dropped

    def summary(self) -> str:
        parts = [
            f"Kept {self.takeaways_kept} of "
            f"{self.takeaways_kept + self.takeaways_dropped} takeaways",
            f"{self.quiz_kept} of {self.quiz_kept + self.quiz_dropped} questions",
        ]
        if self.chapters_flagged:
            parts.append(f"{plural(self.chapters_flagged, 'chapter')} could not be confirmed")
        text = ", ".join(parts) + "."
        if self.dropped_total:
            # Deliberately not naming a single cause: items are dropped for a missing
            # quote, an unknown segment id, or an out-of-range answer index.
            text += (
                f" {plural(self.dropped_total, 'item')} dropped because we could not"
                " verify them against your transcript."
            )
        return text


@dataclass
class GroundedResult:
    summary: str
    themes: list[str]
    takeaways: list[Takeaway]
    chapters: list[VerifiedChapter]
    quiz: list[QuizQuestion]
    report: ValidationReport
    has_timestamps: bool


class GroundingRejected(Exception):
    """Too little survived to be worth showing. The caller retries or reports."""


def _filter_takeaways(
    takeaways: list[Takeaway], segments: dict[str, Segment], report: ValidationReport
) -> list[Takeaway]:
    kept = []
    for takeaway in takeaways:
        if quote_is_grounded(takeaway.evidence, segments):
            kept.append(takeaway)
        else:
            report.reasons.append(
                f"takeaway dropped: quote not found in {takeaway.evidence.segment_id}"
            )
    report.takeaways_kept = len(kept)
    report.takeaways_dropped = len(takeaways) - len(kept)
    return kept


def _filter_quiz(
    quiz: list[QuizQuestion], segments: dict[str, Segment], report: ValidationReport
) -> list[QuizQuestion]:
    kept = []
    for question in quiz:
        if not 0 <= question.correct_index < len(question.options):
            # The schema can only say "an integer"; the range is ours to check.
            report.reasons.append(
                f"question dropped: correct_index {question.correct_index} outside "
                f"0..{len(question.options) - 1}"
            )
            continue
        if not quote_is_grounded(question.evidence, segments):
            report.reasons.append(
                f"question dropped: quote not found in {question.evidence.segment_id}"
            )
            continue
        kept.append(question)
    report.quiz_kept = len(kept)
    report.quiz_dropped = len(quiz) - len(kept)
    return kept


def _verify_chapters(
    chapters: list[Chapter], segments: dict[str, Segment], report: ValidationReport
) -> list[VerifiedChapter]:
    """Chapters are kept even when unverified, because a gap breaks navigation.

    An unverified chapter gets no timestamp: the segment it claims to start at is
    precisely what we could not confirm.
    """
    order = {segment_id: index for index, segment_id in enumerate(segments)}
    verified: list[VerifiedChapter] = []
    last_position = -1

    for chapter in chapters:
        segment = segments.get(chapter.start_segment_id)
        if segment is None:
            verified.append(
                VerifiedChapter(chapter, None, False, "start segment does not exist")
            )
            continue
        if not quote_is_grounded(chapter.evidence, segments):
            verified.append(
                VerifiedChapter(chapter, None, False, "quote not found in the cited segment")
            )
            continue

        position = order[chapter.start_segment_id]
        if position <= last_position:
            verified.append(
                VerifiedChapter(chapter, None, False, "starts before the previous chapter")
            )
            continue

        last_position = position
        verified.append(VerifiedChapter(chapter, segment.start, True))

    report.chapters_verified = sum(1 for item in verified if item.verified)
    report.chapters_flagged = sum(1 for item in verified if not item.verified)
    for item in verified:
        if not item.verified:
            reason = f"chapter flagged unverified: {item.reason}"
            report.reasons.append(reason)
    return verified


def validate(result: EpisodeResult, segments: dict[str, Segment]) -> GroundedResult:
    """Run the pipeline in order. Raises GroundingRejected if too little survives."""
    report = ValidationReport()

    takeaways = _filter_takeaways(list(result.overview.takeaways), segments, report)
    quiz = _filter_quiz(list(result.quiz), segments, report)
    chapters = _verify_chapters(list(result.chapters), segments, report)

    grounded_items = (
        report.takeaways_kept
        + report.takeaways_dropped
        + report.quiz_kept
        + report.quiz_dropped
        + len(chapters)
    )
    failed_items = report.dropped_total + report.chapters_flagged

    if not result.overview.summary.strip():
        raise GroundingRejected("the summary was empty")
    if report.chapters_verified < 2:
        raise GroundingRejected(
            f"only {report.chapters_verified} chapter(s) could be verified"
        )
    if not quiz:
        raise GroundingRejected("no quiz question survived validation")
    if grounded_items and failed_items > grounded_items / 2:
        # Scattered failures are normal. A majority means the model was not working
        # from this transcript at all, and retrying is better than showing the remains.
        raise GroundingRejected(
            f"{failed_items} of {grounded_items} grounded items failed validation"
        )

    has_timestamps = any(item.start_seconds is not None for item in chapters)
    return GroundedResult(
        summary=result.overview.summary.strip(),
        themes=list(result.overview.themes),
        takeaways=takeaways,
        chapters=chapters,
        quiz=quiz,
        report=report,
        has_timestamps=has_timestamps,
    )
