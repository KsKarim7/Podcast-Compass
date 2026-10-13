import pytest

# Fixtures have to clear the 250-word minimum, because that minimum is what guarantees
# a transcript makes enough segments to carry two chapters. Each cue therefore carries
# a real opening sentence plus filler, which keeps the cue count small and readable
# while making the whole thing long enough to be accepted.
FILLER = (
    "The point people miss is that temperature changes how quickly the dough ferments, "
    "which is why the same recipe behaves differently in a warm kitchen and a cold one, "
    "and why timing beats measuring almost every time. "
)

VTT = f"""WEBVTT

1
00:00:00.000 --> 00:00:04.500
So the thing people get wrong about sourdough is the timing, not the recipe. {FILLER * 2}

2
00:00:04.500 --> 00:00:09.000
You can use the same flour as a bakery and still get a dense loaf. {FILLER * 2}

3
00:00:09.000 --> 00:00:14.250
What matters is how warm your kitchen is. {FILLER * 2}
"""

SRT = f"""1
00:00:00,000 --> 00:00:04,500
So the thing people get wrong about sourdough is the timing, not the recipe. {FILLER * 2}

2
00:00:04,500 --> 00:00:09,000
You can use the same flour as a bakery and still get a dense loaf. {FILLER * 2}

3
00:00:09,000 --> 00:00:14,000
A cold kitchen will slow everything down by hours. {FILLER * 2}
"""


@pytest.fixture
def vtt_text() -> str:
    return VTT


@pytest.fixture
def srt_text() -> str:
    return SRT


@pytest.fixture
def long_plain_text() -> str:
    """Comfortably over the word minimum, in two paragraphs."""
    first = "Fermentation depends on temperature more than on flour. " + FILLER * 4
    second = "A warm kitchen ferments dough faster than a cold one. " + FILLER * 4
    return f"{first}\n\n{second}"


def words(count: int, word: str = "word") -> str:
    return " ".join([word] * count)


def long_enough(word: str = "word") -> str:
    """Plain text that passes validation, for tests that do not care about content."""
    return words(260, word)
