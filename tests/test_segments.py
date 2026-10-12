from podcast_compass import config
from podcast_compass.parsing import Cue, parse_transcript
from podcast_compass.segments import (
    build_segments,
    format_timestamp,
    render_for_prompt,
    segment_id,
    segment_lookup,
    segments_from_cues,
    segments_from_text,
)
from tests.conftest import words


def cue(start: float, end: float, text: str) -> Cue:
    return Cue(start=start, end=end, text=text)


class TestIds:
    def test_ids_are_zero_padded_and_sequential(self):
        cues = [cue(i, i + 1, words(config.WORDS_PER_SEGMENT)) for i in range(3)]
        segments = segments_from_cues(cues)
        assert [s.id for s in segments] == ["S001", "S002", "S003"]

    def test_segment_id_padding(self):
        assert segment_id(1) == "S001"
        assert segment_id(208) == "S208"


class TestCueMerging:
    def test_short_cues_merge_until_the_word_target(self):
        cues = [cue(i, i + 1, words(10)) for i in range(24)]
        segments = segments_from_cues(cues)
        # 240 words at a 120-word target gives two segments.
        assert len(segments) == 2

    def test_merged_segment_keeps_first_start_and_last_end(self):
        cues = [cue(0, 5, words(60)), cue(5, 11, words(60)), cue(11, 20, words(10))]
        segments = segments_from_cues(cues)
        assert segments[0].start == 0
        assert segments[0].end == 11

    def test_cue_longer_than_the_target_becomes_its_own_segment(self):
        long_cue = cue(0, 90, words(config.WORDS_PER_SEGMENT + 50))
        segments = segments_from_cues([long_cue, cue(90, 95, words(5))])
        assert len(segments) == 2
        assert len(segments[0].text.split()) == config.WORDS_PER_SEGMENT + 50
        assert segments[0].text == long_cue.text

    def test_trailing_cues_below_the_target_still_flushed(self):
        segments = segments_from_cues([cue(0, 2, words(5))])
        assert len(segments) == 1
        assert segments[0].start == 0

    def test_no_cues_gives_no_segments(self):
        assert segments_from_cues([]) == []


class TestTextPacking:
    def test_paragraphs_packed_without_times(self, long_plain_text):
        segments = segments_from_text(long_plain_text)
        assert all(s.start is None and s.end is None for s in segments)
        assert len(segments) >= 1

    def test_over_long_paragraph_is_split(self):
        segments = segments_from_text(words(config.WORDS_PER_SEGMENT * 2 + 30))
        assert len(segments) == 3
        assert len(segments[0].text.split()) == config.WORDS_PER_SEGMENT

    def test_no_segment_exceeds_the_target_for_plain_text(self):
        segments = segments_from_text("\n\n".join([words(70)] * 6))
        assert all(len(s.text.split()) <= config.WORDS_PER_SEGMENT for s in segments)

    def test_blank_paragraphs_ignored(self):
        segments = segments_from_text(f"{words(10)}\n\n\n\n{words(10)}")
        assert len(segments) == 1

    def test_internal_newlines_collapsed(self):
        segments = segments_from_text("one\ntwo\nthree")
        assert segments[0].text == "one two three"


class TestBuildAndLookup:
    def test_build_from_vtt_uses_cues(self, vtt_text):
        segments = build_segments(parse_transcript(vtt_text))
        assert segments[0].start is not None

    def test_build_from_plain_text_has_no_times(self, long_plain_text):
        segments = build_segments(parse_transcript(long_plain_text))
        assert segments[0].start is None

    def test_lookup_keyed_by_id(self, long_plain_text):
        segments = build_segments(parse_transcript(long_plain_text))
        lookup = segment_lookup(segments)
        assert lookup["S001"] is segments[0]
        assert "S999" not in lookup


class TestTimestampFormatting:
    def test_formats_hours_minutes_seconds(self):
        assert format_timestamp(0) == "00:00:00"
        assert format_timestamp(872.4) == "00:14:32"
        assert format_timestamp(3661) == "01:01:01"

    def test_fractional_seconds_truncated_not_rounded(self):
        assert format_timestamp(59.999) == "00:00:59"


class TestPromptRendering:
    def test_includes_ids_and_times_when_present(self, vtt_text):
        rendered = render_for_prompt(build_segments(parse_transcript(vtt_text)))
        assert rendered.startswith("S001 [00:00:00]")

    def test_omits_times_for_plain_text(self, long_plain_text):
        rendered = render_for_prompt(build_segments(parse_transcript(long_plain_text)))
        assert rendered.startswith("S001 ")
        assert "[" not in rendered
