"""One opt-in test that proves a failure path against the real SDK, not a fake.

Everything else in the suite drives `llm.generate` with fakes shaped like the exceptions
we observed in google-genai 2.29.0. That is fast and needs no credentials, but it would
keep passing if the real SDK changed shape. This test closes that gap for the one failure
we can trigger without a valid key or any quota: an invalid key.

    RUN_LIVE_TESTS=1 python -m pytest tests/test_live_sdk.py -v

It makes one real HTTPS request with the literal key "invalid-key-for-test", so it spends
no free-tier quota and needs no secret.
"""

import os

import pytest

from podcast_compass import config, llm
from podcast_compass.models import OverviewOnly

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="set RUN_LIVE_TESTS=1 to run; makes one real network call with an invalid key",
)

INVALID_KEY = "invalid-key-for-test"


def test_real_sdk_invalid_key_maps_to_a_config_failure():
    call = llm.build_sdk_call(INVALID_KEY)

    try:
        call(
            model=config.PRIMARY_MODEL,
            system_instruction="You are terse.",
            prompt="hello",
            schema=OverviewOnly.model_json_schema(),
        )
    except Exception as exc:  # noqa: BLE001 - the exception is the subject of the test
        observed = exc
    else:
        pytest.fail("expected the SDK to reject an invalid key")

    failure = llm.classify(observed)

    # Printed so the report can show what the real SDK produced.
    print(f"\n  class       : {type(observed).__name__}")
    print(f"  module      : {type(observed).__module__}")
    print(f"  status_code : {getattr(observed, 'status_code', 'ABSENT')!r}")
    print(f"  classified  : {failure.kind}")

    assert failure.kind == "config"
    assert failure.use_fallback is False
    assert failure.user_message == llm.CONFIG_MESSAGE

    # The two facts the classifier depends on, asserted against the real SDK.
    assert getattr(observed, "status_code", None) in (400, 401)
    assert not isinstance(observed, ValueError), (
        "a provider error must not be a ValueError, or it would be mistaken for a parse failure"
    )


def test_generate_surfaces_the_config_message_and_does_not_fall_back():
    call = llm.build_sdk_call(INVALID_KEY)
    attempts = []

    def counting_call(**kwargs):
        attempts.append(kwargs["model"])
        return call(**kwargs)

    with pytest.raises(llm.LlmError) as excinfo:
        llm.generate(counting_call, "hello", OverviewOnly)

    assert excinfo.value.user_message == llm.CONFIG_MESSAGE
    # A bad key is not worth trying on the fallback model.
    assert attempts == [config.PRIMARY_MODEL]
