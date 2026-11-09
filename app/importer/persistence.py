"""One validated persistence boundary for manual approvals and automatic imports."""

from datetime import date
import hashlib
import json
import logging
import sqlite3
from pydantic import ValidationError
from app import library
from .store import backup


class ContentError(ValueError):
    def __init__(self, message, *, code="invalid_content", status=422, issues=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.issues = issues or [{"loc": ["content"], "msg": message, "type": code}]


def issues(error):
    if isinstance(error, ContentError):
        return error.issues
    if isinstance(error, ValidationError):
        return [{k: e[k] for k in ("loc", "msg", "type")} for e in error.errors()]
    return [{"loc": ["content"], "msg": str(error), "type": "invalid_content"}]


def failure(error, *, operation, record=None, proposal_id=None):
    context = {
        "operation": operation,
        "proposal_id": proposal_id,
        "creature": (record or {}).get("display_name"),
        "stable_key": (record or {}).get("stable_key"),
        "issues": issues(error),
    }
    logging.getLogger(__name__).warning(
        "Creature import failed: %s", json.dumps(context)
    )
    return context


def pending(store, pid):
    row = store.get(pid)
    if not row:
        raise ContentError("Proposal not found", code="proposal_not_found", status=404)
    if row["status"] != "pending":
        raise ContentError(
            "Proposal already decided; refresh the review queue",
            code="proposal_conflict",
            status=409,
        )
    return row


def science_update(record, proposal, manual=False):
    updated = json.loads(json.dumps(record))
    patch = json.loads(json.dumps(proposal.get("science", {})))
    if not set(patch) <= library.SCIENCE_FIELDS:
        raise ContentError("Unsupported scientific proposal field")
    if not patch or not proposal.get("evidence"):
        raise ContentError("No source-supported scientific fields to apply")
    if not manual:
        if record["verification_status"] == "verified":
            return updated
        patch = {
            k: v for k, v in patch.items() if k not in record.get("reviewed_fields", {})
        }
    updated.update(patch)
    refs = {s["id"]: s for s in updated["sources"]}
    ids = {}
    for evidence in proposal["evidence"]:
        source = {
            k: v
            for k, v in evidence.items()
            if k in {"id", "title", "url", "publisher", "supports", "retrieved_on"}
        }
        identity = {k: v for k, v in source.items() if k != "retrieved_on"}
        suffix = hashlib.sha256(
            json.dumps(
                {"source": identity, "science": proposal["science"]}, sort_keys=True
            ).encode()
        ).hexdigest()[:12]
        original = source["id"]
        source["id"] = original + ("-review-" if manual else "-") + suffix
        ids[original] = source["id"]
        if manual:
            source["checked_on"] = date.today().isoformat()
        refs.setdefault(source["id"], source)
    for field in ("length", "weight"):
        if field in patch and updated[field] is not None:
            updated[field]["source_ids"] = [
                ids.get(s, s) for s in updated[field]["source_ids"]
            ]
    updated["sources"] = list(refs.values())
    if manual:
        for field in patch:
            updated.setdefault("reviewed_fields", {})[field] = {
                "reviewer": "parent-review",
                "checked_on": date.today().isoformat(),
            }
    updated["import_stage"] = (
        "manually_reviewed"
        if manual or record.get("import_stage") == "manually_reviewed"
        else "source_supported"
    )
    return updated


def image_update(record, candidate, folder, pid, manual=False):
    from .review import safe_file
    from scripts.prepare_image import prepare

    if not candidate.get("supported") or not candidate.get("original_file"):
        raise ContentError(
            "This candidate lacks supported identity/license/download evidence; it cannot be approved",
            issues=[
                {
                    "loc": ["image"],
                    "msg": "Resolve exact identity, license and original file evidence before publication",
                    "type": "image_evidence_missing",
                }
            ],
        )
    source = safe_file(folder, candidate["original_file"])
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != candidate.get("sha256"):
            raise ContentError(
                "Staged image checksum changed; rerun source acquisition"
            )
    metadata = {
        k: v
        for k, v in candidate.items()
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
        modifications="Locally acquired source; no alteration of taxon identity",
        verified_by="parent-review" if manual else "automated-import:v1",
        checked_on=date.today().isoformat(),
        approval_method="manual" if manual else "automated",
    )
    # Validate licensing/taxon before writing any published derivatives.
    parsed = library.Image.model_validate(metadata)
    if library.normalize(parsed.identified_taxon) != library.normalize(
        record["scientific_name"]
    ):
        raise ContentError(
            "Image identification must match the recorded taxon, not a related species"
        )
    if not manual:
        from .sources import image_candidate

        labels = {
            "CC0-1.0": "CC0",
            "Public-Domain": "Public domain",
            "CC-BY-4.0": "CC BY 4.0",
            "CC-BY-SA-4.0": "CC BY-SA 4.0",
            "CC-BY-3.0": "CC BY 3.0",
            "CC-BY-SA-3.0": "CC BY-SA 3.0",
        }
        info = {
            "url": candidate.get("download_url"),
            "descriptionurl": candidate.get("original_source_url"),
            "extmetadata": {
                k: {"value": v or ""}
                for k, v in {
                    "Artist": candidate.get("creator"),
                    "LicenseShortName": labels.get(candidate.get("license")),
                    "LicenseUrl": candidate.get("license_url"),
                    "ImageDescription": candidate.get("description"),
                }.items()
            },
        }
        checked = image_candidate(
            info,
            {},
            set(),
            None,
            record["scientific_name"],
            record["category"] == "shark" and record.get("modern_status") != "extinct",
            source_kind=candidate.get("source_kind", "commons"),
        )
        if not checked["supported"]:
            raise ContentError(
                "Automatic image identity/license screening failed",
                issues=[
                    {"loc": ["image"], "msg": reason, "type": "image_evidence_invalid"}
                    for reason in checked["issues"]
                ],
            )
    if not manual and (
        not candidate.get("description")
        or not candidate.get("identity_evidence")
        or candidate.get("issues")
    ):
        raise ContentError(
            "Automatic image publication requires complete identity evidence and no unresolved issues"
        )
    updated = json.loads(json.dumps(record))
    updated["image"] = prepare(source, metadata, "import-" + str(pid))
    if updated.get("import_stage") != "manually_reviewed":
        updated["import_stage"] = "source_supported"
    return updated


def persist(
    db,
    record,
    original,
    *,
    manual=False,
    operation="automatic_import",
    proposal_id=None,
):
    try:
        parsed = library.validate_records([record])[0]
        if parsed.model_dump(mode="json") == library.CreatureRecord.model_validate(
            original
        ).model_dump(mode="json"):
            return {"changed": False, "backup_created": False}
        asset_only = not manual and operation == "automatic_image"
        if asset_only and parsed.model_dump(
            mode="json", exclude={"image", "import_stage"}
        ) != library.CreatureRecord.model_validate(original).model_dump(
            mode="json", exclude={"image", "import_stage"}
        ):
            raise ContentError(
                "Automatic image import cannot change scientific or pronunciation fields"
            )
        saved = backup(db)
        with sqlite3.connect(db, timeout=5) as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute(
                "SELECT record_json FROM creature_profiles WHERE stable_key=?",
                (parsed.stable_key,),
            ).fetchone()
            if (latest is None and original.get("id") is not None) or (
                latest and json.loads(latest[0]) != original
            ):
                raise ContentError(
                    "Record changed during import/review; reload and inspect it again",
                    code="record_conflict",
                    status=409,
                )
            result = library.import_records(
                conn,
                [parsed.model_dump(mode="json")],
                allow_reviewed_updates=manual or asset_only,
            )
        return {
            "changed": bool(result["inserted"] + result["updated"]),
            "backup_created": saved is not None,
        }
    except sqlite3.IntegrityError as error:
        wrapped = ContentError(
            "Database identity constraint rejected the update",
            code="database_conflict",
            status=409,
            issues=[
                {"loc": ["database"], "msg": str(error), "type": "database_constraint"}
            ],
        )
        failure(wrapped, operation=operation, record=record, proposal_id=proposal_id)
        raise wrapped from error
    except sqlite3.OperationalError as error:
        wrapped = ContentError(
            "Database is unavailable or busy; retry after checking server logs",
            code="database_unavailable",
            status=503,
        )
        failure(wrapped, operation=operation, record=record, proposal_id=proposal_id)
        raise wrapped from error
    except (ValueError, KeyError, OSError) as error:
        failure(error, operation=operation, record=record, proposal_id=proposal_id)
        raise
