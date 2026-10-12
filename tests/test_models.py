import pytest
from pydantic import ValidationError

from podcast_compass.models import (
    SECTION_MODELS,
    Chapter,
    EpisodeResult,
    Evidence,
    QuizQuestion,
)


def evidence() -> dict:
    return {"segment_id": "S001", "quote": "the timing, not the recipe"}


class TestShape:
    def test_every_grounded_item_carries_evidence(self):
        for model in (Chapter, QuizQuestion):
            assert "evidence" in model.model_fields

    def test_no_model_has_a_timestamp_field(self):
        # Times come from the parsed cues, so the model has nowhere to invent one.
        for model in (Chapter, QuizQuestion, EpisodeResult, Evidence):
            fields = " ".join(model.model_fields)
            assert "time" not in fields
            assert "start" not in fields.replace("start_segment_id", "")

    def test_chapter_cites_a_segment_not_a_time(self):
        assert "start_segment_id" in Chapter.model_fields
        assert "start_time" not in Chapter.model_fields


class TestValidation:
    def test_missing_evidence_rejected(self):
        with pytest.raises(ValidationError):
            Chapter(title="t", explanation="e", start_segment_id="S001")

    def test_missing_quote_rejected(self):
        with pytest.raises(ValidationError):
            Evidence(segment_id="S001")

    def test_correct_index_must_be_an_int(self):
        with pytest.raises(ValidationError):
            QuizQuestion(
                question="q",
                options=["a", "b", "c", "d"],
                correct_index="two",
                explanation="e",
                evidence=evidence(),
            )

    def test_valid_quiz_question_accepted(self):
        q = QuizQuestion(
            question="q",
            options=["a", "b", "c", "d"],
            correct_index=1,
            explanation="e",
            evidence=evidence(),
        )
        assert q.evidence.segment_id == "S001"


class TestSchemaIsFlatEnough:
    def test_json_schema_generates(self):
        schema = EpisodeResult.model_json_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"overview", "chapters", "quiz"}

    def test_no_optional_fields_anywhere(self):
        # Gemini's strict-ish subset is happiest with every field required.
        schema = EpisodeResult.model_json_schema()
        for name, definition in schema.get("$defs", {}).items():
            if definition.get("type") == "object":
                assert set(definition["required"]) == set(definition["properties"]), name

    def test_section_models_cover_the_three_revisable_sections(self):
        assert set(SECTION_MODELS) == {"overview", "chapters", "quiz"}
        for model in SECTION_MODELS.values():
            assert model.model_json_schema()["type"] == "object"
