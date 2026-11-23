"""The provider boundary: one call, classified failures, one fallback, one repair.

The SDK call is injected rather than imported at the call site, so every path in here is
testable without a key or a network. `_client`, `build_sdk_call` and `build_sdk_embedder` are
the only functions that touch google-genai.

Two things worth knowing about this SDK, both established by inspecting 2.29.0 rather than
from its documentation:

* `interactions.create` raises from a private hierarchy
  (`google.genai._gaos.lib.compat_errors`) whose base class is a *different* class also
  named `APIError`. Errors from it are not instances of the documented
  `google.genai.errors.APIError`, so the documented handler would catch nothing. We never
  import the private module; we read `status_code` off whatever arrives.
* On a timeout the exception has a `status_code` attribute whose value is `None`, so the
  test has to be `is not None` rather than `hasattr`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

from . import config, messages, prompts

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# User-facing wording lives in messages.py so it cannot drift.


class ModelCall(Protocol):
    """One request to one model. Returns the raw text the model produced."""

    def __call__(
        self, *, model: str, system_instruction: str, prompt: str, schema: dict[str, Any]
    ) -> str: ...


@dataclass(frozen=True)
class Failure:
    kind: str
    user_message: str
    use_fallback: bool
    detail: str


class LlmError(Exception):
    """A failure already translated into something a user can read."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.detail)
        self.failure = failure

    @property
    def user_message(self) -> str:
        return self.failure.user_message


@dataclass(frozen=True)
class Outcome:
    model: str
    elapsed_ms: float
    used_fallback: bool
    repaired: bool

    @property
    def requests(self) -> int:
        """How many provider requests this actually cost, for the daily counter."""
        return 1 + int(self.used_fallback) + int(self.repaired)


def _looks_like_timeout(exc: Exception) -> bool:
    """Timeouts and connection errors arrive without a usable status code.

    The exception is not an httpx instance; the httpx error is only reachable as its
    __cause__, so the class name is checked first and the cause is the backstop.
    """
    if type(exc).__name__ in {"APITimeoutError", "APIConnectionError"}:
        return True
    cause = exc.__cause__ or exc.__context__
    return cause is not None and type(cause).__module__.split(".")[0] == "httpx"


def classify(exc: Exception) -> Failure:
    status = getattr(exc, "status_code", None)
    if status is None:
        # The SDK's documented error class carries the HTTP status as `code` rather than
        # `status_code`. Read it too, in case the embeddings endpoint raises that class
        # rather than the private one described at the top of this module.
        code = getattr(exc, "code", None)
        status = code if isinstance(code, int) else None
    message = str(getattr(exc, "message", "") or exc)
    detail = f"{type(exc).__name__} status={status!r}"

    if status is not None:
        # An invalid key returns 400 INVALID_ARGUMENT, not the documented 401, so 400
        # cannot be treated as our own bug without checking the message first.
        if status in (400, 401) and "api key not valid" in message.casefold():
            return Failure("config", messages.REJECTED_KEY, False, detail)
        if status == 401:
            return Failure("config", messages.REJECTED_KEY, False, detail)
        if status == 403:
            return Failure("config", messages.REJECTED_KEY, False, detail)
        if status == 400:
            return Failure("bad_request", messages.UNKNOWN, False, detail)
        if status == 404:
            return Failure("not_found", messages.MODEL_BUSY, True, detail)
        if status == 429:
            return Failure("quota", messages.QUOTA_EXHAUSTED, True, detail)
        if status in (408, 500, 502, 503, 504):
            return Failure("transient", messages.MODEL_BUSY, True, detail)
        return Failure("unknown", messages.UNKNOWN, False, detail)

    if _looks_like_timeout(exc):
        return Failure("timeout", messages.TIMED_OUT, True, detail)

    return Failure("unknown", messages.UNKNOWN, False, detail)


def _attempt(
    call: ModelCall, model: str, system_instruction: str, prompt: str, schema: dict[str, Any]
) -> str:
    """The only place a provider exception can come from."""
    try:
        return call(
            model=model, system_instruction=system_instruction, prompt=prompt, schema=schema
        )
    except Exception as exc:  # noqa: BLE001 - classified immediately, never swallowed
        failure = classify(exc)
        logger.warning("call failed on %s: %s", model, failure.detail)
        raise LlmError(failure) from exc


def _parse(raw: str, schema_model: type[T]) -> T:
    """Separate from _attempt on purpose: our parsing failures are not provider failures."""
    return schema_model.model_validate_json(raw)


def generate(
    call: ModelCall,
    prompt: str,
    schema_model: type[T],
    *,
    system_instruction: str = prompts.SYSTEM_INSTRUCTION,
    primary_model: str = config.PRIMARY_MODEL,
    fallback_model: str = config.FALLBACK_MODEL,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[T, Outcome]:
    """One generation: primary, then one fallback, then one repair retry.

    Raises LlmError, whose user_message is safe to show.
    """
    schema = schema_model.model_json_schema()
    started = clock()
    used_fallback = False

    try:
        raw = _attempt(call, primary_model, system_instruction, prompt, schema)
        model = primary_model
    except LlmError as first:
        if not first.failure.use_fallback:
            raise
        used_fallback = True
        logger.info("falling back to %s after %s", fallback_model, first.failure.kind)
        raw = _attempt(call, fallback_model, system_instruction, prompt, schema)
        model = fallback_model

    try:
        parsed = _parse(raw, schema_model)
    except ValueError:  # pydantic ValidationError and JSONDecodeError are both ValueErrors
        elapsed = clock() - started
        if elapsed > config.REPAIR_BUDGET_S:
            logger.warning("skipping repair retry, %.1fs already spent", elapsed)
            raise LlmError(Failure("malformed", messages.MALFORMED_TWICE, False, "budget spent"))

        logger.info("output failed validation, attempting one repair retry")
        raw = _attempt(
            call, model, system_instruction, prompts.with_repair_preamble(prompt), schema
        )
        try:
            parsed = _parse(raw, schema_model)
        except ValueError as exc:
            raise LlmError(
                Failure("malformed", messages.MALFORMED_TWICE, False, f"repair failed: {exc!r}"[:200])
            ) from exc

        outcome = Outcome(model, (clock() - started) * 1000, used_fallback, repaired=True)
        logger.info("generated on %s in %.0f ms (repaired)", model, outcome.elapsed_ms)
        return parsed, outcome

    outcome = Outcome(model, (clock() - started) * 1000, used_fallback, repaired=False)
    logger.info("generated on %s in %.0f ms", model, outcome.elapsed_ms)
    return parsed, outcome


def _client(api_key: str):
    """One client configuration for both calls: our timeout and our retry policy."""
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=config.REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(
                attempts=config.RETRY_ATTEMPTS,
                initial_delay=config.RETRY_INITIAL_DELAY_S,
                max_delay=config.RETRY_MAX_DELAY_S,
                http_status_codes=config.RETRY_STATUS_CODES,
            ),
        ),
    )


def build_sdk_call(api_key: str) -> ModelCall:
    """The real adapter. Imported lazily so tests never need google-genai configured."""
    client = _client(api_key)

    def call(
        *, model: str, system_instruction: str, prompt: str, schema: dict[str, Any]
    ) -> str:
        interaction = client.interactions.create(
            model=model,
            system_instruction=system_instruction,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            },
        )
        return interaction.output_text

    return call


class EmbedCall(Protocol):
    """One embedding request for a batch of texts. Returns one vector per text."""

    def __call__(self, *, texts: list[str], task_type: str) -> list[list[float]]: ...


# An embedding failure has no second model to fall back to: vectors from another model
# could not be compared with the ones already in the index. So the "busy, trying a second
# model" wording would be wrong, and these kinds get their own message.
_SEARCH_FAILURE_KINDS = {"not_found", "transient", "timeout"}


def embed(call: EmbedCall, texts: list[str], task_type: str) -> list[list[float]]:
    """One embedding request, with failures classified exactly as for generation."""
    try:
        vectors = call(texts=texts, task_type=task_type)
    except Exception as exc:
        failure = classify(exc)
        if failure.kind in _SEARCH_FAILURE_KINDS:
            failure = replace(failure, user_message=messages.SEARCH_UNAVAILABLE)
        logger.warning("embedding call failed: %s", failure.detail)
        raise LlmError(failure) from exc

    if len(vectors) != len(texts):
        raise LlmError(
            Failure(
                "malformed",
                messages.UNKNOWN,
                False,
                f"asked for {len(texts)} embeddings, got {len(vectors)}",
            )
        )
    return vectors


def build_sdk_embedder(api_key: str) -> EmbedCall:
    """The real embedding adapter, lazily imported like build_sdk_call."""
    from google.genai import types

    client = _client(api_key)

    def call(*, texts: list[str], task_type: str) -> list[list[float]]:
        result = client.models.embed_content(
            model=config.EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=config.EMBEDDING_DIMENSIONS,
            ),
        )
        return [list(item.values) for item in result.embeddings]

    return call
