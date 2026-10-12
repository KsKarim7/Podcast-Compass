import pytest

from podcast_compass.grounding import (
    GroundingRejected,
    normalise,
    quote_is_grounded,
    validate,
)
from podcast_compass.models import (
    Chapter,
    EpisodeResult,
    Evidence,
    Overview,
    QuizQuestion,
    Takeaway,
)
from podcast_compass.segments import Segment

SEG_TEXT = {
    "S001": "So the thing people get wrong about sourdough is the timing, not the recipe.",
    "S002": "You can use the same flour as a bakery and still get a dense loaf.",
    "S003": "What matters is how warm your kitchen is, because that changes fermentation.",
    "S004": "A cold kitchen will slow everything down by hours.",
}


@pytest.fixture
def segments() -> dict[str, Segment]:
    return {
        sid: Segment(id=sid, text=text, start=float(i * 30), end=float(i * 30 + 29))
        for i, (sid, text) in enumerate(SEG_TEXT.items())
    }


@pytest.fixture
def untimed_segments() -> dict[str, Segment]:
    return {
        sid: Segment(id=sid, text=text, start=None, end=None)
        for sid, text in SEG_TEXT.items()
    }


def ev(segment_id: str, quote: str) -> Evidence:
    return Evidence(segment_id=segment_id, quote=quote)


def takeaway(segment_id="S001", quote="the timing, not the recipe") -> Takeaway:
    return Takeaway(text="Timing matters most.", evidence=ev(segment_id, quote))


def chapter(segment_id="S001", quote="the timing, not the recipe", title="Timing") -> Chapter:
    return Chapter(
        title=title,
        explanation="Why timing dominates.",
        start_segment_id=segment_id,
        evidence=ev(segment_id, quote),
    )


def question(segment_id="S003", quote="how warm your kitchen is", index=0) -> QuizQuestion:
    return QuizQuestion(
        question="What matters most?",
        options=["Temperature", "Flour", "Water", "Time"],
        correct_index=index,
        explanation="Warmth drives fermentation.",
        evidence=ev(segment_id, quote),
    )


def result(
    *, takeaways=None, chapters=None, quiz=None, summary="A short summary."
) -> EpisodeResult:
    return EpisodeResult(
        overview=Overview(
            summary=summary,
            themes=["timing", "temperature"],
            takeaways=takeaways if takeaways is not None else [takeaway()],
        ),
        chapters=chapters
        if chapters is not None
        else [chapter(), chapter("S003", "how warm your kitchen is", "Temperature")],
        quiz=quiz if quiz is not None else [question()],
    )


class TestNormalise:
    def test_collapses_whitespace_and_casefolds(self):
        assert normalise("  The   TIMING \n not  ") == "the timing not"

    def test_curly_quotes_and_dashes_folded(self):
        assert normalise("“it’s” — fine") == '"it\'s" - fine'

    def test_nbsp_treated_as_a_space(self):
        assert normalise("a b") == "a b"


class TestQuoteGrounding:
    def test_exact_quote_passes(self, segments):
        assert quote_is_grounded(ev("S001", "the timing, not the recipe"), segments)

    def test_punctuation_and_spacing_differences_still_pass(self, segments):
        # These must keep passing. If someone "tightens" the normaliser into an
        # exact-match check, real quotes from the model start being dropped.
        assert quote_is_grounded(ev("S001", "THE TIMING, NOT THE RECIPE"), segments)
        assert quote_is_grounded(ev("S001", "the timing,  not   the recipe"), segments)
        assert quote_is_grounded(ev("S001", "the timing,\nnot the recipe"), segments)
        assert quote_is_grounded(ev("S001", "the timing, not the recipe"), segments)

    def test_curly_quote_style_differences_pass(self):
        segs = {"S001": Segment(id="S001", text="he said “it’s warm” today", start=0.0, end=1.0)}
        assert quote_is_grounded(ev("S001", 'he said "it\'s warm" today'), segs)

    def test_substituted_punctuation_does_not_pass(self, segments):
        # The normaliser folds punctuation *style*, not punctuation *choice*: swapping
        # the comma for a dash fails. Documented rather than fixed, because loosening
        # this means accepting quotes that are not what the transcript says.
        assert not quote_is_grounded(ev("S001", "the timing - not the recipe"), segments)

    def test_paraphrase_fails(self, segments):
        assert not quote_is_grounded(ev("S001", "timing is more important than recipe"), segments)

    def test_quote_from_a_different_segment_fails(self, segments):
        assert not quote_is_grounded(ev("S002", "the timing, not the recipe"), segments)

    def test_unknown_segment_fails(self, segments):
        assert not quote_is_grounded(ev("S999", "the timing, not the recipe"), segments)

    def test_too_short_a_quote_fails(self, segments):
        # "the timing" appears, but two words prove nothing.
        assert not quote_is_grounded(ev("S001", "the timing"), segments)


class TestTakeaways:
    def test_ungrounded_takeaway_dropped(self, segments):
        grounded = validate(
            result(takeaways=[takeaway(), takeaway("S001", "completely invented words here")]),
            segments,
        )
        assert len(grounded.takeaways) == 1
        assert grounded.report.takeaways_dropped == 1

    def test_report_counts_are_real(self, segments):
        grounded = validate(result(takeaways=[takeaway(), takeaway()]), segments)
        assert "Kept 2 of 2 takeaways" in grounded.report.summary()

    def test_summary_pluralises_and_names_no_single_cause(self, segments):
        grounded = validate(
            result(
                takeaways=[takeaway(), takeaway("S001", "invented words right here")],
                quiz=[question(), question(index=9)],
            ),
            segments,
        )
        summary = grounded.report.summary()
        assert "2 items dropped" in summary
        # An out-of-range answer index is not a missing quote, so the text must not say so.
        assert "quote was not found" not in summary
        assert "1 chapter(s)" not in summary


class TestQuiz:
    def test_ungrounded_question_dropped(self, segments):
        grounded = validate(
            result(quiz=[question(), question("S003", "not in the transcript at all")]),
            segments,
        )
        assert len(grounded.quiz) == 1
        assert grounded.report.quiz_dropped == 1

    def test_correct_index_out_of_range_dropped(self, segments):
        # The schema can only require an integer; the range is checked here.
        grounded = validate(result(quiz=[question(), question(index=7)]), segments)
        assert len(grounded.quiz) == 1
        assert any("outside 0..3" in reason for reason in grounded.report.reasons)

    def test_negative_correct_index_dropped(self, segments):
        grounded = validate(result(quiz=[question(), question(index=-1)]), segments)
        assert len(grounded.quiz) == 1

    def test_last_valid_index_accepted(self, segments):
        grounded = validate(result(quiz=[question(index=3)]), segments)
        assert len(grounded.quiz) == 1


class TestChapters:
    def test_verified_chapter_gets_its_segment_start_time(self, segments):
        grounded = validate(result(), segments)
        first = grounded.chapters[0]
        assert first.verified is True
        assert first.start_seconds == segments["S001"].start

    def test_unverified_chapter_is_kept_but_has_no_timestamp(self, segments):
        bad = chapter("S002", "this quote is not in segment two", "Mystery")
        grounded = validate(
            result(chapters=[chapter(), chapter("S003", "how warm your kitchen is"), bad]),
            segments,
        )
        assert len(grounded.chapters) == 3
        flagged = [c for c in grounded.chapters if not c.verified]
        assert len(flagged) == 1
        assert flagged[0].start_seconds is None
        assert flagged[0].chapter.title == "Mystery"

    def test_chapter_with_unknown_segment_flagged(self, segments):
        grounded = validate(
            result(
                chapters=[
                    chapter(),
                    chapter("S003", "how warm your kitchen is"),
                    chapter("S999", "the timing, not the recipe", "Ghost"),
                ]
            ),
            segments,
        )
        ghost = [c for c in grounded.chapters if c.chapter.title == "Ghost"][0]
        assert ghost.verified is False
        assert "does not exist" in ghost.reason

    def test_out_of_order_chapter_flagged(self, segments):
        grounded = validate(
            result(
                chapters=[
                    chapter("S003", "how warm your kitchen is", "Later"),
                    chapter("S004", "slow everything down by hours", "Latest"),
                    chapter("S001", "the timing, not the recipe", "Earlier"),
                ]
            ),
            segments,
        )
        earlier = [c for c in grounded.chapters if c.chapter.title == "Earlier"][0]
        assert earlier.verified is False
        assert "before the previous chapter" in earlier.reason
        assert earlier.start_seconds is None

    def test_no_timestamps_for_plain_text_input(self, untimed_segments):
        grounded = validate(result(), untimed_segments)
        assert grounded.has_timestamps is False
        assert all(c.start_seconds is None for c in grounded.chapters)
        assert all(c.verified for c in grounded.chapters)


class TestWholeResponseRejection:
    def test_empty_summary_rejected(self, segments):
        with pytest.raises(GroundingRejected, match="summary was empty"):
            validate(result(summary="   "), segments)

    def test_fewer_than_two_verified_chapters_rejected(self, segments):
        with pytest.raises(GroundingRejected, match="chapter"):
            validate(result(chapters=[chapter()]), segments)

    def test_no_surviving_quiz_question_rejected(self, segments):
        with pytest.raises(GroundingRejected, match="no quiz question"):
            validate(result(quiz=[question("S003", "nowhere in this transcript")]), segments)

    def test_majority_failure_rejected(self, segments):
        # 5 of 9 grounded items fail: 6 takeaways (1 good), 1 question, 2 chapters.
        bad_takeaways = [takeaway("S001", "invented text number one")] * 5
        with pytest.raises(GroundingRejected, match="failed validation"):
            validate(result(takeaways=[takeaway()] + bad_takeaways), segments)

    def test_exactly_half_failing_is_tolerated(self, segments):
        # The threshold is "more than half", so 4 of 8 survives. Pinned because the
        # boundary is the difference between retrying and showing a thin result.
        bad_takeaways = [takeaway("S001", "invented text number one")] * 4
        grounded = validate(result(takeaways=[takeaway()] + bad_takeaways), segments)
        assert grounded.report.takeaways_dropped == 4
        assert len(grounded.takeaways) == 1

    def test_scattered_failures_are_tolerated(self, segments):
        grounded = validate(
            result(
                takeaways=[takeaway(), takeaway(), takeaway("S001", "invented text here")],
                chapters=[chapter(), chapter("S003", "how warm your kitchen is")],
                quiz=[question(), question()],
            ),
            segments,
        )
        assert grounded.report.takeaways_dropped == 1
        assert len(grounded.takeaways) == 2


class TestPurity:
    def test_model_objects_are_not_mutated_with_times(self, segments):
        original = result()
        grounded = validate(original, segments)
        # The time lives on the wrapper, never on the model's own object.
        assert not hasattr(grounded.chapters[0].chapter, "start_seconds")
        assert grounded.chapters[0].start_seconds is not None
        assert original.chapters[0].start_segment_id == "S001"
