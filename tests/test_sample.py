"""The committed sample: the transcript always exists, the result may not yet."""

import json

import pytest

from podcast_compass import sample
from podcast_compass.grounding import validate
from podcast_compass.models import EpisodeResult
from podcast_compass.parsing import parse_transcript
from podcast_compass.segments import build_segments, segment_lookup

needs_sample = pytest.mark.skipif(
    not sample.result_exists(),
    reason="run tools/generate_sample.py to create samples/sample_results.json",
)


class TestTranscript:
    def test_transcript_is_committed_and_readable(self):
        assert sample.TRANSCRIPT_PATH.is_file()
        assert sample.load_transcript().startswith("WEBVTT")

    def test_transcript_is_labelled_as_original_material(self):
        text = sample.load_transcript()
        assert "original script written for this demo" in text.casefold()

    def test_transcript_parses_into_several_timed_segments(self):
        parsed = parse_transcript(sample.load_transcript())
        segments = build_segments(parsed)
        assert parsed.detected == "vtt"
        assert parsed.has_timestamps
        # Chapters need strictly increasing segments, so one segment would not do.
        assert len(segments) >= 3

    def test_note_block_does_not_become_a_cue(self):
        parsed = parse_transcript(sample.load_transcript())
        joined = " ".join(cue.text for cue in parsed.cues).casefold()
        assert "original script written for this demo" not in joined
        assert parsed.malformed_cues == 0


class TestMissingResult:
    @pytest.mark.skipif(
        sample.result_exists(), reason="only applies before the sample is generated"
    )
    def test_loader_names_the_script_to_run(self):
        with pytest.raises(FileNotFoundError, match="generate_sample.py"):
            sample.load_bundle()


@needs_sample
class TestGeneratedResult:
    def test_bundle_loads_and_parses_into_the_schema(self):
        bundle = sample.load_bundle()
        assert isinstance(bundle.result, EpisodeResult)
        assert bundle.model
        assert bundle.generated_at

    def test_label_states_date_model_and_that_no_call_was_made(self):
        label = sample.load_bundle().label
        assert "Pre-generated with this app on" in label
        assert sample.load_bundle().model in label
        assert "No API call was made just now." in label

    def test_the_committed_result_passes_grounding(self):
        # If this fails the sample is stale: the prompts or schema changed and the
        # file needs regenerating.
        bundle = sample.load_bundle()
        segments = build_segments(parse_transcript(bundle.transcript))
        grounded = validate(bundle.result, segment_lookup(segments))
        assert grounded.report.chapters_verified >= 2
        assert grounded.quiz

    def test_file_records_how_it_was_made(self):
        payload = json.loads(sample.RESULT_PATH.read_text(encoding="utf-8"))
        assert "generate_sample.py" in payload["note"]
        assert payload["model"]

    def test_no_timestamp_is_stored_in_the_model_data(self):
        # Times are derived from cues at render time, never persisted into model output.
        payload = json.loads(sample.RESULT_PATH.read_text(encoding="utf-8"))
        for chapter in payload["result"]["chapters"]:
            assert "start_seconds" not in chapter
            assert "start_timestamp" not in chapter
            assert chapter["start_segment_id"].startswith("S")
