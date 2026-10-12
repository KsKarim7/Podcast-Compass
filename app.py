"""Podcast Compass: turn a transcript into an overview, chapters and a quiz.

This module is layout and state only. Parsing, validation and the provider call live in
the podcast_compass package so they can be tested without a browser or a key.
"""

from __future__ import annotations

import streamlit as st

from podcast_compass import config, render
from podcast_compass.demo import DEMO_VTT, demo_result
from podcast_compass.grounding import GroundedResult, GroundingRejected, validate
from podcast_compass.parsing import InputError, decode_bytes, parse_transcript
from podcast_compass.segments import build_segments, segment_lookup

st.set_page_config(page_title="Podcast Compass", page_icon="🎧", layout="centered")

REJECTION_MESSAGE = (
    "We could not verify enough of that result against your transcript, so we are not "
    "showing it."
)


def init_state() -> None:
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("detection", None)
    st.session_state.setdefault("rejection", None)
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("checked", False)


def clear_result() -> None:
    st.session_state["result"] = None
    st.session_state["detection"] = None
    st.session_state["rejection"] = None
    st.session_state["answers"] = {}
    st.session_state["checked"] = False


def load_demo() -> None:
    """Render the built-in example with no API call."""
    clear_result()
    parsed = parse_transcript(DEMO_VTT)
    segments = build_segments(parsed)
    try:
        result = validate(demo_result(), segment_lookup(segments))
    except GroundingRejected as exc:
        st.session_state["rejection"] = str(exc)
        return
    st.session_state["result"] = result
    st.session_state["detection"] = render.detection_line(parsed, len(segments))


def read_input(pasted: str, upload) -> str:
    if upload is not None:
        return decode_bytes(upload.getvalue())
    return pasted


def prepare(text: str) -> tuple[str, int]:
    """Parse and segment, returning the detection line and the segment count."""
    parsed = parse_transcript(text)
    segments = build_segments(parsed)
    st.session_state["segments"] = segments
    return render.detection_line(parsed, len(segments)), len(segments)


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
        used = len(pasted.strip())
        st.caption(f"{used:,} / {config.MAX_CHARS:,} characters")

    left, right = st.columns(2)
    with left:
        st.button(
            "Load example episode",
            on_click=load_demo,
            help="Renders a built-in example. Makes no API call.",
            width="stretch",
        )
    with right:
        if st.button("Check this transcript", width="stretch"):
            handle_check(pasted, upload)


def handle_check(pasted: str, upload) -> None:
    """Parse and segment only. Generation arrives with the model call."""
    clear_result()
    try:
        text = read_input(pasted, upload)
        if not text.strip():
            raise InputError("Paste a transcript or upload a file first.")
        detection, count = prepare(text)
    except InputError as exc:
        st.session_state["rejection"] = str(exc)
        return
    st.session_state["detection"] = detection
    st.toast(f"Read {count} segments. Generation is not wired up yet.")


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
            render.evidence_caption(
                takeaway.evidence.segment_id, takeaway.evidence.quote
            )
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
        if chosen is None:
            st.warning(f"{number + 1}. Not answered")
            continue
        verdict = render.answer_feedback(chosen, question.correct_index)
        correct = question.options[question.correct_index]
        if verdict == "Correct":
            st.success(f"{number + 1}. Correct — {correct}")
        else:
            st.error(f"{number + 1}. Not quite. The answer is {correct}")
        st.write(question.explanation)
        st.caption(
            render.evidence_caption(
                question.evidence.segment_id, question.evidence.quote
            )
        )

    if st.button("Reset quiz"):
        st.session_state["checked"] = False
        for number in range(len(result.quiz)):
            st.session_state.pop(f"answer_{number}", None)
        st.rerun()


def show_results() -> None:
    if st.session_state["detection"]:
        st.caption(st.session_state["detection"])

    result = st.session_state["result"]
    if result is None:
        return

    st.caption(result.report.summary())
    show_overview(result)
    show_chapters(result)
    show_quiz(result)


def show_rejection() -> None:
    reason = st.session_state["rejection"]
    if not reason:
        return
    st.error(f"{REJECTION_MESSAGE} ({reason})")
    # No automatic retry: the call already succeeded, so spending another request is
    # the user's decision rather than ours.
    if st.button("Try again"):
        clear_result()
        st.rerun()


def main() -> None:
    init_state()
    show_input()
    st.divider()
    show_rejection()
    show_results()


main()
