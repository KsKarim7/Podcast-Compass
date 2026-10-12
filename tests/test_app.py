"""The app script itself, run through Streamlit's AppTest.

This catches what unit tests cannot: an invalid widget argument, a state key read before
it is set, or an exception on first load. No API call is made anywhere here — AppTest has
no secrets file, so the key lookup returns None and the generate path stops at that
boundary, which is itself worth asserting.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from podcast_compass import config, messages, quota, render, sample

# AppTest resolves a relative path against the file that calls it, which would look
# inside tests/, so the path is built from the repo root.
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

needs_sample = pytest.mark.skipif(
    not sample.result_exists(),
    reason="run tools/generate_sample.py to create samples/sample_results.json",
)


@pytest.fixture(autouse=True)
def never_reach_the_provider(monkeypatch):
    """Belt and braces: fail loudly instead of spending a real request.

    A local .streamlit/secrets.toml is visible to AppTest, so without this a test that
    clicks Generate with valid input would make a real API call on a developer machine
    and quietly spend free-tier quota. The fixture patches the only door to the SDK;
    the blanked key below is the second, independent guard.
    """

    def refuse(*args, **kwargs):
        raise AssertionError(
            "an app test tried to build a real SDK client; tests must never call the provider"
        )

    monkeypatch.setattr("podcast_compass.llm.build_sdk_call", refuse)


def fresh(key: str = "") -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    # Overrides any real secrets file, so behaviour does not depend on the machine.
    at.secrets["GEMINI_API_KEY"] = key
    return at


@pytest.fixture
def app() -> AppTest:
    at = fresh()
    at.run()
    return at


@pytest.fixture
def keyed_app() -> AppTest:
    """A configured key, for checking enabled state only. Never clicks Generate."""
    at = fresh("dummy-key-never-used")
    at.run()
    return at


def button(at: AppTest, label: str):
    for candidate in at.button:
        if candidate.label == label:
            return candidate
    raise AssertionError(f"no button labelled {label!r}; found {[b.label for b in at.button]}")


def submit_text(at: AppTest, text: str, label: str = "Generate") -> AppTest:
    """One browser click: set the form value and press, with no run in between."""
    at.text_area[0].set_value(text)
    for candidate in at.button:
        if candidate.label == label:
            candidate.click()
            return at.run()
    raise AssertionError(f"no button labelled {label!r}")


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
        button(app, "Generate").click()
        app.run()
        assert not app.exception
        assert "Paste a transcript or upload a file first." in errors(app)

    def test_short_transcript_is_rejected_with_the_real_count(self, app):
        submit_text(app, "too short")
        assert "9 characters" in errors(app)

    def test_oversized_transcript_is_rejected_with_the_real_count(self, app):
        submit_text(app, "x" * (config.MAX_CHARS + 5))
        assert f"{config.MAX_CHARS + 5:,} characters" in errors(app)

    def test_valid_input_is_parsed_then_stops_at_the_missing_key(self, app):
        submit_text(app, "fermentation depends on temperature. " * 20)
        assert not app.exception
        # Detection is still reported, so the user learns about their file either way.
        assert "plain text" in captions(app)
        assert "no timestamps" in captions(app)
        assert "not configured with an API key" in errors(app)

    def test_one_submit_is_enough_after_typing(self, app):
        """Regression: a free-standing text_area needed two clicks.

        The first click only blurred the field and committed its value, so the button
        press was lost. Inside a form the value and the press arrive together. AppTest
        reproduces this faithfully: setting the value and pressing in one run cycle is
        exactly one browser click, and an intervening run() is a second one.
        """
        app.text_area[0].set_value("too short")
        button(app, "Generate").click()
        app.run()
        # One cycle produced the verdict; no second press was needed.
        assert "9 characters" in errors(app)


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


class TestQuotaInTheInterface:
    def test_allowance_is_shown_up_front(self, app):
        assert "10 of 10 generations left in this session" in captions(app)
        assert f"of {quota.MAX_DAILY_REQUESTS} requests left today" in captions(app)

    def test_limitation_is_admitted_in_the_interface(self, app):
        # The caveat has to be visible to users, not only in the README.
        body = " ".join(m.value for m in app.markdown)
        assert "not a hard limit" in body or "not a hard limit" in str(app.expander)

    def test_generate_is_enabled_when_a_key_is_configured(self, keyed_app):
        assert button(keyed_app, "Generate").disabled is False
        assert "not configured with an API key" not in captions(keyed_app)

    def test_session_cap_blocks_without_calling_the_provider(self, keyed_app):
        # Pre-spend the session allowance, then try again. The autouse fixture would
        # fail this test if the guard let the call through.
        keyed_app.session_state["usage"] = quota.SessionUsage(
            actions=quota.MAX_SESSION_ACTIONS, last_action_at=None
        )
        submit_text(keyed_app, "fermentation depends on temperature. " * 20)
        assert not keyed_app.exception
        assert "this session" in errors(keyed_app)

    def test_spacing_rule_blocks_a_rapid_second_action(self, keyed_app):
        import time as _time

        keyed_app.session_state["usage"] = quota.SessionUsage(
            actions=1, last_action_at=_time.monotonic()
        )
        submit_text(keyed_app, "fermentation depends on temperature. " * 20)
        assert messages.TOO_SOON in errors(keyed_app)


class TestTheGuardItself:
    def test_build_sdk_call_is_patched_in_these_tests(self, app):
        # Proves the autouse fixture is active: if it ever stops working, this fails
        # rather than a later test quietly spending a real request.
        from podcast_compass import llm

        with pytest.raises(AssertionError, match="never call the provider"):
            llm.build_sdk_call("dummy")

    def test_the_key_is_blanked_regardless_of_a_local_secrets_file(self, app):
        assert app.secrets["GEMINI_API_KEY"] == ""
