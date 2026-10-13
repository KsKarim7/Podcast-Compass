"""The provider boundary, driven entirely by fakes.

The fake exception classes below copy the shapes observed in google-genai 2.29.0: a
status-carrying error exposes `status_code` and `message`, and a timeout exposes
`status_code` set to None with an httpx error as its __cause__.
"""

import inspect
import json
import sys

import pytest

from podcast_compass import config, llm, messages
from podcast_compass.llm import LlmError, classify, generate
from podcast_compass.models import Overview, OverviewOnly


class FakeStatusError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class APITimeoutError(Exception):
    """Same class name as the SDK's, which is what the classifier keys on."""

    def __init__(self) -> None:
        super().__init__("timed out")
        self.status_code = None


class FakeHttpxError(Exception):
    pass


FakeHttpxError.__module__ = "httpx"


VALID = json.dumps(
    {
        "overview": {
            "summary": "A short summary.",
            "themes": ["timing", "temperature"],
            "takeaways": [
                {
                    "text": "Timing matters more than the recipe.",
                    "evidence": {"segment_id": "S001", "quote": "the timing, not the recipe"},
                }
            ],
        }
    }
)


class RecordingCall:
    """A fake ModelCall that returns scripted results and records what it was asked."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, *, model, system_instruction, prompt, schema):
        # Record every argument, including system_instruction: anything the fake drops
        # is an argument no test can check.
        self.calls.append(
            {
                "model": model,
                "system_instruction": system_instruction,
                "prompt": prompt,
                "schema": schema,
            }
        )
        result = self.results.pop(0) if self.results else VALID
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def models_used(self):
        return [c["model"] for c in self.calls]


class TestClassify:
    def test_invalid_key_on_400_is_a_config_error(self):
        failure = classify(FakeStatusError(400, "API key not valid. Please pass a valid API key."))
        assert failure.kind == "config"
        assert failure.use_fallback is False

    def test_plain_400_is_not_treated_as_a_key_problem(self):
        failure = classify(FakeStatusError(400, "Invalid JSON payload"))
        assert failure.kind == "bad_request"
        assert failure.use_fallback is False

    def test_401_is_a_config_error(self):
        assert classify(FakeStatusError(401, "unauthenticated")).kind == "config"

    def test_403_is_a_config_error(self):
        assert classify(FakeStatusError(403, "permission denied")).kind == "config"

    def test_404_falls_back(self):
        failure = classify(FakeStatusError(404, "model not found"))
        assert failure.kind == "not_found"
        assert failure.use_fallback is True

    def test_429_falls_back(self):
        failure = classify(FakeStatusError(429, "rate_limit_exceeded"))
        assert failure.kind == "quota"
        assert failure.use_fallback is True

    @pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
    def test_transient_statuses_fall_back(self, status):
        failure = classify(FakeStatusError(status, "busy"))
        assert failure.kind == "transient"
        assert failure.use_fallback is True

    def test_timeout_has_a_none_status_code_and_still_falls_back(self):
        exc = APITimeoutError()
        # The trap: hasattr is True while the value is None.
        assert hasattr(exc, "status_code")
        assert exc.status_code is None
        failure = classify(exc)
        assert failure.kind == "timeout"
        assert failure.use_fallback is True

    def test_httpx_cause_recognised_as_transient(self):
        exc = Exception("wrapped")
        exc.__cause__ = FakeHttpxError("connect error")
        assert classify(exc).kind == "timeout"

    def test_unrecognised_exception_is_not_retried(self):
        failure = classify(RuntimeError("something odd"))
        assert failure.kind == "unknown"
        assert failure.use_fallback is False

    def test_messages_never_leak_internals(self):
        # The placeholder is deliberately not key-shaped: a realistic-looking fake would
        # show up in the pre-submission history scan for leaked credentials.
        leaked = "REDACTED-PLACEHOLDER-VALUE"
        failure = classify(FakeStatusError(400, f"API key not valid: {leaked}"))
        assert leaked not in failure.user_message
        assert failure.user_message == messages.REJECTED_KEY


class TestGenerate:
    def test_happy_path_uses_primary_only(self):
        call = RecordingCall(VALID)
        parsed, outcome = generate(call, "prompt", OverviewOnly)
        assert isinstance(parsed.overview, Overview)
        assert call.models_used == [config.PRIMARY_MODEL]
        assert outcome.used_fallback is False
        assert outcome.repaired is False

    def test_schema_sent_is_the_models_json_schema(self):
        call = RecordingCall(VALID)
        generate(call, "prompt", OverviewOnly)
        assert call.calls[0]["schema"] == OverviewOnly.model_json_schema()

    def test_fallback_used_once_on_transient_failure(self):
        call = RecordingCall(FakeStatusError(503, "busy"), VALID)
        _, outcome = generate(call, "prompt", OverviewOnly)
        assert call.models_used == [config.PRIMARY_MODEL, config.FALLBACK_MODEL]
        assert outcome.used_fallback is True

    def test_fallback_not_used_for_a_config_error(self):
        call = RecordingCall(FakeStatusError(403, "denied"))
        with pytest.raises(LlmError) as excinfo:
            generate(call, "prompt", OverviewOnly)
        assert excinfo.value.failure.kind == "config"
        assert len(call.calls) == 1

    def test_fallback_failure_is_not_retried_again(self):
        call = RecordingCall(FakeStatusError(503, "busy"), FakeStatusError(503, "busy"))
        with pytest.raises(LlmError):
            generate(call, "prompt", OverviewOnly)
        assert len(call.calls) == 2

    def test_repair_retry_fires_once_and_succeeds(self):
        call = RecordingCall("not json at all", VALID)
        parsed, outcome = generate(call, "prompt", OverviewOnly)
        assert outcome.repaired is True
        assert len(call.calls) == 2
        assert call.calls[1]["prompt"].startswith("Your previous output was not valid JSON")

    def test_repair_retry_only_once(self):
        call = RecordingCall("nope", "still nope")
        with pytest.raises(LlmError) as excinfo:
            generate(call, "prompt", OverviewOnly)
        assert excinfo.value.failure.kind == "malformed"
        assert len(call.calls) == 2

    def test_repair_uses_the_same_model_the_output_came_from(self):
        call = RecordingCall(FakeStatusError(503, "busy"), "bad json", VALID)
        _, outcome = generate(call, "prompt", OverviewOnly)
        assert call.models_used == [
            config.PRIMARY_MODEL,
            config.FALLBACK_MODEL,
            config.FALLBACK_MODEL,
        ]
        assert outcome.used_fallback is True
        assert outcome.repaired is True

    def test_repair_skipped_once_the_budget_is_spent(self):
        call = RecordingCall("bad json", VALID)
        ticks = iter([0.0, config.REPAIR_BUDGET_S + 1])

        with pytest.raises(LlmError) as excinfo:
            generate(call, "prompt", OverviewOnly, clock=lambda: next(ticks))
        assert excinfo.value.failure.kind == "malformed"
        assert len(call.calls) == 1

    def test_schema_valid_json_but_wrong_shape_triggers_repair(self):
        call = RecordingCall(json.dumps({"overview": {"summary": "x"}}), VALID)
        _, outcome = generate(call, "prompt", OverviewOnly)
        assert outcome.repaired is True

    def test_elapsed_ms_recorded(self):
        call = RecordingCall(VALID)
        ticks = iter([10.0, 11.5])
        _, outcome = generate(call, "prompt", OverviewOnly, clock=lambda: next(ticks))
        assert outcome.elapsed_ms == pytest.approx(1500.0)

    def test_user_message_is_present_for_every_failure_kind(self):
        for exc in (
            FakeStatusError(400, "API key not valid"),
            FakeStatusError(429, "quota"),
            FakeStatusError(503, "busy"),
            APITimeoutError(),
            RuntimeError("odd"),
        ):
            failure = classify(exc)
            assert failure.user_message
            assert not failure.user_message.endswith(":")


class TestSdkStaysOutOfTheTests:
    def test_google_genai_is_never_imported(self):
        # build_sdk_call imports google-genai inside the function body, so the whole
        # pipeline is exercisable with no SDK and no key. If this starts failing,
        # something has added a module-level import of the provider.
        generate(RecordingCall(VALID), "prompt", OverviewOnly)
        assert "google.genai" not in sys.modules

    def test_no_sdk_import_outside_the_adapter(self):
        source = inspect.getsource(llm)
        before_adapter = source[: source.index("def build_sdk_call")]
        imports = [
            line.strip()
            for line in before_adapter.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        assert not [line for line in imports if "google" in line], imports
