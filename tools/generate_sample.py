"""Regenerate samples/sample_results.json from samples/sample_episode.vtt.

Run this once to create the committed sample, and again whenever the prompts or the
result schema change, so the sample never shows output the current code could not
produce.

    GEMINI_API_KEY=... python tools/generate_sample.py

The key is read from the environment and is never written to a file.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast_compass import config, prompts, sample  # noqa: E402
from podcast_compass.grounding import GroundingRejected, validate  # noqa: E402
from podcast_compass.llm import LlmError, build_sdk_call, generate  # noqa: E402
from podcast_compass.models import EpisodeResult  # noqa: E402
from podcast_compass.parsing import parse_transcript  # noqa: E402
from podcast_compass.segments import build_segments, render_for_prompt, segment_lookup  # noqa: E402


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set.")
        return 2

    transcript = sample.load_transcript()
    parsed = parse_transcript(transcript)
    segments = build_segments(parsed)
    print(
        f"transcript: {parsed.detected}, {len(parsed.cues)} cues, "
        f"{len(segments)} segments, {len(transcript):,} chars"
    )

    prompt = prompts.build_generation_prompt(render_for_prompt(segments))
    print(f"prompt: {len(prompt):,} chars")

    started = time.monotonic()
    try:
        result, outcome = generate(build_sdk_call(key), prompt, EpisodeResult)
    except LlmError as exc:
        print(f"generation failed: {exc.failure.kind} — {exc.failure.detail}")
        print(f"user message would be: {exc.user_message}")
        return 1

    print(
        f"generated on {outcome.model} in {outcome.elapsed_ms:.0f} ms"
        f"{' (fallback)' if outcome.used_fallback else ''}"
        f"{' (repaired)' if outcome.repaired else ''}"
    )

    try:
        grounded = validate(result, segment_lookup(segments))
    except GroundingRejected as exc:
        print(f"the generated result did not pass grounding: {exc}")
        print("not saving. Re-run; if it keeps failing, the prompts need work.")
        return 1

    print(f"validation: {grounded.report.summary()}")
    for item in grounded.chapters:
        marker = "ok " if item.verified else "FLAG"
        print(f"  {marker} {item.start_seconds} {item.chapter.title}")

    sample.save_bundle(
        result,
        generated_at=date.today().isoformat(),
        model=outcome.model,
    )
    print(f"\nwrote {sample.RESULT_PATH.relative_to(Path.cwd())}")
    print(f"elapsed overall: {(time.monotonic() - started):.1f}s")
    print(f"primary model configured as: {config.PRIMARY_MODEL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
