import pytest

from podcast_compass import config
from podcast_compass.parsing import (
    InputError,
    decode_bytes,
    detect_format,
    parse_cues,
    parse_transcript,
    validate_length,
)
from tests.conftest import words


class TestDetection:
    def test_webvtt_header_detected(self, vtt_text):
        assert detect_format(vtt_text) == "vtt"

    def test_srt_timing_line_detected(self, srt_text):
        assert detect_format(srt_text) == "srt"

    def test_plain_text_detected(self, long_plain_text):
        assert detect_format(long_plain_text) == "text"

    def test_bom_before_webvtt_still_detected(self, vtt_text):
        assert detect_format("﻿" + vtt_text) == "vtt"

    def test_txt_file_holding_vtt_markup_is_detected_as_vtt(self, vtt_text):
        # Detection is by content, so the extension it arrived with is irrelevant.
        assert detect_format(vtt_text) == "vtt"

    def test_srt_timing_beyond_the_first_twenty_lines_is_not_detected(self):
        padded = "\n".join(["chatter"] * 25) + "\n00:00:01,000 --> 00:00:02,000\nhello\n"
        assert detect_format(padded) == "text"


class TestDecoding:
    def test_utf8_bom_is_stripped(self):
        assert decode_bytes("hello".encode("utf-8-sig")) == "hello"

    def test_plain_utf8_decoded(self):
        assert decode_bytes("café".encode("utf-8")) == "café"

    def test_cp1252_fallback(self):
        # 0x92 is a curly apostrophe in cp1252 and invalid as UTF-8.
        assert decode_bytes(b"it\x92s warm") == "it’s warm"

    def test_utf16_decoded_rather_than_mangled(self):
        # cp1252 would decode these bytes into mojibake instead of failing, so the
        # BOM has to be checked before the fallback runs.
        assert decode_bytes("hello there".encode("utf-16")) == "hello there"

    def test_utf16_big_endian_decoded(self):
        assert decode_bytes(b"\xfe\xff" + "hello".encode("utf-16-be")) == "hello"

    def test_undecodable_bytes_rejected(self):
        # 0x81 and 0x90 are undefined in cp1252 and invalid as UTF-8.
        with pytest.raises(InputError, match="text encoding"):
            decode_bytes(b"ok\x81\x90bad")


class TestLengthLimits:
    def test_empty_rejected(self):
        with pytest.raises(InputError, match="no text in it"):
            validate_length("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(InputError, match="no text in it"):
            validate_length("   \n\n\t  ")

    def test_below_minimum_rejected_with_the_real_word_count(self):
        with pytest.raises(InputError) as excinfo:
            validate_length("only four words here")
        assert "4 words" in str(excinfo.value)
        assert f"{config.MIN_WORDS} words" in str(excinfo.value)

    def test_just_under_the_word_minimum_is_rejected(self):
        with pytest.raises(InputError) as excinfo:
            validate_length(words(config.MIN_WORDS - 1))
        assert f"{config.MIN_WORDS - 1} words" in str(excinfo.value)

    def test_exactly_the_word_minimum_is_accepted(self):
        validate_length(words(config.MIN_WORDS))

    def test_over_cap_rejected_with_the_real_count(self):
        oversized = words(config.MAX_CHARS // 5 + 10, "abcd")
        assert len(oversized) > config.MAX_CHARS
        with pytest.raises(InputError) as excinfo:
            validate_length(oversized)
        assert f"{len(oversized):,} characters" in str(excinfo.value)

    def test_just_inside_the_cap_is_accepted(self):
        text = words(config.MAX_CHARS // 5 - 10, "abcd")
        assert len(text) <= config.MAX_CHARS
        validate_length(text)


class TestCueParsing:
    def test_vtt_cues_parsed_with_times(self, vtt_text):
        cues, malformed = parse_cues(vtt_text)
        assert malformed == 0
        assert len(cues) == 3
        assert cues[0].start == 0.0
        assert cues[0].end == 4.5
        assert cues[0].text.startswith("So the thing people")

    def test_srt_comma_separator_parsed(self, srt_text):
        cues, malformed = parse_cues(srt_text)
        assert malformed == 0
        assert len(cues) == 3
        assert cues[1].start == 4.5

    def test_missing_hour_field_accepted(self):
        cues, _ = parse_cues("1\n01:30.000 --> 01:35.000\nhello there\n")
        assert cues[0].start == 90.0

    def test_inline_voice_tags_stripped(self):
        cues, _ = parse_cues(
            "00:00:01.000 --> 00:00:02.000\n<v Alice>Hello <c.yellow>there</c></v>\n"
        )
        assert cues[0].text == "Hello there"

    def test_note_and_style_blocks_ignored(self):
        text = (
            "WEBVTT\n\nNOTE this is a comment\n\n"
            "STYLE\n::cue { color: red }\n\n"
            "00:00:01.000 --> 00:00:02.000\nreal line\n"
        )
        cues, malformed = parse_cues(text)
        assert malformed == 0
        assert [cue.text for cue in cues] == ["real line"]

    def test_empty_cue_text_dropped(self):
        text = (
            "00:00:01.000 --> 00:00:02.000\n\n\n"
            "00:00:02.000 --> 00:00:03.000\nkept\n"
        )
        cues, _ = parse_cues(text)
        assert [cue.text for cue in cues] == ["kept"]

    def test_out_of_order_cues_sorted_by_start(self):
        text = (
            "00:00:10.000 --> 00:00:12.000\nsecond\n\n"
            "00:00:01.000 --> 00:00:03.000\nfirst\n"
        )
        cues, _ = parse_cues(text)
        assert [cue.text for cue in cues] == ["first", "second"]

    def test_overlapping_cues_both_kept(self):
        text = (
            "00:00:01.000 --> 00:00:05.000\nfirst\n\n"
            "00:00:03.000 --> 00:00:07.000\noverlaps\n"
        )
        cues, _ = parse_cues(text)
        assert len(cues) == 2

    def test_block_without_a_timing_line_counted_as_malformed(self):
        text = (
            "00:00:01.000 --> 00:00:02.000\ngood\n\n"
            "99 this block has no arrow\nand two lines\n"
        )
        cues, malformed = parse_cues(text)
        assert len(cues) == 1
        assert malformed == 1


class TestParseTranscript:
    def test_vtt_gives_timestamps(self, vtt_text):
        parsed = parse_transcript(vtt_text)
        assert parsed.detected == "vtt"
        assert parsed.has_timestamps is True
        assert len(parsed.cues) == 3

    def test_plain_text_has_no_timestamps(self, long_plain_text):
        parsed = parse_transcript(long_plain_text)
        assert parsed.detected == "text"
        assert parsed.has_timestamps is False
        assert parsed.cues == ()

    def test_crlf_normalised(self, long_plain_text):
        parsed = parse_transcript(long_plain_text.replace("\n", "\r\n"))
        assert "\r" not in parsed.text

    def test_mostly_malformed_file_rejected(self):
        # Long enough to reach the cue checks: the word minimum is tested separately.
        broken = "\n\n".join([f"{i} no arrow here at all in this block" for i in range(20)])
        text = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            + words(140, "cue")
            + "\n\n"
            + broken
        )
        with pytest.raises(InputError, match="looks damaged"):
            parse_transcript(text)

    def test_vtt_with_no_cues_but_readable_text_falls_back(self):
        # Enough prose survives markup stripping to be worth keeping.
        body = "\n\n".join([words(100, "sourdough")] * 3)
        with_header = f"WEBVTT\n\n{body}"
        parsed = parse_transcript(with_header)
        assert parsed.detected == "text"
        assert parsed.fell_back_to_text is True
        assert parsed.has_timestamps is False

    def test_header_only_file_rejected(self):
        # Enough "words" to clear the minimum, but nothing survives markup stripping.
        timings = "\n\n".join(
            [f"{i}\n00:00:0{i % 10}.000 --> 00:00:0{(i + 1) % 10}.000" for i in range(130)]
        )
        with pytest.raises(InputError, match="could not read any subtitle cues"):
            parse_transcript(f"WEBVTT\n\n{timings}")

    def test_malformed_within_tolerance_is_kept_and_counted(self):
        good = "\n\n".join(
            [
                f"00:00:{i:02d}.000 --> 00:00:{i + 1:02d}.000\nline {i} " + words(30)
                for i in range(10)
            ]
        )
        text = f"WEBVTT\n\n{good}\n\nstray block with no arrow in it\n"
        parsed = parse_transcript(text)
        assert parsed.malformed_cues == 1
        assert len(parsed.cues) == 10


class TestWordMinimumGuaranteesEnoughSegments:
    """Why the minimum is in words: it is what makes two chapters possible at all."""

    def test_the_minimum_yields_at_least_two_segments_of_plain_text(self):
        from podcast_compass.segments import build_segments

        parsed = parse_transcript(words(config.MIN_WORDS))
        assert len(build_segments(parsed)) >= 2

    def test_one_word_under_the_minimum_is_refused_before_any_call(self):
        with pytest.raises(InputError, match="at least"):
            parse_transcript(words(config.MIN_WORDS - 1))

    def test_a_single_long_cue_still_makes_only_one_segment(self):
        # The word minimum does not guarantee two segments for subtitles: one cue is
        # never split. This is why the chapter requirement also adapts to the input.
        from podcast_compass.segments import build_segments

        cue = "00:00:00.000 --> 00:05:00.000\n" + words(config.MIN_WORDS + 50)
        parsed = parse_transcript(f"WEBVTT\n\n{cue}")
        assert len(parsed.cues) == 1
        assert len(build_segments(parsed)) == 1

    def test_word_count_matches_the_segmenter(self):
        from podcast_compass.parsing import count_words

        assert count_words("  two   words  ") == 2
        assert count_words("") == 0
