"""Retrieval for "Ask the podcast": embed the segments once, then find the closest ones to
a question.

FAISS's IndexFlatIP scores every stored vector against the query by inner product. For
vectors scaled to length 1 the inner product is the cosine similarity, so normalising
every vector first turns it into a cosine search. "Flat" means it compares against all of
them exactly, with no approximation, which is the right choice for a few hundred segments.

The segments being searched are the same numbered segments every citation refers to, so a
search result is always a real segment id with its real text.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import faiss
import numpy as np

from . import config
from .llm import EmbedCall, embed
from .segments import Segment

DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
QUERY_TASK = "RETRIEVAL_QUERY"


def transcript_key(segments: list[Segment]) -> str:
    """Identifies a transcript by its content, so an index is reused only for the same one."""
    digest = hashlib.sha256()
    for segment in segments:
        digest.update(segment.id.encode())
        digest.update(b"\0")
        digest.update(segment.text.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def normalise(vectors: list[list[float]]) -> np.ndarray:
    """Scale each row to length 1, as float32, which is what FAISS stores."""
    matrix = np.asarray(vectors, dtype="float32")
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError(f"expected a list of equal-length vectors, got shape {matrix.shape}")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # An all-zero vector stays zero rather than dividing by zero; it matches nothing.
    norms[norms == 0] = 1.0
    return matrix / norms


def requests_to_index(segment_count: int) -> int:
    return math.ceil(segment_count / config.EMBED_BATCH_SIZE)


@dataclass
class SegmentIndex:
    key: str
    segment_ids: list[str]
    index: faiss.Index
    requests: int


@dataclass(frozen=True)
class Hit:
    segment_id: str
    score: float


def build_index(segments: list[Segment], call: EmbedCall) -> SegmentIndex:
    """Embed every segment, in batches, into one exact cosine index."""
    vectors: list[list[float]] = []
    for start in range(0, len(segments), config.EMBED_BATCH_SIZE):
        batch = segments[start : start + config.EMBED_BATCH_SIZE]
        vectors.extend(embed(call, [segment.text for segment in batch], DOCUMENT_TASK))

    matrix = normalise(vectors)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)
    return SegmentIndex(
        key=transcript_key(segments),
        segment_ids=[segment.id for segment in segments],
        index=index,
        requests=requests_to_index(len(segments)),
    )


def search(index: SegmentIndex, query: str, call: EmbedCall, k: int) -> list[Hit]:
    """The k segments closest to the query, best first. Costs one request."""
    vector = normalise(embed(call, [query], QUERY_TASK))
    if vector.shape[1] != index.index.d:
        raise ValueError(
            f"query has {vector.shape[1]} dimensions, the index has {index.index.d}"
        )
    k = min(k, index.index.ntotal)
    if k <= 0:
        return []
    scores, positions = index.index.search(vector, k)
    return [
        Hit(index.segment_ids[position], float(score))
        for score, position in zip(scores[0], positions[0], strict=True)
        if position >= 0
    ]
