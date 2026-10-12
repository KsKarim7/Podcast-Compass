"""The copy and download payloads."""

import pytest

from podcast_compass import export, render, sample
from podcast_compass.grounding import validate
from podcast_compass.parsing import parse_transcript
from podcast_compass.segments import build_segments, segment_lookup
from tests.fixtures import handwritten_result


@pytest.fixture
def grounded_demo():
    parsed = parse_transcript(sample.load_transcript())
    segments = build_segments(parsed)
    return parsed, segments, validate(handwritten_result(), segment_lookup(segments))


class TestMarkdownExport:
    def test_contains_every_section(self, grounded_demo):
        _, _, result = grounded_demo
        md = export.as_markdown(result)
        for heading in ("## Summary", "## Themes", "## Key takeaways", "## Chapters", "## Quiz"):
            assert heading in md

    def test_quotes_and_segment_ids_survive(self, grounded_demo):
        _, _, result = grounded_demo
        md = export.as_markdown(result)
        for takeaway in result.takeaways:
            assert takeaway.evidence.quote in md
            assert takeaway.evidence.segment_id in md

    def test_timestamps_appear_in_chapter_headings(self, grounded_demo):
        _, _, result = grounded_demo
        md = export.as_markdown(result)
        assert "[00:00:00]" in md
        assert "[00:01:10]" in md

    def test_correct_answer_is_marked(self, grounded_demo):
        _, _, result = grounded_demo
        md = export.as_markdown(result)
        first = result.quiz[0]
        assert f"- [x] {first.options[first.correct_index]}" in md

    def test_no_timestamp_notice_included_for_plain_text(self):
        parsed = parse_transcript(sample.load_transcript())
        segments = build_segments(parsed)
        untimed = {
            sid: segment.__class__(id=sid, text=segment.text, start=None, end=None)
            for sid, segment in segment_lookup(segments).items()
        }
        result = validate(handwritten_result(), untimed)
        md = export.as_markdown(result)
        assert render.NO_TIMESTAMP_NOTICE in md

    def test_ends_with_a_single_newline(self, grounded_demo):
        _, _, result = grounded_demo
        md = export.as_markdown(result)
        assert md.endswith("\n")
        assert not md.endswith("\n\n")


class TestJsonExport:
    def test_round_trips_as_json(self, grounded_demo):
        import json

        _, _, result = grounded_demo
        payload = json.loads(export.as_json(result, model="gemini-3.5-flash-lite"))
        assert payload["model"] == "gemini-3.5-flash-lite"
        assert payload["has_timestamps"] is True
        assert len(payload["chapters"]) == 3
        assert len(payload["quiz"]) == 4

    def test_timestamps_are_ours_and_human_readable(self, grounded_demo):
        _, _, result = grounded_demo
        payload = export.as_dict(result)
        first = payload["chapters"][0]
        assert first["start_seconds"] == 0.0
        assert first["start_timestamp"] == "00:00:00"
        assert payload["chapters"][1]["start_timestamp"] == "00:01:10"

    def test_validation_counts_are_included(self, grounded_demo):
        _, _, result = grounded_demo
        payload = export.as_dict(result)
        assert payload["validation"]["takeaways_dropped"] == 0
        assert payload["validation"]["chapters_verified"] == 3

    def test_evidence_survives_into_json(self, grounded_demo):
        _, _, result = grounded_demo
        payload = export.as_dict(result)
        quote = payload["overview"]["takeaways"][0]["evidence"]["quote"]
        assert quote == result.takeaways[0].evidence.quote

    def test_generated_at_defaults_to_now(self, grounded_demo):
        _, _, result = grounded_demo
        assert export.as_dict(result)["generated_at"]
