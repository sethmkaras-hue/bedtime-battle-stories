"""Explicit authenticated decisions over bounded staged data, not arbitrary JSON/files."""

from datetime import date
import json
import re
from pathlib import Path
import sqlite3
from app import library


def safe_file(folder, relative):
    if (
        not isinstance(relative, str)
        or re.fullmatch(
            r"(?:originals/[0-9a-f]{64}\.image|previews/[0-9a-f]{64}\.webp)", relative
        )
        is None
    ):
        raise ValueError("Only staged image files can be accessed")
    folder = Path(folder).resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise ValueError("Staged file is missing or invalid; rerun the importer")
    return path


def approve(db, store, pid, scopes, image_index=0, pron_edits=None):
    from .persistence import (
        pending,
        ContentError,
        science_update,
        image_update,
        persist,
    )

    row = pending(store, pid)
    proposal = json.loads(row["payload"])
    if not scopes:
        raise ContentError("Choose the updates you inspected before approving")
    if set(scopes) & set(store.applied(pid)):
        raise ContentError(
            "Some selected updates are already applied; refresh the review queue",
            code="proposal_conflict",
            status=409,
        )
    if not set(scopes) <= {"science", "image", "pronunciation"}:
        raise ContentError("Unsupported approval scope")
    with sqlite3.connect(db) as conn:
        current = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE stable_key=?",
            (row["stable_key"],),
        ).fetchone()
    record = json.loads(current[0]) if current else proposal["record"]
    updated = json.loads(json.dumps(record))
    changed = []
    if "science" in scopes:
        updated = science_update(updated, proposal, manual=True)
        changed.append("science")
    if "pronunciation" in scopes:
        candidate = proposal.get("pronunciation")
        if not candidate:
            raise ContentError("No sourced pronunciation proposal to approve")
        pron = {
            k: v
            for k, v in candidate.items()
            if k in {"phonetic", "stress", "tts_text", "source_url", "alternatives"}
        }
        pron.update(pron_edits or {})
        pron.update(
            status="verified",
            verified_by="parent-review",
            checked_on=date.today().isoformat(),
        )
        updated["pronunciation"] = library.Pronunciation.model_validate(
            pron
        ).model_dump(mode="json")
        changed.append("pronunciation")
    if "image" in scopes:
        images = proposal.get("images", [])
        if not 0 <= image_index < len(images):
            raise ContentError(
                "Choose an available image candidate",
                issues=[
                    {
                        "loc": ["image_index"],
                        "msg": "Image index is outside this proposal",
                        "type": "image_index_invalid",
                    }
                ],
            )
        updated = image_update(
            updated, images[image_index], store.root, pid, manual=True
        )
        changed.append("image")
    updated["import_stage"] = "manually_reviewed"
    result = persist(
        db, updated, record, manual=True, operation="parent_approval", proposal_id=pid
    )
    store.complete(pid, changed, "parent_approval")
    return {
        "approved": pid,
        "fields": changed,
        "profile_verification": updated["verification_status"],
        "backup_created": result["backup_created"],
        "remaining_scopes": store.remaining(pid),
        "audio_note": "Run IMPORT_CREATURE_LIBRARY.sh --all --generate-audio or GENERATE_PRONUNCIATIONS.sh after approving guidance.",
    }
