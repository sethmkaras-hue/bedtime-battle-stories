"""Seeded game simulation. Numerical estimates are game rules, not animal facts."""

import hashlib
import math
import random

VERSION = 2
ARENAS = {
    "neutral": [("Make-believe shore-and-water arena", "neutral")],
    "land": [
        ("Prehistoric forest", "cover"),
        ("Open floodplain", "open"),
        ("Riverbank", "edge"),
    ],
    "water": [
        ("Coastal shallows", "cover"),
        ("Open ocean", "open"),
        ("Rocky shoreline", "edge"),
    ],
}


def inputs(creature):
    profile = creature.get("profile") or {}
    reviewed = profile.get("verification_status") == "verified"
    stamps = profile.get("reviewed_fields", {})
    result = {"creature_id": creature["id"], "documented": {}, "game_estimates": {}}
    for field in ("length", "weight"):
        value = profile.get(field) or {}
        if (
            (reviewed or field in stamps)
            and value.get("minimum")
            and value.get("maximum")
        ):
            result["documented"][field] = (value["minimum"] + value["maximum"]) / 2
    # Existing editorial game rating is used uniformly, never species-name rules.
    rating = min(10, max(1, float(creature.get("gameplay_rating", 3))))
    physical = " ".join(profile.get("physical_characteristics", []) if reviewed else [])
    offense = " ".join(profile.get("offensive_adaptations", []) if reviewed else [])
    defense = " ".join(profile.get("defensive_adaptations", []) if reviewed else [])
    result["documented"]["traits"] = [v for v in (physical, offense, defense) if v]
    result["game_estimates"] = {
        "strength": rating,
        "agility": max(1, 6 - rating * 0.35),
        "weapons": min(
            2,
            sum(
                word in offense.lower()
                for word in ("jaws", "teeth", "horn", "claw", "tail club")
            )
            * 0.5,
        ),
        "defense": min(
            2,
            sum(
                word in defense.lower()
                for word in ("armor", "armour", "plate", "shell", "spine")
            )
            * 0.5,
        ),
        "habitat": creature.get("habitat"),
        "basis": "Fictional game model; not measured speed/strength",
    }
    return result


def _resolve(left, right, seed, arena, desired=None):
    rng = random.Random(seed)
    name, condition = rng.choice(ARENAS[arena])
    data = [inputs(left), inputs(right)]
    scores = []
    modifiers = []
    for item in data:
        game = item["game_estimates"]
        facts = item["documented"]
        size = (
            math.log1p(facts.get("weight", 0)) * 0.12
            + math.log1p(facts.get("length", 0)) * 0.25
        )
        modifier = (
            game["agility"] * 0.2
            if condition == "cover"
            else game["strength"] * 0.12
            if condition == "open"
            else 0.3
            if condition == "edge" and game["habitat"] == "semi_aquatic"
            else 0
        )
        score = (
            game["strength"] * 0.6
            + game["agility"] * 0.35
            + game["weapons"] * 0.2
            + game["defense"] * 0.3
            + size
            + modifier
        )
        scores.append(score)
        modifiers.append(modifier)
    probability = min(
        0.85, max(0.15, 1 / (1 + math.exp((scores[1] - scores[0]) / 0.9)))
    )
    draw = rng.random() if desired is None else None
    return {
        "version": VERSION,
        "seed": seed,
        "competitor_ids": [left["id"], right["id"]],
        "inputs": data,
        "environment": {
            "name": name,
            "arena": arena,
            "condition": condition,
            "fictional_contest": True,
            "scientifically_realistic": arena != "neutral",
            "habitat_note": "Each creature stays in its own habitat; this cross-habitat encounter is fictional"
            if arena == "neutral"
            else "Shared compatible habitat",
        },
        "modifiers": modifiers,
        "scores": scores,
        "left_win_probability": probability,
        "draw": draw,
        "winner_id": desired
        if desired is not None
        else left["id"]
        if draw < probability
        else right["id"],
        "winner_determination_method": "child_choice"
        if desired is not None
        else "simulation",
    }


def battle_seed(seed, number):
    return int.from_bytes(
        hashlib.sha256(f"chapter:{seed}:{number}".encode()).digest()[:8], "big"
    )


def simulate(left, right, seed, arena):
    return _resolve(left, right, seed, arena)


def chosen(left, right, seed, arena, desired):
    if desired not in {left["id"], right["id"]}:
        raise ValueError("Desired winner must be a competitor")
    return _resolve(left, right, seed, arena, desired)
