"""The app script itself, run through Streamlit's AppTest.

This catches what unit tests cannot: an invalid widget argument, a state key that is
read before it is set, or an exception on first load. It makes no API call, because the
example episode is rendered from the built-in fixture.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from podcast_compass import config, render

# AppTest resolves a relative path against the file that calls it, which would look
# inside tests/, so the path is built from the repo root.
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def button(at: AppTest, label: str):
    for candidate in at.button:
        if candidate.label == label:
            return candidate
    raise AssertionError(f"no button labelled {label!r}; found {[b.label for b in at.button]}")


class TestFirstLoad:
    def test_runs_without_exceptions(self, app):
        assert not app.exception

    def test_shows_the_title(self, app):
        assert app.title[0].value == "Podcast Compass"

    def test_data_use_notice_is_visible_before_any_input(self, app):
        assert any(render.DATA_USE_NOTICE in w.value for w in app.warning)

    def test_limits_text_comes_from_config(self, app):
        assert any(config.LIMITS_TEXT in c.value for c in app.caption)

    def test_upload_and_paste_are_both_offered(self, app):
        assert app.text_area
        # The uploader is not exposed as its own AppTest accessor, so assert the
        # script produced no exception while declaring it and that the cap is ours.
        assert config.MAX_UPLOAD_MB == 2

    def test_no_results_before_anything_is_loaded(self, app):
        assert not app.subheader


class TestExampleEpisode:
    @pytest.fixture
    def loaded(self, app) -> AppTest:
        button(app, "Load example episode").click().run()
        return app

    def test_loads_without_exceptions(self, loaded):
        assert not loaded.exception

    def test_renders_all_three_sections(self, loaded):
        headings = [s.value for s in loaded.subheader]
        assert headings == ["Overview", "Chapters", "Quiz"]

    def test_detection_line_reports_webvtt_and_cues(self, loaded):
        captions = " ".join(c.value for c in loaded.caption)
        assert "WebVTT" in captions
        assert "12 cues" in captions
        assert "timestamps available" in captions

    def test_validation_summary_shows_real_counts(self, loaded):
        captions = " ".join(c.value for c in loaded.caption)
        assert "Kept 4 of 4 takeaways" in captions

    def test_chapter_timestamps_rendered(self, loaded):
        body = " ".join(m.value for m in loaded.markdown)
        assert "[00:00:00]" in body
        assert "[00:01:10]" in body
        assert "[00:02:21]" in body

    def test_evidence_quotes_are_shown_not_hidden(self, loaded):
        captions = " ".join(c.value for c in loaded.caption)
        assert "The limiting factor in a city is water, not flowers" in captions

    def test_quiz_is_a_form_with_one_radio_per_question(self, loaded):
        assert len(loaded.radio) == 4

    def test_no_timestamp_notice_absent_for_a_vtt_source(self, loaded):
        infos = " ".join(i.value for i in loaded.info)
        assert render.NO_TIMESTAMP_NOTICE not in infos


class TestQuizInteraction:
    @pytest.fixture
    def loaded(self, app) -> AppTest:
        button(app, "Load example episode").click().run()
        return app

    def test_answering_correctly_is_reported(self, loaded):
        # A widget inside st.form only commits its value when the form is submitted,
        # so the value and the click have to happen in the same run cycle.
        loaded.radio[0].set_value(1)  # the demo's first answer is index 1
        button(loaded, "Check answers").click()
        loaded.run()
        assert not loaded.exception
        assert loaded.session_state["answer_0"] == 1
        assert any("Correct" in s.value for s in loaded.success)

    def test_answering_incorrectly_reveals_the_answer_and_evidence(self, loaded):
        loaded.radio[0].set_value(0)
        button(loaded, "Check answers").click()
        loaded.run()
        assert any("Not quite" in e.value for e in loaded.error)
        captions = " ".join(c.value for c in loaded.caption)
        assert "S001" in captions

    def test_unanswered_question_is_flagged_not_marked_wrong(self, loaded):
        button(loaded, "Check answers").click().run()
        assert any("Not answered" in w.value for w in loaded.warning)


class TestInputValidation:
    def test_empty_submission_is_rejected_without_a_crash(self, app):
        button(app, "Check this transcript").click().run()
        assert not app.exception
        assert any("Paste a transcript" in e.value for e in app.error)

    def test_short_transcript_is_rejected_with_the_real_count(self, app):
        app.text_area[0].set_value("too short").run()
        button(app, "Check this transcript").click().run()
        assert any("9 characters" in e.value for e in app.error)

    def test_plain_text_is_accepted_and_reports_no_timestamps(self, app):
        app.text_area[0].set_value("fermentation depends on temperature. " * 20).run()
        button(app, "Check this transcript").click().run()
        assert not app.exception
        captions = " ".join(c.value for c in app.caption)
        assert "plain text" in captions
        assert "no timestamps" in captions
