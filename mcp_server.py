"""Podcast Compass as an MCP server: the app's parsing, retrieval and quote checks, offered
as tools that an AI client such as Claude Desktop or MCP Inspector can call.

It runs over stdio: the client starts this file as a subprocess and exchanges protocol
messages through its standard input and output. Anything else printed to stdout would
corrupt that stream, so the server only logs, and only to stderr.

    python mcp_server.py

The Gemini key comes from the GEMINI_API_KEY environment variable. Loading a transcript
needs no key; searching, asking and generating a quiz do.
"""

from __future__ import annotations

import logging
import os
import sys
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from podcast_compass import ask, config, messages, prompts, quota, rag
from podcast_compass.grounding import VerifiedCitation, verify_quiz
from podcast_compass.llm import (
    EmbedCall,
    LlmError,
    ModelCall,
    build_sdk_call,
    build_sdk_embedder,
    generate,
)
from podcast_compass.models import QuizOnly
from podcast_compass.parsing import InputError, parse_transcript
from podcast_compass.render import NO_TIMESTAMP_NOTICE
from podcast_compass.segments import (
    Segment,
    build_segments,
    format_timestamp,
    render_for_prompt,
    segment_lookup,
)

logger = logging.getLogger("podcast_compass.mcp")

# Transcripts are held in this process's memory only, and only the most recent few, so a
# long-running server does not grow without limit. Nothing is written to disk.
MAX_TRANSCRIPTS = 5
MAX_SEARCH_RESULTS = 10


class TranscriptInfo(BaseModel):
    transcript_id: str
    format: str = Field(description="vtt, srt or text, detected from the content")
    segments: int
    has_timestamps: bool
    notice: str | None = Field(description="Why there are no timestamps, when there are none")


class SearchHit(BaseModel):
    segment_id: str
    start: str | None = Field(description="HH:MM:SS read from the subtitle cues, if any")
    score: float = Field(description="Cosine similarity to the query, from -1 to 1")
    text: str = Field(description="The segment's text, verbatim from the transcript")


class SearchResult(BaseModel):
    hits: list[SearchHit]


class Citation(BaseModel):
    segment_id: str
    quote: str = Field(description="Checked to appear in the cited segment")
    start: str | None = Field(description="HH:MM:SS read from the subtitle cues, if any")


class AnswerResult(BaseModel):
    supported: bool
    answer: str
    citations: list[Citation]
    dropped_citations: int = Field(description="Citations removed because they failed the check")


class QuizItem(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    citation: Citation


class QuizResult(BaseModel):
    questions: list[QuizItem]
    dropped_questions: int = Field(description="Questions removed because they failed the check")


@dataclass
class Loaded:
    segments: list[Segment]
    index: rag.SegmentIndex | None = None


def _start(seconds: float | None) -> str | None:
    return format_timestamp(seconds) if seconds is not None else None


def _citation(item: VerifiedCitation) -> Citation:
    return Citation(segment_id=item.segment_id, quote=item.quote, start=_start(item.start_seconds))


def _provider_error(exc: LlmError) -> ToolError:
    """The app's messages point at its example episode, which an MCP client cannot see."""
    if exc.failure.kind == "config":
        return ToolError("not_configured: the Gemini API key was rejected; check GEMINI_API_KEY.")
    if exc.failure.kind == "quota":
        return ToolError("quota_exceeded: the provider's free-tier limit was reached; try later.")
    return ToolError(f"provider_error: {exc.user_message}")


def create_server(
    *,
    model_call_factory: Callable[[str], ModelCall] = build_sdk_call,
    embed_call_factory: Callable[[str], EmbedCall] = build_sdk_embedder,
    counter: quota.DailyCounter | None = None,
) -> MCPServer:
    """Built by a function so tests can pass fake providers and their own counter."""
    server = MCPServer(
        "podcast-compass",
        instructions=(
            "Load a podcast transcript, then search it, ask questions about it or generate a "
            "quiz. Every quote returned has been checked to appear in the segment it cites, "
            "and timestamps come only from subtitle cues."
        ),
    )
    transcripts: OrderedDict[str, Loaded] = OrderedDict()
    daily = counter or quota.DailyCounter()

    def loaded(transcript_id: str) -> Loaded:
        if transcript_id not in transcripts:
            raise ToolError(
                "unknown_transcript: no transcript with that id is loaded; call "
                "load_transcript first. Only the most recent "
                f"{MAX_TRANSCRIPTS} are kept."
            )
        return transcripts[transcript_id]

    def api_key() -> str:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ToolError("not_configured: set GEMINI_API_KEY in the server's environment.")
        return key

    def spend(worst: int, run):
        """Reserve the worst case, run, settle with what was spent, as the app does."""
        if not daily.reserve(worst):
            raise ToolError(
                f"quota_exceeded: this server's limit of {daily.limit} requests a day is used up."
            )
        try:
            value, spent = run()
        except InputError as exc:
            daily.release(worst)
            raise ToolError(f"invalid_input: {exc}") from exc
        except LlmError as exc:
            # As in the app: on a failure the reservation is kept, so the count runs high.
            raise _provider_error(exc) from exc
        except ValueError as exc:
            # Embeddings that cannot be indexed, such as empty vectors.
            logger.warning("could not index or search the embeddings", exc_info=True)
            raise ToolError(f"provider_error: {messages.UNKNOWN}") from exc
        daily.settle(worst, spent)
        return value

    @server.tool()
    def load_transcript(
        text: Annotated[
            str,
            Field(
                min_length=1,
                max_length=config.MAX_CHARS,
                description="The transcript: plain text, WebVTT or SubRip, as text.",
            ),
        ],
    ) -> TranscriptInfo:
        """Parse and segment a transcript, and return the id the other tools take.
        Makes no API request."""
        try:
            parsed = parse_transcript(text)
        except InputError as exc:
            raise ToolError(f"invalid_input: {exc}") from exc

        segments = build_segments(parsed)
        transcript_id = rag.transcript_key(segments)[:16]
        transcripts[transcript_id] = transcripts.pop(transcript_id, Loaded(segments))
        while len(transcripts) > MAX_TRANSCRIPTS:
            transcripts.popitem(last=False)

        return TranscriptInfo(
            transcript_id=transcript_id,
            format=parsed.detected,
            segments=len(segments),
            has_timestamps=parsed.has_timestamps,
            notice=None if parsed.has_timestamps else NO_TIMESTAMP_NOTICE,
        )

    @server.tool()
    def search_transcript(
        transcript_id: Annotated[str, Field(min_length=1, max_length=64)],
        query: Annotated[str, Field(min_length=1, max_length=config.MAX_QUESTION_CHARS)],
        k: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = config.RETRIEVAL_TOP_K,
    ) -> SearchResult:
        """Find the transcript segments closest in meaning to the query, best first.
        Returns each segment's own text, so nothing here is generated."""
        item = loaded(transcript_id)
        cleaned = ask.clean_question(query)
        if not cleaned:
            raise ToolError("invalid_input: the query is empty.")
        key = api_key()
        current = ask.index_is_current(item.index, item.segments)
        worst = (0 if current else rag.requests_to_index(len(item.segments))) + 1

        def run():
            embed_call = embed_call_factory(key)
            spent = 0
            if not current:
                item.index = rag.build_index(item.segments, embed_call)
                spent += item.index.requests
            hits = rag.search(item.index, cleaned, embed_call, k)
            return hits, spent + 1

        hits = spend(worst, run)
        lookup = segment_lookup(item.segments)
        return SearchResult(
            hits=[
                SearchHit(
                    segment_id=hit.segment_id,
                    start=_start(lookup[hit.segment_id].start),
                    score=round(hit.score, 4),
                    text=lookup[hit.segment_id].text,
                )
                for hit in hits
            ]
        )

    @server.tool()
    def ask_podcast(
        transcript_id: Annotated[str, Field(min_length=1, max_length=64)],
        question: Annotated[str, Field(min_length=1, max_length=config.MAX_QUESTION_CHARS)],
    ) -> AnswerResult:
        """Answer a question from the transcript only. Every citation's quote is checked
        against the segment it cites; if none survives, the answer says the transcript
        does not answer the question."""
        item = loaded(transcript_id)
        key = api_key()
        worst = ask.worst_case_requests(item.index, item.segments)

        def run():
            result = ask.ask(
                question,
                item.segments,
                model_call=model_call_factory(key),
                embed_call=embed_call_factory(key),
                index=item.index,
            )
            item.index = result.index
            return result, result.requests

        result = spend(worst, run)
        return AnswerResult(
            supported=result.answer.supported,
            answer=result.answer.text,
            citations=[_citation(citation) for citation in result.answer.citations],
            dropped_citations=result.answer.dropped,
        )

    @server.tool()
    def generate_quiz(
        transcript_id: Annotated[str, Field(min_length=1, max_length=64)],
    ) -> QuizResult:
        """Generate 5-8 multiple-choice questions. Each answer cites a segment and a
        quote; questions whose quote cannot be found there are removed."""
        item = loaded(transcript_id)
        key = api_key()
        prompt = prompts.build_quiz_prompt(render_for_prompt(item.segments))

        def run():
            raw, outcome = generate(model_call_factory(key), prompt, QuizOnly)
            return raw, outcome.requests

        raw = spend(quota.REQUESTS_PER_ACTION, run)
        lookup = segment_lookup(item.segments)
        kept, report = verify_quiz(raw.quiz, lookup)
        if not kept:
            raise ToolError(
                "unverifiable: none of the generated questions could be confirmed against "
                "the transcript; try again."
            )
        return QuizResult(
            questions=[
                QuizItem(
                    question=question.question,
                    options=list(question.options),
                    correct_index=question.correct_index,
                    explanation=question.explanation,
                    citation=Citation(
                        segment_id=question.evidence.segment_id,
                        quote=question.evidence.quote,
                        start=_start(lookup[question.evidence.segment_id].start),
                    ),
                )
                for question in kept
            ],
            dropped_questions=report.quiz_dropped,
        )

    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    create_server().run("stdio")


if __name__ == "__main__":
    main()
