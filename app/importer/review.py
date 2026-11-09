"""Explicit authenticated decisions over bounded staged data, not arbitrary JSON/files."""

from datetime import date
import json
import re
import hashlib
from pathlib import Path
import sqlite3
from app import library
from .store import backup


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
    row = store.get(pid)
    if not row or row["status"] != "pending":
        raise ValueError("Proposal is not pending")
    proposal = json.loads(row["payload"])
    if not scopes:
        raise ValueError("Choose the updates you inspected before approving")
    with sqlite3.connect(db) as conn:
        current = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE stable_key=?",
            (row["stable_key"],),
        ).fetchone()
    record = json.loads(current[0]) if current else proposal["record"]
    updated = json.loads(json.dumps(record))
    stamp = {"reviewer": "parent-review", "checked_on": date.today().isoformat()}
    changed = []
    if "science" in scopes:
        if not proposal["science"] or not proposal["evidence"]:
            raise ValueError("No source-supported scientific fields to approve")
        for field, value in proposal["science"].items():
            if field not in {
                "taxon_rank",
                "subcategory",
                "time_period",
                "geographic_distribution",
                "diet",
                "length",
                "weight",
                "modern_status",
                "habitat",
            }:
                raise ValueError("Unsupported scientific proposal field")
            updated[field] = value
            updated.setdefault("reviewed_fields", {})[field] = stamp
            changed.append(field)
        sources = {s["id"]: s for s in updated["sources"]}
        source_ids = {}
        for evidence in proposal["evidence"]:
            source = {
                k: v
                for k, v in evidence.items()
                if k in {"id", "title", "url", "publisher", "supports", "retrieved_on"}
            }
            suffix = hashlib.sha256(
                json.dumps(
                    {"source": evidence, "science": proposal["science"]}, sort_keys=True
                ).encode()
            ).hexdigest()[:12]
            source_ids[source["id"]] = source["id"] + "-review-" + suffix
            source["id"] = source_ids[source["id"]]
            source["checked_on"] = date.today().isoformat()
            sources[source["id"]] = source
        updated["sources"] = list(sources.values())
        for field in ("length", "weight"):
            if field in proposal["science"] and updated[field] is not None:
                updated[field]["source_ids"] = [
                    source_ids.get(s, s) for s in updated[field]["source_ids"]
                ]
    if "pronunciation" in scopes:
        candidate = proposal.get("pronunciation")
        if not candidate:
            raise ValueError("No sourced pronunciation proposal to approve")
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
            raise ValueError("Choose an image candidate")
        image = images[image_index]
        if not image.get("supported") or not image.get("original_file"):
            raise ValueError(
                "This candidate lacks supported identity/license/download evidence; it cannot be approved"
            )
        source = safe_file(store.root, image["original_file"])
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != image.get("sha256"):
                raise ValueError(
                    "Staged image checksum changed; rerun source acquisition"
                )
        # The parent has inspected the evidence and preview. Conversion happens
        # only for this approved licensed image; no source HTML becomes executable.
        from scripts.prepare_image import prepare

        metadata = {
            k: v
            for k, v in image.items()
            if k
            in {
                "creator",
                "original_source_url",
                "license",
                "license_url",
                "attribution",
                "identified_taxon",
            }
        }
        metadata.update(
            placeholder=False,
            path="/static/creatures/pending.webp",
            modifications="Source downloaded without altering species identity",
            verified_by="parent-review",
            checked_on=date.today().isoformat(),
        )
        updated["image"] = prepare(source, metadata, "import-" + str(pid))
        changed.append("image")
    updated["import_stage"] = "manually_reviewed"
    # Approving a partial scientific update is not an assertion that the entire
    # encyclopedia profile (all facts, traits, measurements) is verified.
    parsed = library.CreatureRecord.model_validate(updated)
    library.validate_records([parsed.model_dump(mode="json")])
    saved = backup(db)
    with sqlite3.connect(db, timeout=5) as conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE stable_key=?",
            (row["stable_key"],),
        ).fetchone()
        if current and (latest is None or latest[0] != current[0]):
            raise ValueError(
                "Record changed during review; reload and inspect it again"
            )
        if current:
            parsed.id = record["id"]
            conn.execute(
                "UPDATE creature_profiles SET record_json=?,protected=? WHERE stable_key=?",
                (
                    parsed.model_dump_json(),
                    int(parsed.verification_status == "verified"),
                    parsed.stable_key,
                ),
            )
            if record["pronunciation"] != parsed.pronunciation.model_dump(mode="json"):
                conn.execute(
                    "DELETE FROM pronunciation_assets WHERE creature_id=?",
                    (record["id"],),
                )
        else:
            library.import_records(conn, [parsed.model_dump(mode="json")])
    store.decide(pid, "approved")
    return {
        "approved": pid,
        "fields": changed,
        "profile_verification": parsed.verification_status,
        "backup_created": saved is not None,
        "audio_note": "Run IMPORT_CREATURE_LIBRARY.sh --all --generate-audio or GENERATE_PRONUNCIATIONS.sh after approving guidance.",
    }
