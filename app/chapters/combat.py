"""Non-graphic combat choreography; never writes scientific creature profiles.

Named anatomical constraints cover the genera used in the user's examples.
Unknown animals use body contact, not invented horns, claws or tail clubs.
"""

import re

EDITORIAL = {
    "tyrannosaurus": "bite",
    "allosaurus": "bite",
    "giganotosaurus": "bite",
    "spinosaurus": "bite",
    "triceratops": "horns",
    "styracosaurus": "horns",
    "centrosaurus": "horns",
    "pentaceratops": "horns",
    "stegosaurus": "spiked_tail",
    "ankylosaurus": "club",
    "euoplocephalus": "club",
    "velociraptor": "claws",
    "deinonychus": "claws",
    "utahraptor": "claws",
}


def ability(creature):
    if creature.get("category") == "shark":
        return "bite"
    profile = creature.get("profile") or {}
    reviewed = profile.get("verification_status") == "verified"
    evidence = []
    for field in ("physical_characteristics", "offensive_adaptations"):
        if reviewed or field in profile.get("reviewed_fields", {}):
            evidence.extend(profile.get(field, []))
    literal = " ".join(evidence).lower()
    if not re.search(r"\b(no|without|lacks|absent)\b", literal):
        for token, key in [
            ("tail club", "club"),
            ("spiked tail", "spiked_tail"),
            ("horn", "horns"),
            ("claw", "claws"),
            ("jaws", "bite"),
            ("teeth", "bite"),
        ]:
            if token in literal:
                return key
    genus = (
        (
            profile.get("scientific_name")
            or creature.get("scientific_name")
            or creature["name"]
        )
        .split()[0]
        .lower()
    )
    return EDITORIAL.get(genus, "body")


def attack(actor, target, rng, gentle=False):
    kind = ability(actor)
    water = actor.get("habitat") == "marine"
    legs = target.get("habitat") == "land" and target.get("category") == "dinosaur"
    area = "legs" if legs else "side"
    phrases = {
        "bite": [
            "bites the rival's side",
            "chomps the rival's shoulder"
            if legs
            else "bites the rival's fin"
            if target.get("category") == "shark"
            else "snaps onto the rival's side",
        ],
        "horns": [
            "drives its horns into the rival's side",
            "charges, striking the rival with its horns",
        ],
        "spiked_tail": [
            f"whips its spiked tail into the rival's {area}",
            f"swings its tail spikes against the rival's {area}",
        ],
        "club": [
            f"slams its tail club into the rival's {area}",
            f"swings its heavy tail club at the rival's {area}",
        ],
        "claws": [
            "rakes its claws across the rival's flank",
            "slashes the rival's side with its claws",
        ],
        "body": [
            "rams the rival's side",
            "slams its shoulder into the rival"
            if not water
            else "strikes the rival with its body",
        ],
    }
    effect = "; the rival reels" if water else "; the rival staggers"
    if not gentle:
        effect = rng.choice(
            [
                effect,
                ", leaving a bruise",
                ", leaving a small cut"
                if kind in {"claws", "horns", "spiked_tail", "bite"}
                else ", knocking the rival off balance",
            ]
        )
    return rng.choice(phrases[kind]) + effect


def finish(winner, loser, environment, rng):
    if environment["arena"] == "neutral":
        return f"{winner['name']} strikes from the shoreline edge; {loser['name']} pulls away. {winner['name']} wins!"
    water = environment["arena"] == "water"
    tactic = (
        rng.choice(["dives under the rush", "turns sharply around the attack"])
        if water
        else rng.choice(
            [
                "sidesteps the rush",
                "ducks inside the guard",
                "uses cover to strike from the side",
            ]
            if environment["condition"] == "cover"
            else ["sidesteps the rush", "turns inside the attack"]
        )
    )
    weapon = ability(winner)
    blow = {
        "bite": "bites the rival's side",
        "horns": "lands a horn strike",
        "club": "lands a tail-club strike",
        "spiked_tail": "lands a spiked-tail strike",
        "claws": "lands a claw strike",
        "body": "slams into the rival",
    }[weapon]
    retreat = "swims away wounded" if water else "limps away"
    return f"{winner['name']} {tactic}, then {blow}! The rival {retreat}. {winner['name']} wins!"


def short_attack(actor, target):
    part = "legs" if target.get("habitat") == "land" else "side"
    return {
        "bite": "bites the rival's side",
        "horns": "strikes with its horns",
        "club": f"clubs the rival's {part}",
        "spiked_tail": f"whips tail spikes into the rival's {part}",
        "claws": "claws the rival's flank",
        "body": "rams the rival's side",
    }[ability(actor)]
