"""Structured local narrative variants follow an already persisted simulation."""

import random
import re

from pydantic import BaseModel, ConfigDict, Field

from . import combat

VERSION = 2


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
    combat_actions: list[str] = Field(default_factory=list)
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
    target = words or round(
        settings["duration_seconds"] * 2.15 * settings.get("speech_rate", 1)
    )
    # Keep continuity brief: never spend a short battle on a long introduction.
    prefix = (
        "Six completed battles. "
        if number == 7
        else f"After Chapter {previous[-1]['chapter_number']}, "
        if refs
        else ""
    )
    refs = refs[-1:] if refs else []
    intro = prefix + f"{a} meets {b} in the {place}."
    first = combat.attack(left, right, rng, settings["tone"] == "gentle")
    counter = combat.attack(right, left, rng, settings["tone"] == "gentle")
    core = [intro, f"{a} {first}! {b} counters and {counter}!"]
    decisive = combat.finish(winner, loser, simulation["environment"], rng)
    transition = (
        "Our champion! Sweet dreams." if number == 7 else "On to the next chapter!"
    )
    ending = decisive + " " + transition
    # Whole action clauses can expand a longer requested take; no silence padding
    # or rate acceleration. Shortening retains both attacks and a tactical finish.
    if target < 55:
        opening = rng.choice(
            [f"In the {place}!", f"At the {place}, they clash!", f"The {place} shakes!"]
        )
        exchange = rng.choice(
            [
                f"{a} {combat.short_attack(left, right)}! {b} {combat.short_attack(right, left)}, leaving a bruise!",
                f"{b} {combat.short_attack(right, left)}! {a} counters and {combat.short_attack(left, right)}. A bruise darkens!",
            ]
        )
        core = [prefix + opening, exchange]
        water = simulation["environment"]["arena"] == "water"
        move = (
            rng.choice(["dives under the rush", "turns sharply"])
            if water
            else rng.choice(["sidesteps", "turns inside the attack"])
        )
        tactic = move + " and " + combat.short_attack(winner, loser)
        retreat = "The wounded rival swims off." if water else "The rival limps away."
        ending = f"{winner['name']} {tactic} and wins! {retreat}" + (
            " Champion!" if number == 7 else ""
        )
    additions = [
        f"{a} lunges again, but {b} twists out of reach.",
        "A fierce counterattack turns the fight around.",
        "The next impact sends both challengers reeling.",
        "One more strike bruises the rival, but the fight continues.",
        "Both recover their balance and clash again.",
        "The rival guards its sore side and turns sharply.",
        "A hard collision changes the angle of the fight.",
        "A quick feint draws a counterattack into empty space.",
        "The challengers press closer, looking for an opening.",
        "Another daring strike sends the rival stumbling."
        if simulation["environment"]["arena"] == "land"
        else "Another daring strike sends the rival reeling.",
        "A narrow opening appears.",
        "The attack comes fast.",
        "A bold counter lands.",
    ]
    rng.shuffle(additions)
    for sentence in additions:
        count = len((" ".join(core) + " " + ending).split())
        if count >= target - 2:
            break
        if count + len(sentence.split()) <= target + 2:
            core.append(sentence)
    for sentence in (
        "The challengers clash again.",
        "Another hard strike lands.",
        "The fight turns!",
    ):
        count = len((" ".join(core) + " " + ending).split())
        if count >= target - 2:
            break
        if count + len(sentence.split()) <= target + 2:
            core.append(sentence)
    if simulation["environment"]["arena"] == "neutral":
        core.insert(
            0,
            "In this make-believe shoreline arena, each creature stays in its own habitat.",
        )
    result = Narrative(
        title=("The Championship: " if number == 7 else f"Chapter {number}: ")
        + f"{a} and {b}",
        paragraphs=core,
        ending=ending,
        winner_id=winner["id"],
        participant_names=[a, b],
        summary=f"{winner['name']} won in the {place}; {loser['name']} retreated after physical attacks.",
        key_events=[first, counter, decisive],
        combat_actions=[first, counter, decisive],
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
