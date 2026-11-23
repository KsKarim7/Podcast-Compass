"""The FAISS index: normalisation, batching, request counting and search."""

import numpy as np
import pytest

from podcast_compass import config, rag, sample
from podcast_compass.llm import LlmError
from podcast_compass.parsing import parse_transcript
from podcast_compass.segments import Segment, build_segments
from tests.fake_providers import DIMENSIONS, FakeEmbedder


@pytest.fixture
def segments():
    return build_segments(parse_transcript(sample.load_transcript()))


def many_segments(count: int) -> list[Segment]:
    return [Segment(f"S{n:03d}", f"segment number {n} talks about topic {n}", None, None)
            for n in range(1, count + 1)]


class TestNormalise:
    def test_rows_have_length_one(self):
        matrix = rag.normalise([[3.0, 4.0], [0.0, 2.0]])
        assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)
        assert matrix.dtype == np.float32

    def test_a_zero_vector_stays_zero_instead_of_dividing_by_zero(self):
        matrix = rag.normalise([[0.0, 0.0], [1.0, 0.0]])
        assert np.all(matrix[0] == 0)
        assert not np.isnan(matrix).any()

    def test_inner_product_of_normalised_vectors_is_cosine(self):
        a, b = [1.0, 2.0, 3.0], [2.0, 1.0, 0.5]
        cosine = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        matrix = rag.normalise([a, b])
        assert float(matrix[0] @ matrix[1]) == pytest.approx(cosine, rel=1e-6)

    def test_empty_input_is_rejected(self):
        with pytest.raises(ValueError):
            rag.normalise([])


class TestBuildIndex:
    def test_every_segment_is_indexed_once(self, segments):
        embedder = FakeEmbedder()
        index = rag.build_index(segments, embedder)
        assert index.index.ntotal == len(segments)
        assert index.index.d == DIMENSIONS
        assert index.segment_ids == [segment.id for segment in segments]

    def test_documents_are_embedded_as_documents(self, segments):
        embedder = FakeEmbedder()
        rag.build_index(segments, embedder)
        assert {task for task, _ in embedder.requests} == {rag.DOCUMENT_TASK}

    def test_a_long_transcript_is_embedded_in_batches(self):
        embedder = FakeEmbedder()
        count = config.EMBED_BATCH_SIZE * 2 + 50
        index = rag.build_index(many_segments(count), embedder)
        assert [size for _, size in embedder.requests] == [
            config.EMBED_BATCH_SIZE,
            config.EMBED_BATCH_SIZE,
            50,
        ]
        assert index.requests == len(embedder.requests) == 3

    def test_requests_to_index_matches_the_batching(self):
        assert rag.requests_to_index(1) == 1
        assert rag.requests_to_index(config.EMBED_BATCH_SIZE) == 1
        assert rag.requests_to_index(config.EMBED_BATCH_SIZE + 1) == 2

    def test_the_key_changes_with_the_text(self, segments):
        changed = [Segment(s.id, s.text + " extra", s.start, s.end) for s in segments]
        assert rag.transcript_key(segments) == rag.transcript_key(list(segments))
        assert rag.transcript_key(segments) != rag.transcript_key(changed)

    def test_a_short_embedding_response_is_an_error(self, segments):
        def short(*, texts, task_type):
            return [[1.0, 0.0]]

        with pytest.raises(LlmError):
            rag.build_index(segments, short)


class TestSearch:
    def test_finds_the_segment_about_the_question(self, segments):
        embedder = FakeEmbedder()
        index = rag.build_index(segments, embedder)
        hits = rag.search(index, "equipment smoker veil tool", embedder, 1)
        assert hits[0].segment_id == "S002"

    def test_results_are_best_first(self, segments):
        embedder = FakeEmbedder()
        index = rag.build_index(segments, embedder)
        hits = rag.search(index, "water for the colony in a city", embedder, 3)
        scores = [hit.score for hit in hits]
        assert scores == sorted(scores, reverse=True)

    def test_k_is_capped_at_the_number_of_segments(self, segments):
        embedder = FakeEmbedder()
        index = rag.build_index(segments, embedder)
        assert len(rag.search(index, "honey", embedder, 50)) == len(segments)

    def test_the_question_is_embedded_as_a_query_in_one_request(self, segments):
        embedder = FakeEmbedder()
        index = rag.build_index(segments, embedder)
        before = len(embedder.requests)
        rag.search(index, "honey", embedder, 2)
        assert embedder.requests[before:] == [(rag.QUERY_TASK, 1)]

    def test_a_query_of_another_size_is_refused(self, segments):
        index = rag.build_index(segments, FakeEmbedder())

        def other_model(*, texts, task_type):
            return [[1.0] * (DIMENSIONS + 1) for _ in texts]

        with pytest.raises(ValueError, match="dimensions"):
            rag.search(index, "honey", other_model, 2)

    def test_scores_are_cosine_similarities(self, segments):
        embedder = FakeEmbedder()
        index = rag.build_index(segments, embedder)
        for hit in rag.search(index, "honey in the first year", embedder, 3):
            assert -1.0 - 1e-5 <= hit.score <= 1.0 + 1e-5
