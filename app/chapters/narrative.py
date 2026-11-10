"""Structured local narrative variants follow an already persisted simulation."""

import random
import re
from pydantic import BaseModel, ConfigDict, Field

VERSION = 1


class Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    paragraphs: list[str]
    ending: str
    winner_id: int
    participant_names: list[str]
    summary: str
    key_events: list[str] = Field(min_length=2)
    transition: str
    chapter_number: int
    references: list[int]
    generation_version: int = VERSION


def outline(arena):
    return {
        "title": "The Moonlight Champions",
        "theme": "Courage and clever choices",
        "setting": "The ancient woodland trail"
        if arena == "land"
        else "The fictional split-habitat trail"
        if arena == "neutral"
        else "The moonlit ocean trail",
        "atmosphere": "Dramatic, safe adventure for age five",
        "progression": ["Quarterfinal"] * 4 + ["Semifinal"] * 2 + ["Championship"],
        "continuity_rules": [
            "Reference completed chapters only",
            "No future winners",
            "Defeated creatures remain safe",
        ],
        "version": VERSION,
    }


def generate(
    left, right, simulation, number, context, previous, settings, words=None, variant=0
):
    rng = random.Random(simulation["seed"] + variant)
    a, b = left["name"], right["name"]
    winner = left if simulation["winner_id"] == left["id"] else right
    loser = right if winner is left else left
    place = simulation["environment"]["name"].lower()
    refs = (
        [p["chapter_number"] for p in previous]
        if settings["connected_chapters"]
        else []
    )
    openings = [
        f"A hush falls over the {place}. {a} and {b} face the next challenge!",
        f"The moon peeks over the {place}. {a} moves closer, while {b} holds position.",
        f"Something stirs in the {place}. Here come {a} and {b}, ready for a daring contest!",
    ]
    intro = rng.choice(openings)
    if number == 7:
        intro = f"Six completed battles have brought us here. The championship begins in the {place}! {a} and {b} face their greatest challenge."
    elif refs:
        last = previous[-1]
        intro = f"After Chapter {last['chapter_number']}, {last['winner_name']} has advanced. Now {a} and {b} meet in the {place}."
    # No unreviewed species-specific anatomy is invented. Generic contest motion
    # works for the selected land/water arena; inspected traits can be mentioned.
    traits = []
    for creature in (left, right):
        p = creature.get("profile") or {}
        if p.get(
            "verification_status"
        ) == "verified" or "physical_characteristics" in p.get("reviewed_fields", {}):
            supported = p.get("physical_characteristics", [])
            if supported and not re.search(
                r"\b(gore|dismemberment|bleeding|suffering|death|dies)\b",
                supported[0],
                re.I,
            ):
                traits.append(
                    f"Remember {creature['name']}: {supported[0][:180].rstrip('.')}."
                )
    actions = [
        f"{a} makes a bold move. {b} turns just in time. Neither gives up!",
        f"{b} moves into the lead, but {a} finds an opening. The contest changes in a heartbeat!",
        "A sudden turn changes everything! For a moment, the finish seems far away. Then a clever new path appears.",
        "One contender holds a steady position. The other tries a daring approach. Who can find the final opening?",
        "The moon lights the path ahead. A quick dodge brings a surprising chance, and the adventure grows even closer.",
        "Both pause, then move again. Patience meets courage in this friendly contest. One final challenge remains.",
        "A narrow opening appears. The challengers must choose carefully. A strong start matters, but a clever finish can change the story.",
        "The arena feels quiet for one heartbeat. Then the contest springs to life again. Both creatures try their very best.",
    ]
    rng.shuffle(actions)
    # Every length includes setting, both introductions, confrontation and reversal.
    core = [
        intro,
        *traits[:1],
        actions[0],
        "But wait! The lead changes, and a surprising dodge keeps the challenge alive.",
    ]
    transition = (
        "The champion can rest beneath the stars. Our seven-chapter adventure is complete."
        if number == 7
        else "Another chapter waits along the moonlit trail."
    )
    ending = (
        f"With one decisive move, {winner['name']} takes the winning position! {loser['name']} retreats safely. "
        + (
            f"{winner['name']} is our champion! "
            if number == 7
            else f"{winner['name']} advances. "
        )
        + transition
    )
    target = words or round(
        settings["duration_seconds"] * 2.15 * settings.get("speech_rate", 1)
    )
    # Compact complete scenes when the full introduction does not fit. Add
    # varied whole clauses measured by word count only as a starting estimate.
    if len((" ".join(core) + " " + ending).split()) > target + 3:
        start = (
            "Six completed battles brought us here. "
            if number == 7
            else f"After Chapter {previous[-1]['chapter_number']}, "
            if refs
            else ""
        )
        core = [
            start + f"{a} meets {b} in the {place}.",
            rng.choice(
                [
                    "A bold move! But wait, a quick turn changes the lead.",
                    "One challenger takes the lead. A surprising maneuver opens another path!",
                    "The first approach seems certain. Then a clever turn changes everything!",
                    "They close in carefully. Suddenly, a daring dodge turns the contest around!",
                ]
            ),
            *traits[:1],
        ]
        ending = (
            f"{winner['name']} finds the opening and wins! {loser['name']} retreats safely. "
            + (
                "Our champion is here. Sweet dreams!"
                if number == 7
                else "The next chapter awaits!"
            )
        )
    additions = actions + [
        "One more chance appears.",
        "The challengers watch carefully.",
        "A brave new plan begins.",
        "The moon shines above.",
        "Each careful move matters.",
        "The adventure grows closer.",
        "Both stand ready.",
        "Everything changes.",
        "What courage!",
    ]
    rng.shuffle(additions)
    for sentence in additions:
        count = len((" ".join(core) + " " + ending).split())
        if count >= target - 2:
            break
        if count + len(sentence.split()) <= target + 2:
            core.append(sentence)
    for sentence in (
        "The stars shine overhead.",
        "Both challengers gather courage.",
        "The contest holds another surprise.",
        "What a moment!",
    ):
        count = len((" ".join(core) + " " + ending).split())
        if count >= target - 2:
            break
        if count + len(sentence.split()) <= target + 2:
            core.append(sentence)
    if settings.get("tone") == "gentle":
        core[0] = "Under the gentle moonlight, " + core[0][0].lower() + core[0][1:]
    if simulation["environment"]["arena"] == "neutral":
        core.insert(
            0,
            "This is a make-believe arena. Each creature stays safely in its own habitat.",
        )
    result = Narrative(
        title=("The Championship: " if number == 7 else f"Chapter {number}: ")
        + f"{a} and {b}",
        paragraphs=core,
        ending=ending,
        winner_id=winner["id"],
        participant_names=[a, b],
        summary=f"{winner['name']} won in the {place}; {loser['name']} retreated safely.",
        key_events=["A bold opening", "The lead reversed", "A safe decisive finish"],
        transition=transition,
        chapter_number=number,
        references=refs,
    )
    validate(result, simulation, number, previous)
    return result.model_dump()


def validate(result, simulation, number, previous):
    if result.winner_id != simulation["winner_id"] or result.chapter_number != number:
        raise ValueError("Narrative cannot change the persisted simulation")
    text = " ".join([*result.paragraphs, result.ending])
    if any(name not in text for name in result.participant_names):
        raise ValueError("Narrative omitted a competing creature")
    for ref in re.findall(r"\bChapter\s+(\d+)", text):
        if int(ref) > number:
            raise ValueError("Narrative refers to a future chapter")
    if any(
        ref >= number or ref not in {p["chapter_number"] for p in previous}
        for ref in result.references
    ):
        raise ValueError("Narrative references an uncompleted or future chapter")
