"""Podcast Compass: turn a transcript into an overview, chapters and a quiz.

This module is layout and state only. Parsing, validation, export and the provider call
live in the podcast_compass package so they can be tested without a browser or a key.
"""

from __future__ import annotations

import time

import streamlit as st

from podcast_compass import config, export, prompts, quota, render, sample
from podcast_compass.grounding import GroundedResult, GroundingRejected, validate
from podcast_compass.llm import LlmError, build_sdk_call, generate
from podcast_compass.models import SECTION_MODELS, EpisodeResult, replace_section
from podcast_compass.parsing import InputError, decode_bytes, parse_transcript
from podcast_compass.segments import build_segments, render_for_prompt, segment_lookup

st.set_page_config(page_title="Podcast Compass", page_icon="🎧", layout="centered")

REJECTION_MESSAGE = (
    "We could not verify enough of that result against your transcript, so we are not "
    "showing it."
)
NO_KEY_MESSAGE = (
    "This app is not configured with an API key, so generation is unavailable. "
    "The example episode still works."
)
SECTION_LABELS = {"overview": "Overview", "chapters": "Chapters", "quiz": "Quiz"}
PRESET_LABELS = {
    "shorter": "Shorter",
    "simpler": "Simpler",
    "more_detailed": "More detailed",
    "harder": "Harder questions",
    "custom": "Custom instruction",
}


@st.cache_resource
def daily_counter() -> quota.DailyCounter:
    """One counter shared by every session in this process.

    st.cache_resource is documented as "shared across all users, sessions, and reruns",
    which is the scope we want. Its limits are stated in quota.LIMITATION_NOTE and in
    the README rather than glossed over.
    """
    return quota.DailyCounter()


def session_usage() -> quota.SessionUsage:
    if "usage" not in st.session_state:
        st.session_state["usage"] = quota.SessionUsage()
    return st.session_state["usage"]


def spend_allowed() -> str | None:
    """None when an action may proceed, otherwise the message to show.

    Checked before the client is built, so a blocked action costs nothing at all.
    """
    decision = quota.check(
        session_usage(), daily_counter(), monotonic=time.monotonic()
    )
    return None if decision.allowed else decision.message


def call_with_quota(run):
    """Reserve the worst case, run the call, then give back what was not used.

    Reserving up front is what stops several sessions starting at once from pushing the
    day past its limit; settling afterwards means a plain single-request generation is
    only charged one request.
    """
    counter = daily_counter()
    reserved = quota.REQUESTS_PER_ACTION
    if not counter.reserve(reserved):
        return None, quota.DAILY_LIMIT_MESSAGE

    try:
        raw, outcome = run()
    except LlmError as exc:
        # The provider was reached, so at least one request was spent.
        counter.settle(reserved, 1)
        quota.record_action(session_usage(), monotonic=time.monotonic())
        return None, exc.user_message

    counter.settle(reserved, outcome.requests)
    quota.record_action(session_usage(), monotonic=time.monotonic())
    return (raw, outcome), None


def api_key() -> str | None:
    """Streamlit raises if no secrets file exists at all, so this stays defensive."""
    try:
        key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None
    return key or None


def init_state() -> None:
    st.session_state.setdefault("raw", None)
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("segments", None)
    st.session_state.setdefault("detection", None)
    st.session_state.setdefault("notice", None)
    st.session_state.setdefault("error", None)
    st.session_state.setdefault("previous", {})
    st.session_state.setdefault("checked", False)
    st.session_state.setdefault("source", None)


def clear_all() -> None:
    for key in ("raw", "result", "segments", "detection", "notice", "error", "source"):
        st.session_state[key] = None
    st.session_state["previous"] = {}
    st.session_state["checked"] = False


def clear_answers(count: int) -> None:
    st.session_state["checked"] = False
    for number in range(count):
        st.session_state.pop(f"answer_{number}", None)


def store(raw: EpisodeResult, segments, detection: str, source: str) -> None:
    """Validate and keep both the raw result and the grounded view.

    The raw result is what a revision merges into, and the grounded view is what the
    page renders. Keeping both means a revision is re-validated as a whole.
    """
    lookup = segment_lookup(segments)
    try:
        grounded = validate(raw, lookup)
    except GroundingRejected as exc:
        st.session_state["error"] = f"{REJECTION_MESSAGE} ({exc})"
        return
    st.session_state["raw"] = raw
    st.session_state["result"] = grounded
    st.session_state["segments"] = segments
    st.session_state["detection"] = detection
    st.session_state["source"] = source


def load_sample() -> None:
    clear_all()
    try:
        bundle = sample.load_bundle()
    except FileNotFoundError as exc:
        st.session_state["error"] = str(exc)
        return
    parsed = parse_transcript(bundle.transcript)
    segments = build_segments(parsed)
    store(
        bundle.result,
        segments,
        render.detection_line(parsed, len(segments)),
        source="sample",
    )
    st.session_state["notice"] = bundle.label


def run_generation(text: str) -> None:
    clear_all()

    # Input is checked first so a bad file is reported as a bad file, and the detection
    # line is shown even when generation cannot run, which tells the user something
    # useful about their transcript either way.
    try:
        parsed = parse_transcript(text)
    except InputError as exc:
        st.session_state["error"] = str(exc)
        return

    segments = build_segments(parsed)
    st.session_state["detection"] = render.detection_line(parsed, len(segments))

    key = api_key()
    if key is None:
        st.session_state["error"] = NO_KEY_MESSAGE
        return

    blocked = spend_allowed()
    if blocked:
        st.session_state["error"] = blocked
        return

    prompt = prompts.build_generation_prompt(render_for_prompt(segments))

    with st.status("Reading the transcript and generating…", expanded=False) as status:
        result, error = call_with_quota(
            lambda: generate(build_sdk_call(key), prompt, EpisodeResult)
        )
        if error:
            status.update(label="Generation failed", state="error")
            st.session_state["error"] = error
            return
        raw, outcome = result
        status.update(
            label=f"Generated in {outcome.elapsed_ms / 1000:.1f} s", state="complete"
        )

    store(raw, segments, st.session_state["detection"], source="live")
    if outcome.used_fallback:
        st.session_state["notice"] = (
            f"The first model was unavailable, so this came from {outcome.model}."
        )


def run_revision(section: str, instruction: str) -> None:
    key = api_key()
    if key is None:
        st.session_state["error"] = NO_KEY_MESSAGE
        return

    blocked = spend_allowed()
    if blocked:
        st.session_state["error"] = blocked
        return

    raw: EpisodeResult = st.session_state["raw"]
    segments = st.session_state["segments"]
    section_model = SECTION_MODELS[section]
    prompt = prompts.build_revision_prompt(
        section,
        section_model.model_validate(raw.model_dump()).model_dump_json(indent=2),
        instruction,
        render_for_prompt(segments),
    )

    with st.status(f"Revising the {SECTION_LABELS[section].lower()}…") as status:
        result, error = call_with_quota(
            lambda: generate(build_sdk_call(key), prompt, section_model)
        )
        if error:
            status.update(label="Revision failed", state="error")
            st.session_state["error"] = error
            return
        revised, outcome = result
        status.update(label=f"Revised in {outcome.elapsed_ms / 1000:.1f} s", state="complete")

    # Keep the pre-revision section so undo costs nothing.
    previous = dict(st.session_state["previous"])
    previous[section] = section_model.model_validate(raw.model_dump())
    merged = replace_section(raw, section, revised)

    st.session_state["error"] = None
    store(merged, segments, st.session_state["detection"], st.session_state["source"])
    if st.session_state["result"] is not None:
        st.session_state["previous"] = previous
        if section == "quiz":
            clear_answers(len(st.session_state["result"].quiz))


def undo(section: str) -> None:
    """A state swap, not a request."""
    previous = dict(st.session_state["previous"])
    restored = previous.pop(section, None)
    if restored is None:
        return
    raw = replace_section(st.session_state["raw"], section, restored)
    store(raw, st.session_state["segments"], st.session_state["detection"], st.session_state["source"])
    st.session_state["previous"] = previous
    if section == "quiz" and st.session_state["result"] is not None:
        clear_answers(len(st.session_state["result"].quiz))


def read_input(pasted: str, upload) -> str:
    if upload is not None:
        return decode_bytes(upload.getvalue())
    return pasted


def show_input() -> None:
    st.title("Podcast Compass")
    st.write(
        "Paste a podcast transcript and get an overview, navigable chapters and a quiz, "
        "with every claim tied back to the part of the transcript it came from."
    )

    # Shown before any input is accepted, because free-tier terms apply to whatever is sent.
    st.warning(render.DATA_USE_NOTICE, icon="⚠️")

    pasted = st.text_area("Paste a transcript", height=200, key="pasted")
    upload = st.file_uploader(
        "or upload a file",
        type=["txt", "vtt", "srt"],
        accept_multiple_files=False,
        max_upload_size=config.MAX_UPLOAD_MB,
    )
    st.caption(config.LIMITS_TEXT)

    if pasted:
        st.caption(f"{len(pasted.strip()):,} / {config.MAX_CHARS:,} characters")

    has_key = api_key() is not None
    left, right = st.columns(2)
    with left:
        st.button(
            "Load example episode",
            on_click=load_sample,
            help="Shows a result generated earlier. Makes no API call.",
            width="stretch",
        )
    with right:
        if st.button("Generate", width="stretch", type="primary"):
            text = read_input(pasted, upload)
            if not text.strip():
                st.session_state["error"] = "Paste a transcript or upload a file first."
            else:
                run_generation(text)

    st.caption(quota.allowance_caption(session_usage(), daily_counter()))
    with st.expander("Why this demo has limits"):
        st.write(quota.LIMITATION_NOTE)

    if not has_key:
        st.caption(NO_KEY_MESSAGE)


def show_overview(result: GroundedResult) -> None:
    st.subheader("Overview")
    st.write(result.summary)

    st.markdown("**Main themes**")
    for theme in result.themes:
        st.markdown(f"- {theme}")

    st.markdown("**Key takeaways**")
    for takeaway in result.takeaways:
        st.markdown(f"- {takeaway.text}")
        st.caption(
            render.evidence_caption(takeaway.evidence.segment_id, takeaway.evidence.quote)
        )


def show_chapters(result: GroundedResult) -> None:
    st.subheader("Chapters")
    if not result.has_timestamps:
        st.info(render.NO_TIMESTAMP_NOTICE, icon="ℹ️")
    for item in result.chapters:
        st.markdown(f"**{render.chapter_heading(item)}**")
        st.write(item.chapter.explanation)
        st.caption(
            render.evidence_caption(
                item.chapter.evidence.segment_id, item.chapter.evidence.quote
            )
        )


def show_quiz(result: GroundedResult) -> None:
    st.subheader("Quiz")
    with st.form("quiz"):
        for number, question in enumerate(result.quiz):
            st.markdown(f"**{number + 1}. {question.question}**")
            st.radio(
                "Choose an answer",
                options=range(len(question.options)),
                format_func=lambda i, q=question: q.options[i],
                key=f"answer_{number}",
                index=None,
                label_visibility="collapsed",
            )
        if st.form_submit_button("Check answers"):
            st.session_state["checked"] = True

    if not st.session_state["checked"]:
        return

    for number, question in enumerate(result.quiz):
        chosen = st.session_state.get(f"answer_{number}")
        correct = question.options[question.correct_index]
        if chosen is None:
            # Neutral: not answering is not a mistake, but the answer is still useful.
            st.markdown(f"**{number + 1}. Not answered** — the answer is {correct}")
        elif chosen == question.correct_index:
            st.success(f"{number + 1}. Correct — {correct}")
        else:
            st.error(f"{number + 1}. Not quite. The answer is {correct}")
        st.write(question.explanation)
        st.caption(
            render.evidence_caption(question.evidence.segment_id, question.evidence.quote)
        )

    if st.button("Reset quiz"):
        clear_answers(len(result.quiz))
        st.rerun()


def show_revision(result: GroundedResult) -> None:
    st.subheader("Revise one section")
    st.caption(
        "Only the section you choose is regenerated. The rest of the result is left "
        "exactly as it is."
    )

    section = st.selectbox(
        "Section",
        options=list(SECTION_LABELS),
        format_func=lambda key: SECTION_LABELS[key],
        key="revise_section",
    )
    preset = st.radio(
        "Change",
        options=list(PRESET_LABELS),
        format_func=lambda key: PRESET_LABELS[key],
        horizontal=True,
        key="revise_preset",
    )
    instruction = prompts.PRESET_INSTRUCTIONS.get(preset, "")
    if preset == "custom":
        instruction = st.text_input(
            "What should change?",
            max_chars=config.MAX_REVISION_CHARS,
            placeholder="e.g. focus on the practical advice",
            key="revise_custom",
        )

    has_key = api_key() is not None
    left, right = st.columns(2)
    with left:
        disabled = not has_key or (preset == "custom" and not instruction.strip())
        if st.button("Revise this section", disabled=disabled, width="stretch"):
            run_revision(section, instruction)
            st.rerun()
    with right:
        can_undo = section in st.session_state["previous"]
        if st.button(
            f"Undo last change to {SECTION_LABELS[section].lower()}",
            disabled=not can_undo,
            width="stretch",
            help="Restores the previous version. Makes no API call.",
        ):
            undo(section)
            st.rerun()


def show_output(result: GroundedResult) -> None:
    st.subheader("Copy or download")
    markdown = export.as_markdown(result)
    generated_at = ""
    model = ""
    if st.session_state["source"] == "sample" and sample.result_exists():
        bundle = sample.load_bundle()
        generated_at, model = bundle.generated_at, bundle.model
    payload = export.as_json(result, model=model, generated_at=generated_at)

    st.caption("Use the copy button in the top-right of the box below.")
    st.code(markdown, language="markdown", height=300)

    left, right = st.columns(2)
    with left:
        st.download_button(
            "Download Markdown",
            data=markdown,
            file_name="episode.md",
            mime="text/markdown",
            on_click="ignore",
            width="stretch",
        )
    with right:
        st.download_button(
            "Download JSON",
            data=payload,
            file_name="episode.json",
            mime="application/json",
            on_click="ignore",
            width="stretch",
        )


def show_messages() -> None:
    if st.session_state["error"]:
        st.error(st.session_state["error"])
        # No automatic retry: a call that returned parseable output already spent a
        # request, so spending another is the user's decision rather than ours.
        if st.button("Try again"):
            clear_all()
            st.rerun()
    if st.session_state["notice"]:
        st.info(st.session_state["notice"], icon="ℹ️")


def main() -> None:
    init_state()
    show_input()
    st.divider()
    show_messages()

    if st.session_state["detection"]:
        st.caption(st.session_state["detection"])

    result = st.session_state["result"]
    if result is None:
        return

    st.caption(result.report.summary())
    show_overview(result)
    show_chapters(result)
    show_quiz(result)
    st.divider()
    show_revision(result)
    st.divider()
    show_output(result)


main()
