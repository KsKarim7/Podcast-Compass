"""The copy and download payloads.

Separate from render.py, which produces strings for the screen. One function per format
so the copy button and the download button can never disagree.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .grounding import GroundedResult
from .render import NO_TIMESTAMP_NOTICE, chapter_heading, evidence_caption
from .segments import format_timestamp


def as_markdown(result: GroundedResult, *, title: str = "Episode companion") -> str:
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


def as_dict(result: GroundedResult, *, model: str = "", generated_at: str = "") -> dict:
    """The structured payload. Timestamps appear here because we derived them ourselves."""
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "has_timestamps": result.has_timestamps,
        "validation": {
            "takeaways_kept": result.report.takeaways_kept,
            "takeaways_dropped": result.report.takeaways_dropped,
            "quiz_kept": result.report.quiz_kept,
            "quiz_dropped": result.report.quiz_dropped,
            "chapters_verified": result.report.chapters_verified,
            "chapters_flagged": result.report.chapters_flagged,
        },
        "overview": {
            "summary": result.summary,
            "themes": list(result.themes),
            "takeaways": [
                {
                    "text": takeaway.text,
                    "evidence": takeaway.evidence.model_dump(),
                }
                for takeaway in result.takeaways
            ],
        },
        "chapters": [
            {
                "title": item.chapter.title,
                "explanation": item.chapter.explanation,
                "start_segment_id": item.chapter.start_segment_id,
                "start_seconds": item.start_seconds,
                "start_timestamp": (
                    format_timestamp(item.start_seconds)
                    if item.start_seconds is not None
                    else None
                ),
                "verified": item.verified,
                "unverified_reason": item.reason or None,
                "evidence": item.chapter.evidence.model_dump(),
            }
            for item in result.chapters
        ],
        "quiz": [
            {
                "question": question.question,
                "options": list(question.options),
                "correct_index": question.correct_index,
                "explanation": question.explanation,
                "evidence": question.evidence.model_dump(),
            }
            for question in result.quiz
        ],
    }


def as_json(result: GroundedResult, *, model: str = "", generated_at: str = "") -> str:
    return json.dumps(
        as_dict(result, model=model, generated_at=generated_at), indent=2, ensure_ascii=False
    )
