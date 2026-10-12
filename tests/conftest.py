import pytest

VTT = """WEBVTT

1
00:00:00.000 --> 00:00:04.500
So the thing people get wrong about sourdough is the timing.

2
00:00:04.500 --> 00:00:09.000
You can use the same flour as a bakery and still get a dense loaf.

3
00:00:09.000 --> 00:00:14.250
What matters is how warm your kitchen is.
"""

SRT = """1
00:00:00,000 --> 00:00:04,500
So the thing people get wrong about sourdough is the timing.

2
00:00:04,500 --> 00:00:09,000
You can use the same flour as a bakery and still get a dense loaf.
"""


@pytest.fixture
def vtt_text() -> str:
    return VTT


@pytest.fixture
def srt_text() -> str:
    return SRT


@pytest.fixture
def long_plain_text() -> str:
    """Comfortably over the 200-character minimum, in two paragraphs."""
    first = " ".join(["Fermentation depends on temperature more than on flour."] * 4)
    second = " ".join(["A warm kitchen ferments dough faster than a cold one."] * 4)
    return f"{first}\n\n{second}"


def words(count: int, word: str = "word") -> str:
    return " ".join([word] * count)
