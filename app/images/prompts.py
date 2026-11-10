"""Use identity and inspected scientific details; never promote editorial guesses."""

import hashlib

VERSION = 1
STYLE = (
    "Highly detailed natural history encyclopedia illustration, scientifically grounded prehistoric wildlife reconstruction, "
    "realistic anatomy, finely detailed textures, natural colors, professional paleoart, museum-quality educational illustration, "
    "beautiful natural environment, full-body composition, realistic proportions, detailed lighting, sharp focus."
)
NEGATIVE = (
    "cartoon, anthropomorphic, fantasy monster, movie character, fictional anatomy, extra limbs, missing limbs, "
    "severed body parts, blood, gore, violence, text, labels, borders, watermark, multiple unrelated animals, cropped body, blurry"
)


def prompt(record):
    reviewed = record.get("verification_status") == "verified"
    inspected = record.get("reviewed_fields", {})
    details = []
    for field in (
        "physical_characteristics",
        "description",
        "time_period",
        "geographic_distribution",
    ):
        if not reviewed and field not in inspected:
            continue
        value = record.get(field)
        if isinstance(value, list):
            details.extend(str(item)[:180] for item in value[:6])
        elif value:
            details.append(str(value)[:350])
    group = record["category"]
    context = (
        "one whole animal in a natural terrestrial setting"
        if group == "dinosaur"
        else "one whole animal in a natural underwater setting"
    )
    subject = record["scientific_name"]
    positive = (
        f"{subject}. {context}. "
        + ("Source-supported details: " + "; ".join(details) + ". " if details else "")
        + STYLE
    )
    positive += " Single creature, entire body visible. No speculative added anatomy or movie styling."
    return {
        "prompt": positive,
        "negative_prompt": NEGATIVE,
        "prompt_version": VERSION,
        "scientific_basis": "inspected_profile_fields"
        if details
        else "identity_only_no_verified_anatomical_details",
        "scientific_details": details,
        "accuracy_verified": False,
    }


def seed_for(record, base=42):
    return (
        base + int(hashlib.sha256(record["stable_key"].encode()).hexdigest()[:8], 16)
    ) % (2**31)
