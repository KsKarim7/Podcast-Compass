"""Every row of the error catalogue in docs/SPEC.md section 11.

One test per failure, each triggering it with a faked failure. No real API call is made
anywhere in this file: provider failures are fake exceptions shaped like the ones
google-genai 2.29.0 raises, and the app-level tests patch the SDK adapter.

The point of keeping these together is that a reviewer can read the catalogue and this
file side by side, and the table in the report is generated from real test names rather
than claimed.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from podcast_compass import config, messages, quota
from podcast_compass.grounding import GroundingRejected, validate
from podcast_compass.llm import LlmError, classify, generate
from podcast_compass.models import OverviewOnly, QuizOnly, replace_section
from podcast_compass.parsing import InputError, decode_bytes, parse_transcript
from podcast_compass.segments import build_segments, segment_lookup
from tests.fixtures import handwritten_result
from tests.test_llm import VALID, APITimeoutError, FakeStatusError, RecordingCall

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


# --------------------------------------------------------------------------- input


class TestInputFailures:
    def test_empty_input(self):
        with pytest.raises(InputError) as exc:
            parse_transcript("   \n\n  ")
        assert str(exc.value) == messages.EMPTY_INPUT

    def test_below_minimum_length(self):
        with pytest.raises(InputError) as exc:
            parse_transcript("far too short")
        assert str(exc.value) == messages.TOO_SHORT.format(count=13)

    def test_over_the_character_cap(self):
        oversized = "x" * (config.MAX_CHARS + 7)
        with pytest.raises(InputError) as exc:
            parse_transcript(oversized)
        assert str(exc.value) == messages.TOO_LONG.format(count=config.MAX_CHARS + 7)

    def test_undecodable_bytes(self):
        with pytest.raises(InputError) as exc:
            decode_bytes(b"ok\x81\x90bad")
        assert str(exc.value) == messages.BAD_ENCODING

    def test_damaged_cue_file(self):
        broken = "\n\n".join(f"{i} no arrow in this block" for i in range(20))
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nthe only good cue\n\n" + broken
        with pytest.raises(InputError) as exc:
            parse_transcript(text)
        assert str(exc.value) == messages.DAMAGED_CUES.format(good=1, total=21)

    def test_cue_file_with_nothing_readable(self):
        timings = "\n\n".join(
            f"{i}\n00:00:0{i % 10}.000 --> 00:00:0{(i + 1) % 10}.000" for i in range(30)
        )
        with pytest.raises(InputError) as exc:
            parse_transcript(f"WEBVTT\n\n{timings}")
        assert str(exc.value) == messages.NO_CUES_AT_ALL

    def test_cue_file_falls_back_to_plain_text(self):
        from podcast_compass import render

        body = "\n\n".join(["sourdough " * 30] * 3)
        parsed = parse_transcript(f"WEBVTT\n\n{body}")
        assert parsed.fell_back_to_text is True
        assert parsed.has_timestamps is False
        # The explanation has to reach the user, not just the parser.
        assert messages.NO_CUES_FELL_BACK in render.detection_line(parsed, 2)


# ----------------------------------------------------------------------- provider


class TestProviderFailures:
    def test_invalid_key_on_400(self):
        failure = classify(FakeStatusError(400, "API key not valid. Please pass a valid API key."))
        assert failure.user_message == messages.REJECTED_KEY

    def test_permission_denied_on_403(self):
        assert classify(FakeStatusError(403, "denied")).user_message == messages.REJECTED_KEY

    def test_quota_exhausted_on_429(self):
        assert classify(FakeStatusError(429, "quota")).user_message == messages.QUOTA_EXHAUSTED

    @pytest.mark.parametrize("status", [500, 503, 504])
    def test_model_busy_on_5xx(self, status):
        assert classify(FakeStatusError(status, "busy")).user_message == messages.MODEL_BUSY

    def test_timeout(self):
        assert classify(APITimeoutError()).user_message == messages.TIMED_OUT

    def test_unclassified_exception(self):
        assert classify(RuntimeError("something odd")).user_message == messages.UNKNOWN

    def test_malformed_output_after_the_repair_retry(self):
        call = RecordingCall("not json", "still not json")
        with pytest.raises(LlmError) as exc:
            generate(call, "prompt", OverviewOnly)
        assert exc.value.user_message == messages.MALFORMED_TWICE
        assert len(call.calls) == 2

    def test_both_models_failing_reports_the_fallback_condition(self):
        call = RecordingCall(FakeStatusError(503, "busy"), FakeStatusError(429, "quota"))
        with pytest.raises(LlmError) as exc:
            generate(call, "prompt", OverviewOnly)
        assert exc.value.user_message == messages.QUOTA_EXHAUSTED


# ------------------------------------------------------------------------ our caps


class TestCapFailures:
    def test_session_cap(self):
        counter = quota.DailyCounter(now=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
        session = quota.SessionUsage(actions=quota.MAX_SESSION_ACTIONS)
        decision = quota.check(session, counter, monotonic=10_000.0)
        assert decision.message == messages.SESSION_CAP.format(limit=quota.MAX_SESSION_ACTIONS)

    def test_daily_cap(self):
        spent = quota.DailyCounter(limit=2, now=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
        decision = quota.check(quota.SessionUsage(), spent, monotonic=100.0)
        assert decision.message == messages.DAILY_CAP.format(limit=2)

    def test_too_soon(self):
        counter = quota.DailyCounter(now=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
        session = quota.SessionUsage(actions=1, last_action_at=100.0)
        decision = quota.check(session, counter, monotonic=101.0)
        assert decision.message == messages.TOO_SOON


# ----------------------------------------------------------------------- grounding


class TestGroundingFailures:
    @pytest.fixture
    def lookup(self):
        from podcast_compass import sample

        segments = build_segments(parse_transcript(sample.load_transcript()))
        return segment_lookup(segments)

    def test_whole_result_rejected_when_nothing_verifies(self, lookup):
        raw = handwritten_result()
        broken = raw.model_copy(deep=True)
        for chapter in broken.chapters:
            chapter.evidence.quote = "words that appear nowhere in the transcript"
        with pytest.raises(GroundingRejected):
            validate(broken, lookup)

    def test_rejection_reason_is_recorded_for_the_log(self, lookup):
        raw = handwritten_result()
        broken = raw.model_copy(deep=True)
        broken.overview.summary = "  "
        with pytest.raises(GroundingRejected, match="summary was empty"):
            validate(broken, lookup)


# --------------------------------------------------------------- the app's own paths


class FakeUpload:
    """Enough of Streamlit's UploadedFile for the extension guard."""

    def __init__(self, name: str, data: bytes = b"x" * 400) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


@pytest.fixture(autouse=True)
def never_reach_the_provider(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a catalogue test must never call the provider")

    monkeypatch.setattr("podcast_compass.llm.build_sdk_call", refuse)


def fresh_app(key: str = "") -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.secrets["GEMINI_API_KEY"] = key
    return at


def errors(at: AppTest) -> str:
    return " ".join(e.value for e in at.error)


def click(at: AppTest, label: str) -> AppTest:
    for candidate in at.button:
        if candidate.label == label:
            return candidate.click().run()
    raise AssertionError(f"no button labelled {label!r}")


class TestAppLevelFailures:
    def test_nothing_submitted(self):
        at = fresh_app()
        at.run()
        click(at, "Generate")
        assert messages.NOTHING_SUBMITTED in errors(at)

    def test_missing_key(self):
        at = fresh_app()
        at.run()
        at.text_area[0].set_value("fermentation depends on temperature. " * 20).run()
        click(at, "Generate")
        assert messages.MISSING_KEY in errors(at)

    def test_unsupported_file_type(self):
        from app import read_input

        with pytest.raises(InputError) as exc:
            read_input("", FakeUpload("notes.pdf"))
        assert str(exc.value) == messages.UNSUPPORTED_FILE_TYPE.format(extension=".pdf")

    def test_allowed_file_type_passes_the_guard(self):
        from app import read_input

        text = read_input("", FakeUpload("episode.vtt", b"WEBVTT\n\n" + b"x" * 400))
        assert text.startswith("WEBVTT")

    def test_try_again_button_appears_with_an_error(self):
        at = fresh_app()
        at.run()
        click(at, "Generate")
        assert any(b.label == "Try again" for b in at.button)

    def test_try_again_clears_the_error(self):
        at = fresh_app()
        at.run()
        click(at, "Generate")
        assert errors(at)
        click(at, "Try again")
        assert not errors(at)


@pytest.mark.skipif(
    not __import__("podcast_compass.sample", fromlist=["x"]).result_exists(),
    reason="run tools/generate_sample.py to create samples/sample_results.json",
)
class TestFailedRevisionKeepsTheGoodResult:
    """The branch flagged while building the interface, now pinned down.

    Driven through the interface, not by calling app functions directly: importing
    app.py from a test creates a second Streamlit context with its own session state,
    so assertions would be reading different state from the one the code wrote to.

    The provider is replaced by a fake that returns whatever JSON the test wants, so the
    real generate(), store() and validate() all run with no network.
    """

    @staticmethod
    def _fake_provider(payload: str):
        def build(api_key):
            def call(**kwargs):
                return payload

            return call

        return build

    def _loaded(self, monkeypatch, payload: str) -> AppTest:
        monkeypatch.setattr(
            "podcast_compass.llm.build_sdk_call", self._fake_provider(payload)
        )
        at = fresh_app("dummy-key-never-used")
        at.run()
        click(at, "Load example episode")
        at.selectbox[0].set_value("quiz").run()
        return at

    @staticmethod
    def _broken_quiz_json() -> str:
        from podcast_compass import sample

        quiz = QuizOnly.model_validate(sample.load_bundle().result.model_dump())
        for question in quiz.quiz:
            question.evidence.quote = "nothing like this appears in the transcript"
        return quiz.model_dump_json()

    @staticmethod
    def _shorter_quiz_json() -> str:
        from podcast_compass import sample

        quiz = QuizOnly.model_validate(sample.load_bundle().result.model_dump())
        return QuizOnly(quiz=quiz.quiz[:2]).model_dump_json()

    def test_a_rejected_revision_keeps_the_previous_result(self, monkeypatch):
        at = self._loaded(monkeypatch, self._broken_quiz_json())
        before = at.session_state["result"]
        questions_before = len(before.quiz)

        click(at, "Revise this section")

        assert not at.exception
        assert messages.REVISION_REJECTED in errors(at)
        # The good result is still on screen, unchanged.
        assert len(at.session_state["result"].quiz) == questions_before
        assert at.session_state["result"].summary == before.summary

    def test_a_rejected_revision_does_not_offer_undo(self, monkeypatch):
        at = self._loaded(monkeypatch, self._broken_quiz_json())
        click(at, "Revise this section")

        assert at.session_state["previous"] == {}
        undo = [b for b in at.button if b.label.startswith("Undo last change")]
        assert undo and undo[0].disabled is True

    def test_an_accepted_revision_replaces_only_that_section(self, monkeypatch):
        at = self._loaded(monkeypatch, self._shorter_quiz_json())
        chapters_before = [c.chapter.title for c in at.session_state["result"].chapters]
        summary_before = at.session_state["result"].summary

        click(at, "Revise this section")

        assert not at.exception
        assert not errors(at)
        assert len(at.session_state["result"].quiz) == 2
        # Everything else is untouched, which is the brief's single-section requirement.
        assert [c.chapter.title for c in at.session_state["result"].chapters] == chapters_before
        assert at.session_state["result"].summary == summary_before

    def test_an_accepted_revision_offers_undo(self, monkeypatch):
        at = self._loaded(monkeypatch, self._shorter_quiz_json())
        click(at, "Revise this section")

        assert "quiz" in at.session_state["previous"]
        undo = [b for b in at.button if b.label.startswith("Undo last change")]
        assert undo and undo[0].disabled is False

    def test_undo_restores_the_original_without_a_further_call(self, monkeypatch):
        at = self._loaded(monkeypatch, self._shorter_quiz_json())
        original = len(at.session_state["result"].quiz)
        click(at, "Revise this section")
        assert len(at.session_state["result"].quiz) == 2

        # Any further provider call would return the shortened quiz again; undo must
        # not make one, so the count going back up proves it was a state swap.
        click(at, [b.label for b in at.button if b.label.startswith("Undo last change")][0])
        assert len(at.session_state["result"].quiz) == original


# ------------------------------------------------------------------ message hygiene


class TestMessageHygiene:
    def test_no_message_leaks_internals(self):
        forbidden = ("Traceback", "google.genai", "_gaos", "http://", "https://", "AQ.", "AIza")
        for name, text in messages.all_messages().items():
            for token in forbidden:
                assert token not in text, f"{name} leaks {token!r}"

    def test_every_message_is_a_sentence(self):
        for name, text in messages.all_messages().items():
            if "{" in text:
                continue
            assert text[0].isupper(), name
            assert text.rstrip().endswith((".", "!")), name

    def test_messages_that_mention_unavailability_point_at_the_example(self):
        for name in (
            "MISSING_KEY",
            "REJECTED_KEY",
            "QUOTA_EXHAUSTED",
            "SESSION_CAP",
            "DAILY_CAP",
        ):
            assert "example episode" in messages.all_messages()[name]

    def test_timeout_message_states_the_configured_timeout(self):
        assert str(config.REQUEST_TIMEOUT_MS // 1000) in messages.TIMED_OUT


class TestWholeResultRejectionInTheInterface:
    """A first generation that cannot be verified: message plus Try again, no retry."""

    @staticmethod
    def _fake_provider(payload: str):
        def build(api_key):
            def call(**kwargs):
                return payload

            return call

        return build

    @staticmethod
    def _ungrounded_result_json() -> str:
        raw = handwritten_result().model_copy(deep=True)
        for chapter in raw.chapters:
            chapter.evidence.quote = "nothing like this appears in the transcript"
        for question in raw.quiz:
            question.evidence.quote = "nothing like this appears in the transcript"
        for takeaway in raw.overview.takeaways:
            takeaway.evidence.quote = "nothing like this appears in the transcript"
        return raw.model_dump_json()

    def _generate(self, monkeypatch, calls: list) -> AppTest:
        payload = self._ungrounded_result_json()

        def build(api_key):
            def call(**kwargs):
                calls.append(kwargs["model"])
                return payload

            return call

        monkeypatch.setattr("podcast_compass.llm.build_sdk_call", build)
        at = fresh_app("dummy-key-never-used")
        at.run()
        at.text_area[0].set_value(
            __import__("podcast_compass.sample", fromlist=["x"]).load_transcript()
        ).run()
        click(at, "Generate")
        return at

    def test_shows_the_rejection_message(self, monkeypatch):
        at = self._generate(monkeypatch, [])
        assert not at.exception
        assert messages.GROUNDING_REJECTED in errors(at)

    def test_shows_a_try_again_button(self, monkeypatch):
        at = self._generate(monkeypatch, [])
        assert any(b.label == "Try again" for b in at.button)

    def test_no_result_is_shown(self, monkeypatch):
        at = self._generate(monkeypatch, [])
        assert at.session_state["result"] is None

    def test_does_not_retry_automatically(self, monkeypatch):
        calls: list = []
        self._generate(monkeypatch, calls)
        # One request only. A rejection is the user's decision to retry, not ours.
        assert len(calls) == 1, calls
