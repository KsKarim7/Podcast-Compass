"""A hand-written result for samples/sample_episode.vtt, used only by tests.

This is NOT shown in the interface. The app loads samples/sample_results.json, which is
produced by the real pipeline, because a hand-written result presented as app output
would misrepresent what the app does. Keeping it here lets the render, export and
grounding paths be tested without depending on a generated file.
"""

from __future__ import annotations

from podcast_compass.models import (
    Chapter,
    EpisodeResult,
    Evidence,
    Overview,
    QuizQuestion,
    Takeaway,
)


def handwritten_result() -> EpisodeResult:
    """Quotes are copied from samples/sample_episode.vtt, so grounding passes for real."""
    return EpisodeResult(
        overview=Overview(
            summary=(
                "A conversation about keeping bees in cities. Urban hives often do better "
                "than rural ones because a city flowers across a longer season, while the "
                "real constraint is water rather than forage. The practical advice is to "
                "start with four pieces of equipment and to take no honey in the first "
                "year, because a young colony needs its stores to survive the winter."
            ),
            themes=[
                "Cities as foraging habitat",
                "Water as the limiting factor",
                "Starting with less equipment",
                "Patience in the first year",
            ],
            takeaways=[
                Takeaway(
                    text="Urban hives can outproduce rural ones because cities flower for longer.",
                    evidence=Evidence(
                        segment_id="S001",
                        quote="urban hives often outproduce rural ones",
                    ),
                ),
                Takeaway(
                    text="Water, not flowers, is what a city colony runs short of.",
                    evidence=Evidence(
                        segment_id="S001",
                        quote="The limiting factor in a city is water, not flowers",
                    ),
                ),
                Takeaway(
                    text="A smoker works by masking alarm pheromone, not by calming bees.",
                    evidence=Evidence(
                        segment_id="S002",
                        quote="it masks the alarm pheromone so the colony does not organise against you",
                    ),
                ),
                Takeaway(
                    text="Expect no honey in the first year; the colony needs its stores.",
                    evidence=Evidence(
                        segment_id="S003",
                        quote="A first-year colony needs its stores to survive the winter",
                    ),
                ),
            ],
        ),
        chapters=[
            Chapter(
                title="Why cities suit bees",
                explanation=(
                    "Gardens, parks and street trees flower at different times, giving a "
                    "colony forage across a whole season rather than three intense weeks."
                ),
                start_segment_id="S001",
                evidence=Evidence(
                    segment_id="S001",
                    quote="A city has gardens, parks and street trees flowering at different times",
                ),
            ),
            Chapter(
                title="The equipment you actually need",
                explanation=(
                    "Four items are enough for a first year: hive, veil, smoker and hive "
                    "tool. The smoker is the one most often misunderstood."
                ),
                start_segment_id="S002",
                evidence=Evidence(
                    segment_id="S002",
                    quote="You need a hive, a veil, a smoker and a hive tool",
                ),
            ),
            Chapter(
                title="Leaving the first harvest alone",
                explanation=(
                    "Taking honey from a first-year colony is how beginners lose hives over "
                    "winter. Feed them through a poor autumn instead."
                ),
                start_segment_id="S003",
                evidence=Evidence(
                    segment_id="S003",
                    quote="Patience is most of the skill",
                ),
            ),
        ],
        quiz=[
            QuizQuestion(
                question="Why do urban hives often produce more than rural ones?",
                options=[
                    "Cities are warmer all year",
                    "A city flowers across a longer season",
                    "Urban bees are a different species",
                    "There are fewer predators in cities",
                ],
                correct_index=1,
                explanation=(
                    "A city has many different plants flowering at different times, while a "
                    "single crop gives a short, intense flow and then nothing."
                ),
                evidence=Evidence(
                    segment_id="S001",
                    quote="A city has gardens, parks and street trees flowering at different times",
                ),
            ),
            QuizQuestion(
                question="What does a smoker actually do?",
                options=[
                    "It calms the bees down",
                    "It masks the alarm pheromone",
                    "It warms the hive",
                    "It drives bees out of the supers",
                ],
                correct_index=1,
                explanation=(
                    "It is not a sedative. Masking the alarm pheromone stops the colony "
                    "co-ordinating a response while the hive is open."
                ),
                evidence=Evidence(
                    segment_id="S002",
                    quote="it masks the alarm pheromone so the colony does not organise against you",
                ),
            ),
            QuizQuestion(
                question="How much honey should a first-year beekeeper expect to take?",
                options=["Half the harvest", "A single frame", "None", "As much as the hive allows"],
                correct_index=2,
                explanation=(
                    "The colony needs its own stores for winter. Taking honey in year one is "
                    "how beginners lose a hive in February."
                ),
                evidence=Evidence(
                    segment_id="S002",
                    quote="you should expect to take none at all, and that is the correct outcome",
                ),
            ),
            QuizQuestion(
                question="What is the limiting resource for a colony in a city?",
                options=["Forage", "Water", "Space", "Daylight"],
                correct_index=1,
                explanation=(
                    "Flowers are plentiful in a city; water is not, and a colony drinks a "
                    "great deal while cooling the hive in summer."
                ),
                evidence=Evidence(
                    segment_id="S001",
                    quote="The limiting factor in a city is water, not flowers",
                ),
            ),
        ],
    )
