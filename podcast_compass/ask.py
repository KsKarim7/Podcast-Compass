"""Ask the podcast: retrieve the closest segments, answer from them only, verify the answer.

Used by the Streamlit app and by the MCP server, so both apply the same retrieval, the
same prompt-injection handling and the same citation checks.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config, messages, prompts
from .grounding import VerifiedAnswer, verify_answer
from .llm import EmbedCall, ModelCall, generate
from .models import Answer
from .parsing import InputError
from .quota import REQUESTS_PER_ACTION
from .rag import Hit, SegmentIndex, build_index, requests_to_index, search, transcript_key
from .segments import Segment, render_for_prompt, segment_lookup


@dataclass
class AskResult:
    answer: VerifiedAnswer
    hits: list[Hit]
    index: SegmentIndex
    requests: int


def clean_question(question: str) -> str:
    """Trimmed, capped and defused, exactly as it will appear in the prompt."""
    return prompts.sanitise_user_text(question, config.MAX_QUESTION_CHARS)


def index_is_current(index: SegmentIndex | None, segments: list[Segment]) -> bool:
    return index is not None and index.key == transcript_key(segments)


def worst_case_requests(index: SegmentIndex | None, segments: list[Segment]) -> int:
    """What one question can cost at most, so the caller can reserve it up front:
    building the index if it is not ready, one query embedding, then an answer that may
    need the fallback model and a repair retry."""
    building = 0 if index_is_current(index, segments) else requests_to_index(len(segments))
    return building + 1 + REQUESTS_PER_ACTION


def ask(
    question: str,
    segments: list[Segment],
    *,
    model_call: ModelCall,
    embed_call: EmbedCall,
    index: SegmentIndex | None = None,
    k: int = config.RETRIEVAL_TOP_K,
) -> AskResult:
    """Raises InputError for an empty question and LlmError for a provider failure."""
    cleaned = clean_question(question)
    if not cleaned:
        raise InputError(messages.EMPTY_QUESTION)

    requests = 0
    if not index_is_current(index, segments):
        index = build_index(segments, embed_call)
        requests += index.requests

    hits = search(index, cleaned, embed_call, k)
    requests += 1

    retrieved_ids = {hit.segment_id for hit in hits}
    # Shown to the model in transcript order rather than score order, so the excerpts
    # read as a conversation.
    retrieved = [segment for segment in segments if segment.id in retrieved_ids]
    prompt = prompts.build_answer_prompt(cleaned, render_for_prompt(retrieved))

    raw, outcome = generate(
        model_call, prompt, Answer, system_instruction=prompts.ANSWER_SYSTEM_INSTRUCTION
    )
    requests += outcome.requests

    verified = verify_answer(raw, segment_lookup(segments), retrieved_ids)
    return AskResult(answer=verified, hits=hits, index=index, requests=requests)
