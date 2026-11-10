"""Use identity and inspected scientific details; never promote editorial guesses."""

import hashlib
import re

VERSION = 2
STYLE = (
    "natural history encyclopedia illustration, realistic anatomy, natural colors, professional paleoart"
)

NEGATIVE = (
    "cartoon, anthropomorphic, fantasy monster, movie character, fictional anatomy, extra limbs, missing limbs, "
    "severed body parts, blood, gore, violence, text, labels, borders, watermark, multiple unrelated animals, cropped body, blurry"
)


def prompt(record):
    reviewed = record.get("verification_status") == "verified"
    inspected = record.get("reviewed_fields", {})
    details = []
    environment_details = []
    for field in (
        "physical_characteristics",
        "description",
        "time_period",
        "geographic_distribution",
    ):
        if not reviewed and field not in inspected:
            continue
        value = record.get(field)
        target = (
            details
            if field in {"physical_characteristics", "description"}
            else environment_details
        )
        if isinstance(value, list):
            target.extend(str(item)[:180] for item in value[:6])
        elif value:
            target.append(str(value)[:350])
    subject = record["scientific_name"]
    components = components_for(subject, details, record["category"], environment_details)
    return {
        "prompt": ". ".join(components),
        "prompt_components": components,
        "negative_prompt": NEGATIVE,
        "prompt_version": VERSION,
        "scientific_basis": "inspected_profile_fields"
        if details or environment_details
        else "identity_only_no_verified_anatomical_details",
        "scientific_details": details + environment_details,
        "accuracy_verified": False,
    }


def components_for(subject, details, category=None, environment_details=()):
    """Order matters: later components yield to earlier scientific information."""
    environment = (
        "natural terrestrial setting"
        if category == "dinosaur"
        else "natural underwater setting"
        if category in {"shark", "marine_reptile"}
        else "natural habitat"
    )
    return [
        subject,
        *details,
        "Single creature, full-body composition, entire body visible",
        STYLE,
        environment,
        *environment_details,
        "natural lighting, sharp focus",
    ]


def token_ids(tokenizer, text, special=True):
    # Counting deliberately accepts over-budget candidates without issuing the
    # tokenizer's model-length warning. Only validated text reaches the encoder.
    return tokenizer.encode(
        text, add_special_tokens=special, truncation=False, verbose=False
    )


def fit_components(tokenizer, components, limit, required_first=False):
    """Keep higher-priority clauses; shorten only the last retained clause.

    Whitespace boundaries select readable candidates, but every decision uses
    actual tokenizer IDs (including BOS/EOS), never a word/character estimate.
    """
    final = ""
    for index, component in enumerate(components):
        component = str(component).strip()
        if not component:
            continue
        separator = ". " if final else ""
        candidate = final + separator + component
        if len(token_ids(tokenizer, candidate)) <= limit:
            final = candidate
            continue
        if required_first and index == 0:
            raise ValueError("Scientific creature name exceeds the CLIP token budget")
        # Scan backwards, rather than assuming BPE length is monotonic in text.
        for boundary in reversed(list(re.finditer(r"\s+", component))):
            shortened = component[:boundary.start()].rstrip(" ,;.")
            candidate = final + separator + shortened
            if shortened and len(token_ids(tokenizer, candidate)) <= limit:
                final = candidate
                break
        break
    count = len(token_ids(tokenizer, final))
    if count > limit:
        raise ValueError("Final prompt exceeds the CLIP token budget")
    return final, count


def fit_prompts(settings, tokenizer, encoder_limit):
    """Budget against both the loaded tokenizer and encoder, with specials."""
    limit = min(int(tokenizer.model_max_length), int(encoder_limit))
    specials = tokenizer.num_special_tokens_to_add(pair=False)
    if limit <= specials:
        raise ValueError("CLIP token budget has no room after special tokens")
    components = settings.get("prompt_components")
    if not components:
        # Version-1 queued jobs remain resumable. Their identity/evidence is
        # already persisted, so rebuild priority order without guessing facts.
        subject = settings.get("scientific_name")
        if not subject:
            raise ValueError("Queued image is missing its scientific creature name")
        components = components_for(subject, settings.get("scientific_details", []))
    positive, positive_count = fit_components(
        tokenizer, components, limit, required_first=True
    )
    negative, negative_count = fit_components(
        tokenizer, settings["negative_prompt"].split(","), limit
    )
    return {
        "prompt": positive,
        "negative_prompt": negative,
        "prompt_token_count": positive_count,
        "negative_prompt_token_count": negative_count,
        "prompt_token_limit": limit,
        "prompt_special_tokens": specials,
        "prompt_budget_version": VERSION,
    }


def seed_for(record, base=42):
    return (
        base + int(hashlib.sha256(record["stable_key"].encode()).hexdigest()[:8], 16)
    ) % (2**31)
