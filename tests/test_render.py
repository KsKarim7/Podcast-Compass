from podcast_compass import render
from podcast_compass.demo import DEMO_VTT, demo_result
from podcast_compass.grounding import validate
from podcast_compass.models import Chapter, Evidence
from podcast_compass.parsing import parse_transcript
from podcast_compass.segments import build_segments, segment_lookup
import pytest

from podcast_compass.grounding import VerifiedChapter


@pytest.fixture
def grounded_demo():
    parsed = parse_transcript(DEMO_VTT)
    segments = build_segments(parsed)
    return parsed, segments, validate(demo_result(), segment_lookup(segments))


def chapter(title="Timing") -> Chapter:
    return Chapter(
        title=title,
        explanation="why",
        start_segment_id="S001",
        evidence=Evidence(segment_id="S001", quote="a quote of some length"),
    )


class TestDemoFixture:
    def test_demo_passes_validation_with_nothing_dropped(self, grounded_demo):
        # The built-in example has to survive the real pipeline, or the interface would
        # be demonstrating a result the app could not actually produce.
        _, _, result = grounded_demo
        assert result.report.takeaways_dropped == 0
        assert result.report.quiz_dropped == 0
        assert result.report.chapters_flagged == 0
        assert result.report.chapters_verified == 3

    def test_demo_has_real_timestamps(self, grounded_demo):
        _, _, result = grounded_demo
        assert result.has_timestamps
        assert [item.start_seconds for item in result.chapters] == [0.0, 70.0, 141.0]


class TestDetectionLine:
    def test_vtt_reports_cues_and_timestamps(self, grounded_demo):
        parsed, segments, _ = grounded_demo
        line = render.detection_line(parsed, len(segments))
        assert "WebVTT" in line
        assert "12 cues" in line
        assert "timestamps available" in line
        assert "3 segments" in line

    def test_plain_text_says_no_timestamps(self):
        parsed = parse_transcript("word " * 100)
        line = render.detection_line(parsed, 1)
        assert "plain text" in line
        assert "no timestamps" in line

    def test_fallback_is_named_honestly(self):
        body = "\n\n".join(["sourdough " * 30] * 3)
        parsed = parse_transcript(f"WEBVTT\n\n{body}")
        line = render.detection_line(parsed, 2)
        assert "could not read" in line
        assert "plain text" in line

    def test_skipped_cues_are_reported(self):
        good = "\n\n".join(
            [f"00:00:{i:02d}.000 --> 00:00:{i + 1:02d}.000\nline {i} here" for i in range(10)]
        )
        parsed = parse_transcript(f"WEBVTT\n\n{good}\n\nstray block with no arrow\n")
        line = render.detection_line(parsed, 1)
        assert "1 unreadable cue(s) skipped" in line


class TestChapterHeading:
    def test_verified_chapter_shows_a_time(self):
        item = VerifiedChapter(chapter(), start_seconds=872.0, verified=True)
        assert render.chapter_heading(item) == "[00:14:32] Timing"

    def test_unverified_chapter_shows_no_time_and_says_why(self):
        item = VerifiedChapter(chapter(), start_seconds=None, verified=False, reason="x")
        heading = render.chapter_heading(item)
        assert "[" not in heading
        assert render.UNVERIFIED_CHAPTER_NOTE in heading

    def test_verified_without_cues_shows_title_only(self):
        item = VerifiedChapter(chapter(), start_seconds=None, verified=True)
        assert render.chapter_heading(item) == "Timing"


class TestAnswerFeedback:
    def test_correct_and_incorrect(self):
        assert render.answer_feedback(2, 2) == "Correct"
        assert render.answer_feedback(1, 2) == "Not quite"


class TestMarkdownExport:
    def test_contains_every_section(self, grounded_demo):
        _, _, result = grounded_demo
        md = render.as_markdown(result)
        for heading in ("## Summary", "## Themes", "## Key takeaways", "## Chapters", "## Quiz"):
            assert heading in md

    def test_quotes_and_segment_ids_survive(self, grounded_demo):
        _, _, result = grounded_demo
        md = render.as_markdown(result)
        for takeaway in result.takeaways:
            assert takeaway.evidence.quote in md
            assert takeaway.evidence.segment_id in md

    def test_timestamps_appear_in_chapter_headings(self, grounded_demo):
        _, _, result = grounded_demo
        md = render.as_markdown(result)
        assert "[00:00:00]" in md
        assert "[00:01:10]" in md

    def test_correct_answer_is_marked(self, grounded_demo):
        _, _, result = grounded_demo
        md = render.as_markdown(result)
        first = result.quiz[0]
        assert f"- [x] {first.options[first.correct_index]}" in md

    def test_no_timestamp_notice_included_for_plain_text(self):
        parsed = parse_transcript(DEMO_VTT)
        segments = build_segments(parsed)
        untimed = {
            sid: segment.__class__(id=sid, text=segment.text, start=None, end=None)
            for sid, segment in segment_lookup(segments).items()
        }
        result = validate(demo_result(), untimed)
        md = render.as_markdown(result)
        assert render.NO_TIMESTAMP_NOTICE in md

    def test_ends_with_a_single_newline(self, grounded_demo):
        _, _, result = grounded_demo
        md = render.as_markdown(result)
        assert md.endswith("\n")
        assert not md.endswith("\n\n")


class TestNotices:
    def test_data_use_notice_names_the_three_facts(self):
        text = render.DATA_USE_NOTICE.casefold()
        assert "improve google's products" in text
        assert "human reviewers" in text
        assert "confidential" in text

    def test_no_timestamp_notice_explains_why(self):
        text = render.NO_TIMESTAMP_NOTICE.casefold()
        assert "subtitle cues" in text
        assert "cannot invent" in text
