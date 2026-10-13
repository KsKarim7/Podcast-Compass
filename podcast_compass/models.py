"""The contract in both directions: the schema we send and the shape we parse back.

Deliberately flat. Gemini supports only a subset of JSON Schema and warns that large or
deeply nested schemas may be rejected, so there are no optional fields, no unions and no
nesting beyond one level.

No model here has a timestamp field. Chapters cite a segment id and our own code looks up
that segment's start time, so the model has nowhere to put an invented time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    segment_id: str = Field(description="Id of the segment this came from, e.g. S001")
    quote: str = Field(description="5-25 words copied exactly from that segment")


class Takeaway(BaseModel):
    text: str = Field(description="One thing a listener should remember")
    evidence: Evidence


class Overview(BaseModel):
    summary: str = Field(description="A short paragraph covering the whole episode")
    themes: list[str] = Field(description="3-5 recurring themes, a few words each")
    takeaways: list[Takeaway] = Field(description="3-5 takeaways, each with evidence")


class Chapter(BaseModel):
    title: str = Field(description="A short descriptive title")
    explanation: str = Field(description="One or two sentences on what happens here")
    start_segment_id: str = Field(description="Id of the segment this chapter starts at")
    evidence: Evidence


class QuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(description="Exactly 4 options")
    correct_index: int = Field(description="0-based index of the correct option")
    explanation: str = Field(description="Why that option is correct")
    evidence: Evidence


class EpisodeResult(BaseModel):
    overview: Overview
    chapters: list[Chapter] = Field(
        description="Chapters in transcript order; the task states how many"
    )
    quiz: list[QuizQuestion] = Field(description="5-8 questions")


# One schema per revisable section, so a revision call sends only what it needs to.
class OverviewOnly(BaseModel):
    overview: Overview


class ChaptersOnly(BaseModel):
    chapters: list[Chapter]


class QuizOnly(BaseModel):
    quiz: list[QuizQuestion]


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "overview": OverviewOnly,
    "chapters": ChaptersOnly,
    "quiz": QuizOnly,
}


def replace_section(result: EpisodeResult, section: str, revised: BaseModel) -> EpisodeResult:
    """Swap one section into an existing result.

    The merged result is re-validated from scratch, which is why a revision is held to
    exactly the same grounding rules as the original generation.
    """
    if section not in SECTION_MODELS:
        raise ValueError(f"unknown section: {section!r}")

    data = result.model_dump()
    data[section] = revised.model_dump()[section]
    return EpisodeResult.model_validate(data)
