"""Section replacement and undo, which are pure data operations with no API call."""

import pytest

from podcast_compass import sample
from podcast_compass.grounding import validate
from podcast_compass.models import (
    SECTION_MODELS,
    ChaptersOnly,
    OverviewOnly,
    QuizOnly,
    replace_section,
)
from podcast_compass.parsing import parse_transcript
from podcast_compass.segments import build_segments, segment_lookup
from tests.fixtures import handwritten_result


@pytest.fixture
def segments():
    return build_segments(parse_transcript(sample.load_transcript()))


@pytest.fixture
def lookup(segments):
    return segment_lookup(segments)


class TestSectionModels:
    def test_each_section_parses_out_of_a_full_result(self):
        raw = handwritten_result()
        data = raw.model_dump()
        assert OverviewOnly.model_validate(data).overview.summary == raw.overview.summary
        assert len(ChaptersOnly.model_validate(data).chapters) == len(raw.chapters)
        assert len(QuizOnly.model_validate(data).quiz) == len(raw.quiz)

    def test_section_schemas_are_smaller_than_the_whole(self):
        import json

        from podcast_compass.models import EpisodeResult

        whole = len(json.dumps(EpisodeResult.model_json_schema()))
        for model in SECTION_MODELS.values():
            assert len(json.dumps(model.model_json_schema())) < whole


class TestReplaceSection:
    def test_only_the_named_section_changes(self):
        raw = handwritten_result()
        revised_quiz = QuizOnly(quiz=raw.quiz[:1])
        merged = replace_section(raw, "quiz", revised_quiz)

        assert len(merged.quiz) == 1
        assert merged.overview == raw.overview
        assert merged.chapters == raw.chapters

    def test_overview_replacement_leaves_chapters_and_quiz(self):
        raw = handwritten_result()
        trimmed = OverviewOnly.model_validate(raw.model_dump())
        trimmed.overview.summary = "Much shorter."
        merged = replace_section(raw, "overview", trimmed)

        assert merged.overview.summary == "Much shorter."
        assert merged.chapters == raw.chapters
        assert merged.quiz == raw.quiz

    def test_unknown_section_rejected(self):
        with pytest.raises(ValueError, match="unknown section"):
            replace_section(handwritten_result(), "sidebar", QuizOnly(quiz=[]))

    def test_merged_result_still_validates_against_the_transcript(self, lookup):
        raw = handwritten_result()
        merged = replace_section(raw, "quiz", QuizOnly(quiz=raw.quiz[:2]))
        grounded = validate(merged, lookup)
        assert len(grounded.quiz) == 2

    def test_a_revision_with_bad_evidence_is_caught_by_validation(self, lookup):
        raw = handwritten_result()
        bad = QuizOnly.model_validate(raw.model_dump())
        for question in bad.quiz:
            question.evidence.quote = "words that are not in the transcript anywhere"
        merged = replace_section(raw, "quiz", bad)

        from podcast_compass.grounding import GroundingRejected

        # A revision is held to exactly the same standard as the first generation.
        with pytest.raises(GroundingRejected):
            validate(merged, lookup)


class TestUndoIsAStateSwap:
    def test_restoring_a_kept_section_returns_the_original(self):
        raw = handwritten_result()
        before = QuizOnly.model_validate(raw.model_dump())

        shortened = replace_section(raw, "quiz", QuizOnly(quiz=raw.quiz[:1]))
        assert len(shortened.quiz) == 1

        restored = replace_section(shortened, "quiz", before)
        assert restored.quiz == raw.quiz

    def test_round_trip_changes_nothing_else(self):
        raw = handwritten_result()
        before = ChaptersOnly.model_validate(raw.model_dump())
        changed = replace_section(raw, "chapters", ChaptersOnly(chapters=raw.chapters[:2]))
        restored = replace_section(changed, "chapters", before)
        assert restored == raw
