import pytest

from podcast_compass import export, render, sample
from podcast_compass.grounding import VerifiedChapter, validate
from podcast_compass.models import Chapter, Evidence
from podcast_compass.parsing import parse_transcript
from podcast_compass.segments import build_segments, segment_lookup
from tests.conftest import long_enough
from tests.fixtures import handwritten_result

@pytest.fixture
def grounded_demo():
    parsed = parse_transcript(sample.load_transcript())
    segments = build_segments(parsed)
    return parsed, segments, validate(handwritten_result(), segment_lookup(segments))


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
        parsed = parse_transcript(long_enough())
        line = render.detection_line(parsed, 1)
        assert "plain text" in line
        assert "no timestamps" in line

    def test_fallback_is_named_honestly(self):
        body = "\n\n".join(["sourdough " * 100] * 3)
        parsed = parse_transcript(f"WEBVTT\n\n{body}")
        line = render.detection_line(parsed, 2)
        assert "could not read" in line
        assert "plain text" in line

    def test_skipped_cues_are_reported(self):
        good = "\n\n".join(
            [
                f"00:00:{i:02d}.000 --> 00:00:{i + 1:02d}.000\nline {i} here "
                + " ".join(["pad"] * 30)
                for i in range(10)
            ]
        )
        parsed = parse_transcript(f"WEBVTT\n\n{good}\n\nstray block with no arrow in it\n")
        line = render.detection_line(parsed, 1)
        assert "1 unreadable cue skipped" in line

    def test_counts_are_singular_when_there_is_one(self):
        parsed = parse_transcript(long_enough())
        assert "1 segment ·" in render.detection_line(parsed, 1) + " ·"
        assert "1 segments" not in render.detection_line(parsed, 1)

    def test_counts_are_plural_when_there_are_several(self):
        parsed = parse_transcript(long_enough())
        assert "3 segments" in render.detection_line(parsed, 3)


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
