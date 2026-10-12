"""The app script itself, run through Streamlit's AppTest.

This catches what unit tests cannot: an invalid widget argument, a state key read before
it is set, or an exception on first load. No API call is made anywhere here — AppTest has
no secrets file, so the key lookup returns None and the generate path stops at that
boundary, which is itself worth asserting.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from podcast_compass import config, render, sample

# AppTest resolves a relative path against the file that calls it, which would look
# inside tests/, so the path is built from the repo root.
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

needs_sample = pytest.mark.skipif(
    not sample.result_exists(),
    reason="run tools/generate_sample.py to create samples/sample_results.json",
)


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


def captions(at: AppTest) -> str:
    return " ".join(c.value for c in at.caption)


def errors(at: AppTest) -> str:
    return " ".join(e.value for e in at.error)


class TestFirstLoad:
    def test_runs_without_exceptions(self, app):
        assert not app.exception

    def test_shows_the_title(self, app):
        assert app.title[0].value == "Podcast Compass"

    def test_data_use_notice_is_visible_before_any_input(self, app):
        assert any(render.DATA_USE_NOTICE in w.value for w in app.warning)

    def test_limits_text_comes_from_config(self, app):
        assert config.LIMITS_TEXT in captions(app)

    def test_both_buttons_offered(self, app):
        labels = [b.label for b in app.button]
        assert "Load example episode" in labels
        assert "Generate" in labels

    def test_says_generation_is_unavailable_without_a_key(self, app):
        # AppTest has no secrets file, which is the no-key case.
        assert "not configured with an API key" in captions(app)

    def test_no_results_before_anything_is_loaded(self, app):
        assert not app.subheader


class TestInputValidation:
    def test_empty_submission_is_rejected(self, app):
        button(app, "Generate").click().run()
        assert not app.exception
        assert "Paste a transcript or upload a file first." in errors(app)

    def test_short_transcript_is_rejected_with_the_real_count(self, app):
        app.text_area[0].set_value("too short").run()
        button(app, "Generate").click().run()
        assert "9 characters" in errors(app)

    def test_oversized_transcript_is_rejected_with_the_real_count(self, app):
        app.text_area[0].set_value("x" * (config.MAX_CHARS + 5)).run()
        button(app, "Generate").click().run()
        assert f"{config.MAX_CHARS + 5:,} characters" in errors(app)

    def test_valid_input_reaches_the_key_check_and_stops(self, app):
        app.text_area[0].set_value("fermentation depends on temperature. " * 20).run()
        button(app, "Generate").click().run()
        assert not app.exception
        # Detection is still reported, so the user learns about their file either way.
        assert "plain text" in captions(app)
        assert "no timestamps" in captions(app)
        assert "not configured with an API key" in errors(app)

    def test_character_counter_appears_while_typing(self, app):
        app.text_area[0].set_value("abc").run()
        assert f"3 / {config.MAX_CHARS:,} characters" in captions(app)


class TestMissingSample:
    @pytest.mark.skipif(
        sample.result_exists(), reason="only applies before the sample is generated"
    )
    def test_example_button_explains_what_to_run(self, app):
        button(app, "Load example episode").click().run()
        assert not app.exception
        assert "generate_sample.py" in errors(app)


@needs_sample
class TestExampleEpisode:
    @pytest.fixture
    def loaded(self, app) -> AppTest:
        button(app, "Load example episode").click().run()
        return app

    def test_loads_without_exceptions(self, loaded):
        assert not loaded.exception

    def test_renders_every_section(self, loaded):
        headings = [s.value for s in loaded.subheader]
        assert headings == ["Overview", "Chapters", "Quiz", "Revise one section", "Copy or download"]

    def test_detection_line_reports_webvtt_and_cues(self, loaded):
        assert "WebVTT" in captions(loaded)
        assert "12 cues" in captions(loaded)
        assert "timestamps available" in captions(loaded)

    def test_pre_generated_label_is_shown(self, loaded):
        infos = " ".join(i.value for i in loaded.info)
        assert "Pre-generated with this app on" in infos
        assert "No API call was made just now." in infos

    def test_validation_summary_is_shown(self, loaded):
        assert "Kept" in captions(loaded)

    def test_chapter_timestamps_rendered(self, loaded):
        body = " ".join(m.value for m in loaded.markdown)
        assert "[00:" in body

    def test_revision_controls_present(self, loaded):
        assert loaded.selectbox
        labels = [b.label for b in loaded.button]
        assert "Revise this section" in labels
        assert any(label.startswith("Undo last change") for label in labels)

    def test_undo_is_disabled_before_any_revision(self, loaded):
        undo = [b for b in loaded.button if b.label.startswith("Undo last change")][0]
        assert undo.disabled is True

    def test_revise_is_disabled_without_a_key(self, loaded):
        revise = button(loaded, "Revise this section")
        assert revise.disabled is True

    def test_download_buttons_offered(self, loaded):
        labels = [b.label for b in loaded.download_button]
        assert "Download Markdown" in labels
        assert "Download JSON" in labels

    def test_markdown_is_shown_in_a_copyable_block(self, loaded):
        assert loaded.code
        assert "## Summary" in loaded.code[0].value


@needs_sample
class TestQuizInteraction:
    @pytest.fixture
    def loaded(self, app) -> AppTest:
        button(app, "Load example episode").click().run()
        return app

    def test_unanswered_question_is_neutral_and_still_shows_the_answer(self, loaded):
        button(loaded, "Check answers").click()
        loaded.run()
        body = " ".join(m.value for m in loaded.markdown)
        assert "Not answered" in body
        assert "the answer is" in body
        # Not answering is not a mistake, so it must not be styled as a warning or error.
        assert not any("Not answered" in w.value for w in loaded.warning)
        assert not any("Not answered" in e.value for e in loaded.error)

    def test_correct_answer_is_reported(self, loaded):
        # A widget inside st.form only commits on submit, so the value and the click
        # have to happen in the same run cycle.
        correct = loaded.session_state["result"].quiz[0].correct_index
        loaded.radio[0].set_value(correct)
        button(loaded, "Check answers").click()
        loaded.run()
        assert any("Correct" in s.value for s in loaded.success)

    def test_wrong_answer_reveals_the_answer(self, loaded):
        question = loaded.session_state["result"].quiz[0]
        wrong = (question.correct_index + 1) % len(question.options)
        loaded.radio[0].set_value(wrong)
        button(loaded, "Check answers").click()
        loaded.run()
        assert any("Not quite" in e.value for e in loaded.error)
