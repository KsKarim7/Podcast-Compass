"""Stand-ins for the two provider calls, so retrieval and answering run with no network.

The fake embedder is a bag of words hashed into a small vector. It is crude, but texts that
share words point in similar directions, which is all the retrieval tests need, and it is
deterministic, so a test that passes once always passes.
"""

from __future__ import annotations

import hashlib
import re

from podcast_compass.models import Answer, Evidence

DIMENSIONS = 64


def _vector(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z']+", text.lower()):
        bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS
        vector[bucket] += 1.0
    return vector


class FakeEmbedder:
    """Records every request: its task type and how many texts it carried."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    def __call__(self, *, texts: list[str], task_type: str) -> list[list[float]]:
        self.requests.append((task_type, len(texts)))
        return [_vector(text) for text in texts]


class FakeModel:
    """Returns a fixed answer and keeps the prompts it was given."""

    def __init__(self, answer: Answer | str) -> None:
        self.payload = answer if isinstance(answer, str) else answer.model_dump_json()
        self.prompts: list[str] = []
        self.system_instructions: list[str] = []

    def __call__(self, *, model, system_instruction, prompt, schema) -> str:
        self.prompts.append(prompt)
        self.system_instructions.append(system_instruction)
        return self.payload


def answer(text: str, *citations: tuple[str, str], supported: bool = True) -> Answer:
    return Answer(
        supported=supported,
        answer=text,
        citations=[Evidence(segment_id=sid, quote=quote) for sid, quote in citations],
    )
