"""Ask the podcast through the interface, with both provider calls replaced by fakes.

Driven through AppTest rather than by importing app.py, for the reason given in
test_errors.py: importing the script creates a second Streamlit context.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from podcast_compass import messages, quota, rag, sample
from tests.fake_providers import FakeEmbedder, answer

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

pytestmark = pytest.mark.skipif(
    not sample.result_exists(),
    reason="run tools/generate_sample.py to create samples/sample_results.json",
)

EQUIPMENT = ("S002", "You need a hive, a veil, a smoker and a hive tool.")


@pytest.fixture(autouse=True)
def never_reach_the_provider(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(
            "an app test tried to build a real SDK client; tests must never call the provider"
        )

    monkeypatch.setattr("podcast_compass.llm.build_sdk_call", refuse)
    monkeypatch.setattr("podcast_compass.llm.build_sdk_embedder", refuse)


def fake_providers(monkeypatch, reply) -> FakeEmbedder:
    payload = reply.model_dump_json()
    embedder = FakeEmbedder()
    monkeypatch.setattr(
        "podcast_compass.llm.build_sdk_call", lambda api_key: (lambda **kwargs: payload)
    )
    monkeypatch.setattr("podcast_compass.llm.build_sdk_embedder", lambda api_key: embedder)
    return embedder


def press(at: AppTest, label: str) -> AppTest:
    for candidate in at.button:
        if candidate.label == label:
            candidate.click()
            return at.run()
    raise AssertionError(f"no button labelled {label!r}; found {[b.label for b in at.button]}")


def loaded(key: str = "dummy-key-never-used") -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.secrets["GEMINI_API_KEY"] = key
    at.run()
    return press(at, "Load example episode")


def ask(at: AppTest, question: str) -> AppTest:
    """One browser click: the question and the press arrive together, as in a form."""
    at.text_input(key="question").set_value(question)
    return press(at, "Ask")


def text_of(elements) -> str:
    return " ".join(str(element.value) for element in elements)


class TestAskInTheInterface:
    def test_the_section_is_shown_with_a_result(self):
        at = loaded()
        assert "Ask the podcast" in text_of(at.subheader)

    def test_ask_is_disabled_without_a_key(self):
        at = loaded(key="")
        button = next(b for b in at.button if b.label == "Ask")
        assert button.disabled

    def test_a_verified_answer_is_shown_with_its_quote_and_cue_time(self, monkeypatch):
        fake_providers(monkeypatch, answer("A hive, a veil, a smoker and a hive tool.", EQUIPMENT))
        at = ask(loaded(), "What equipment do you need?")
        assert not at.exception
        assert "A hive, a veil, a smoker and a hive tool." in text_of(at.markdown)
        assert '[00:01:10] S002: "You need a hive' in text_of(at.caption)

    def test_an_unverifiable_answer_becomes_not_in_the_transcript(self, monkeypatch):
        invented = ("S002", "the host recommends a full protective suit and gloves")
        fake_providers(monkeypatch, answer("Buy a full suit.", invented))
        at = ask(loaded(), "What should I wear?")
        assert messages.NOT_IN_TRANSCRIPT in text_of(at.info)
        assert "Buy a full suit." not in text_of(at.markdown)

    def test_an_empty_question_is_refused_without_a_request(self):
        # The autouse guard would fail this test if any provider client were built.
        at = ask(loaded(), "   ")
        assert messages.EMPTY_QUESTION in text_of(at.error)

    def test_the_index_is_built_once_per_session(self, monkeypatch):
        monkeypatch.setattr(quota, "MIN_SECONDS_BETWEEN_ACTIONS", 0.0)
        embedder = fake_providers(monkeypatch, answer("A hive and a veil.", EQUIPMENT))
        at = ask(loaded(), "What equipment do you need?")
        ask(at, "And the smoker?")
        tasks = [task for task, _ in embedder.requests]
        assert tasks.count(rag.DOCUMENT_TASK) == 1
        assert tasks.count(rag.QUERY_TASK) == 2

    def test_loading_another_transcript_clears_the_answer_and_the_index(self, monkeypatch):
        fake_providers(monkeypatch, answer("A hive, a veil, a smoker and a hive tool.", EQUIPMENT))
        at = ask(loaded(), "What equipment do you need?")
        press(at, "Load example episode")
        assert "A hive, a veil, a smoker and a hive tool." not in text_of(at.markdown)
        assert at.session_state["rag_index"] is None
