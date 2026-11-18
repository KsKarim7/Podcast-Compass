"""The embeddings call in llm.py: request shape, failure classification, response checks."""

import sys

import pytest

from podcast_compass import llm, messages


class StatusError(Exception):
    """Shaped like the private SDK errors: the HTTP status as status_code."""

    def __init__(self, status_code: int, message: str = "error") -> None:
        super().__init__(message)
        self.status_code = status_code


class DocumentedError(Exception):
    """Shaped like google.genai.errors.APIError: the HTTP status as code."""

    def __init__(self, code: int, message: str = "error") -> None:
        super().__init__(message)
        self.code = code


class APITimeoutError(Exception):
    pass


def raising(exc: Exception):
    def call(*, texts, task_type):
        raise exc

    return call


class TestEmbed:
    def test_passes_the_texts_and_task_through(self):
        seen = {}

        def call(*, texts, task_type):
            seen.update(texts=texts, task_type=task_type)
            return [[1.0, 0.0] for _ in texts]

        vectors = llm.embed(call, ["a", "b"], "RETRIEVAL_DOCUMENT")
        assert vectors == [[1.0, 0.0], [1.0, 0.0]]
        assert seen == {"texts": ["a", "b"], "task_type": "RETRIEVAL_DOCUMENT"}

    def test_a_missing_vector_is_an_error_not_a_misaligned_index(self):
        def call(*, texts, task_type):
            return [[1.0]]

        with pytest.raises(llm.LlmError) as caught:
            llm.embed(call, ["a", "b"], "RETRIEVAL_DOCUMENT")
        assert caught.value.user_message == messages.UNKNOWN

    @pytest.mark.parametrize("status", [503, 500, 404, 408])
    def test_busy_or_missing_model_gets_the_search_message(self, status):
        with pytest.raises(llm.LlmError) as caught:
            llm.embed(raising(StatusError(status)), ["a"], "RETRIEVAL_QUERY")
        assert caught.value.user_message == messages.SEARCH_UNAVAILABLE

    def test_a_timeout_gets_the_search_message(self):
        with pytest.raises(llm.LlmError) as caught:
            llm.embed(raising(APITimeoutError("slow")), ["a"], "RETRIEVAL_QUERY")
        assert caught.value.user_message == messages.SEARCH_UNAVAILABLE

    def test_quota_keeps_the_quota_message(self):
        with pytest.raises(llm.LlmError) as caught:
            llm.embed(raising(StatusError(429)), ["a"], "RETRIEVAL_QUERY")
        assert caught.value.user_message == messages.QUOTA_EXHAUSTED

    def test_the_documented_error_class_is_classified_by_its_code(self):
        bad_key = DocumentedError(400, "API key not valid. Please pass a valid API key.")
        with pytest.raises(llm.LlmError) as caught:
            llm.embed(raising(bad_key), ["a"], "RETRIEVAL_QUERY")
        assert caught.value.failure.kind == "config"
        assert caught.value.user_message == messages.REJECTED_KEY

    def test_a_non_numeric_code_is_ignored(self):
        odd = DocumentedError(0)
        odd.code = "UNAVAILABLE"
        assert llm.classify(odd).kind == "unknown"


class TestLaziness:
    def test_the_sdk_is_not_imported_by_the_embedding_path(self):
        llm.embed(lambda *, texts, task_type: [[1.0]], ["a"], "RETRIEVAL_QUERY")
        assert "google.genai" not in sys.modules
