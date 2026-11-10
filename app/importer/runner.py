"""Online acquisition runs outside the web server; only bounded writes touch the app DB."""

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote, urlencode
from app import library
from . import sources
from .network import PoliteClient, SourceUnavailable, atomic, robots_enabled
from .store import Store, backup

PILOT = [
    "Tyrannosaurus",
    "Triceratops",
    "Stegosaurus",
    "Velociraptor",
    "Brachiosaurus",
    "Ankylosaurus",
    "Spinosaurus",
    "Diplodocus",
    "Parasaurolophus",
    "Allosaurus",
]
VERSION = 6


def digest(record, inputs=None):
    return hashlib.sha256(
        (
            str(VERSION)
            + json.dumps(record, sort_keys=True)
            + (json.dumps(inputs, sort_keys=True) if inputs else "")
        ).encode()
    ).hexdigest()


def preview_image(client, candidate, folder):
    response = client.get(candidate["download_url"], limit=20_000_000)
    return preview_bytes(response.content, candidate, folder)


def preview_bytes(content, candidate, folder):
    import warnings
    from PIL import Image, ImageOps

    sha = hashlib.sha256(content).hexdigest()
    original = folder / "originals" / (sha + ".image")
    atomic(original, content)
    preview = folder / "previews" / (sha + ".webp")
    preview.parent.mkdir(parents=True, exist_ok=True)
    if not preview.exists():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(original) as source:
                    if source.width * source.height > 25_000_000:
                        raise ValueError(
                            "Source image is too large for bounded processing"
                        )
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    image.thumbnail((640, 640))
                    temporary = preview.with_suffix(".part")
                    try:
                        image.save(temporary, format="WEBP", quality=85)
                        temporary.replace(preview)
                    finally:
                        temporary.unlink(missing_ok=True)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError(
                "Source image exceeds safe decoded-pixel limits"
            ) from error
    return {
        **candidate,
        "original_file": str(original.relative_to(folder)),
        "preview_file": str(preview.relative_to(folder)),
        "sha256": sha,
    }


def collect(
    client,
    record,
    folder,
    dry_run=False,
    pronunciation_index=None,
    museum_pages=False,
    pronunciation_references=None,
    use_wikidata=False,
    image_references=None,
    offline=False,
    source_images=True,
):
    patch, evidence, issues = (
        ({}, [], ["Offline mode: online source research skipped."])
        if offline
        else sources.science(client, record)
    )
    if museum_pages and not offline:
        museum, refs, errors = sources.museum_facts(client, record)
        patch.update(museum)
        evidence += refs
        issues += errors
    else:
        issues.append(
            "Museum/educational page acquisition needs a source-terms review; enable --allow-museum-pages after reviewing site terms."
        )
    pron = (pronunciation_references or {}).get(
        library.normalize(record["scientific_name"])
    )
    if pron is None and museum_pages and not offline:
        pron, errors = sources.pronunciation(client, record, pronunciation_index)
        issues += errors
    if pron is None:
        issues.append(
            "No sourced pronunciation guidance; supply --pronunciation-references or review permitted educational sources."
        )
    try:
        supplied = (image_references or {}).get(
            library.normalize(record["scientific_name"])
        )
        if supplied:
            from .image_files import candidates as from_files

            candidates = from_files(record, supplied, folder, dry_run)
        elif offline or not source_images:
            candidates = []
        else:
            candidates = (
                sources.images(client, record, use_wikidata=True)
                if use_wikidata
                else sources.images(client, record)
            )
        if not candidates and source_images:
            issues.append(
                "No Commons image candidates; retain the existing image or placeholder."
            )
    except (SourceUnavailable, ValueError, KeyError) as error:
        candidates = []
        issues.append(str(error))
    downloaded = 0
    for i, candidate in enumerate(candidates):
        if (
            candidate["supported"]
            and not candidate.get("original_file")
            and candidate.get("acquisition") != "supplied_image"
            and not dry_run
            and downloaded < 2
        ):
            try:
                candidates[i] = preview_image(client, candidate, folder)
                downloaded += 1
            except (SourceUnavailable, ValueError, OSError, ImportError) as error:
                candidate["issues"].append("Preview/download failed: " + str(error))
                candidate["supported"] = False
    return {
        "stable_key": record["stable_key"],
        "creature_id": record.get("id"),
        "scientific_name": record["scientific_name"],
        "display_name": record["display_name"],
        "science": patch,
        "evidence": evidence,
        "pronunciation": pron,
        "images": candidates,
        "issues": issues,
        "source_links": [
            sources.PBDB
            + "?"
            + urlencode({"name": record["scientific_name"], "vocab": "pbdb"}),
            sources.COMMONS
            + "?"
            + urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": record["scientific_name"],
                    "format": "json",
                }
            ),
        ]
        + (
            [
                "https://www.nhm.ac.uk/discover/dino-directory/"
                + quote(record["display_name"].lower(), safe="")
                + ".html"
            ]
            if record["category"] == "dinosaur"
            else []
        ),
        "record": record,
        "stage": "imported_candidates",
        "importer_version": VERSION,
    }


def apply_supported(db, record, proposal):
    from .persistence import science_update, persist

    if not proposal.get("science") or record["verification_status"] == "verified":
        return False
    updated = science_update(record, proposal)
    return persist(db, updated, record, operation="automatic_science")["changed"]


def publish_supported_image(db, record, proposal, store, pid):
    from .persistence import image_update, persist, failure

    row = store.get(pid)
    if not row or row["status"] != "pending":
        return False
    if "image" in store.applied(pid):
        return False
    if not record["image"]["placeholder"]:
        # Reconcile a crash after the canonical commit but before queue bookkeeping.
        image = record["image"]
        if image.get("approval_method") == "automated":
            for candidate in proposal.get("images", []):
                digest = candidate.get("sha256", "")[:16]
                if (
                    digest
                    and ("/import-" + str(pid) + "-" + digest + "/") in image["path"]
                    and image["original_source_url"]
                    == candidate.get("original_source_url")
                ):
                    library.validate_records([record])
                    store.complete(pid, ["image"], "automatic_image_reconciled")
                    break
        return False
    for candidate in proposal.get("images", []):
        if not candidate.get("supported") or not candidate.get("original_file"):
            continue
        try:
            updated = image_update(record, candidate, store.root, pid)
            result = persist(
                db, updated, record, operation="automatic_image", proposal_id=pid
            )
            store.complete(pid, ["image"], "automatic_image")
            return result["changed"]
        except (ValueError, KeyError, OSError) as error:
            context = failure(
                error, operation="automatic_image", record=record, proposal_id=pid
            )
            proposal["issues"].append(
                "Automatic image publication failed: "
                + "; ".join(issue["msg"] for issue in context["issues"])
            )
    return False


def current_record(db, key):
    with sqlite3.connect(db) as conn:
        return json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE stable_key=?", (key,)
            ).fetchone()[0]
        )


def execute(
    db,
    folder,
    pilot=None,
    all_records=False,
    dry_run=False,
    refresh=False,
    apply=True,
    client=None,
    pronunciation_index=None,
    progress=print,
    museum_pages=False,
    pronunciation_references=None,
    use_wikidata=False,
    image_references=None,
    offline=False,
    source_images=False,
):
    respect_robots = getattr(client, "respect_robots", robots_enabled())
    inputs = (
        {
            "references": pronunciation_references,
            "index": pronunciation_index,
            "museum_pages": museum_pages,
            "wikidata": use_wikidata,
            "images": image_references,
            "offline": offline,
            "respect_robots": respect_robots,
            "source_images": source_images,
        }
        if pronunciation_references
        or pronunciation_index
        or museum_pages
        or use_wikidata
        or image_references
        or offline
        or not respect_robots
        or source_images
        else None
    )
    folder = Path(folder)
    store = Store(folder, memory=dry_run)
    own_client = client is None
    temporary = (
        tempfile.TemporaryDirectory(prefix="bedtime-import-dry-")
        if dry_run and own_client
        else None
    )
    client = client or PoliteClient(
        Path(temporary.name) if temporary else folder / "http", refresh=refresh
    )
    report = {
        "processed": 0,
        "resumed": 0,
        "source_supported_applied": 0,
        "images_published": 0,
        "proposals": [],
        "errors": [],
        "dry_run": dry_run,
        "respect_robots": respect_robots,
        "discovered": 0,
    }
    try:
        with sqlite3.connect(
            "file:" + str(Path(db).resolve()) + "?mode=ro", uri=True
        ) as conn:
            records = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT record_json FROM creature_profiles ORDER BY creature_id"
                )
            ]
        if pilot:
            records = sorted(
                [r for r in records if r["category"] == "dinosaur"],
                key=lambda r: (
                    PILOT.index(r["display_name"])
                    if r["display_name"] in PILOT
                    else 1000,
                    r["id"],
                ),
            )[:pilot]
        if all_records and not offline:
            identities = {library.normalize(r["scientific_name"]) for r in records}
            for category, target in [
                ("dinosaur", 150),
                ("shark", 60),
                ("marine_reptile", 40),
            ]:
                missing = max(
                    0, target - sum(r["category"] == category for r in records)
                )
                if not missing:
                    continue
                try:
                    found = sources.discover(client, category, missing * 2)
                    added = 0
                    for candidate in found:
                        name = candidate["scientific_name"]
                        if library.normalize(name) in identities:
                            continue
                        key = (
                            category
                            + ":"
                            + re.sub("[^a-z0-9]+", "-", name.lower()).strip("-")
                        )
                        record = library.CreatureRecord(
                            stable_key=key,
                            display_name=name,
                            scientific_name=name,
                            category=category,
                            taxon_group=candidate["taxon_group"],
                            taxon_rank=candidate["taxon_rank"],
                            review_notes=[
                                "Discovered in an accepted scientific taxon list; biology and habitat require review."
                            ],
                        ).model_dump(mode="json")
                        # A discovered name is staged for review, not inserted to inflate the live library.
                        records.append(record)
                        identities.add(library.normalize(name))
                        report["discovered"] += 1
                        added += 1
                        if added >= missing:
                            break
                except SourceUnavailable as error:
                    report["errors"].append(
                        {"source": "discovery " + category, "error": str(error)}
                    )
        for n, record in enumerate(records):
            if (
                record["verification_status"] == "verified"
                and not record["image"]["placeholder"]
                and record["pronunciation"]["status"] == "verified"
            ):
                continue
            fingerprint = digest(record, inputs)
            checkpoint = store.checkpoint(record["stable_key"], fingerprint)
            if not refresh and checkpoint:
                report["resumed"] += 1
                # Staging and app writes span two databases. After interruption,
                # finish a pending supported-fact write rather than losing it.
                saved = store.get(checkpoint[0])
                if (
                    apply
                    and not dry_run
                    and saved
                    and saved["status"] != "rejected"
                    and record.get("id") is not None
                ):
                    try:
                        applied = apply_supported(
                            db, record, json.loads(saved["payload"])
                        )
                    except (ValueError, KeyError, OSError) as error:
                        from .persistence import failure

                        report["errors"].append(
                            failure(
                                error,
                                operation="automatic_science",
                                record=record,
                                proposal_id=saved["id"],
                            )
                        )
                        applied = False
                    report["source_supported_applied"] += int(applied)
                    image_record = current_record(db, record["stable_key"])
                    published = publish_supported_image(
                        db,
                        image_record,
                        json.loads(saved["payload"]),
                        store,
                        saved["id"],
                    )
                    report["images_published"] += int(published)
                    if applied or published:
                        with sqlite3.connect(db) as conn:
                            updated = json.loads(
                                conn.execute(
                                    "SELECT record_json FROM creature_profiles WHERE stable_key=?",
                                    (record["stable_key"],),
                                ).fetchone()[0]
                            )
                        with store.conn:
                            store.conn.execute(
                                "UPDATE checkpoints SET input_hash=? WHERE stable_key=?",
                                (digest(updated, inputs), record["stable_key"]),
                            )
                continue
            progress(f"[{n + 1}/{len(records)}] {record['display_name']}", flush=True)
            try:
                proposal = collect(
                    client,
                    record,
                    folder,
                    dry_run,
                    pronunciation_index,
                    museum_pages,
                    pronunciation_references,
                    use_wikidata,
                    image_references,
                    offline,
                    source_images or bool(image_references),
                )
                if dry_run:
                    pid = None
                else:
                    pid = store.stage(record["stable_key"], fingerprint, proposal)
                applied = False
                if apply and not dry_run and record.get("id") is not None:
                    try:
                        applied = apply_supported(db, record, proposal)
                    except (ValueError, KeyError, OSError) as error:
                        from .persistence import failure

                        context = failure(
                            error,
                            operation="automatic_science",
                            record=record,
                            proposal_id=pid,
                        )
                        report["errors"].append(context)
                        proposal["issues"].append(
                            "Canonical validation refused update: " + str(error)
                        )
                published = False
                if apply and not dry_run and record.get("id") is not None:
                    publication_record = current_record(db, record["stable_key"])
                    published = publish_supported_image(
                        db, publication_record, proposal, store, pid
                    )
                    report["images_published"] += int(published)
                report["processed"] += 1
                report["source_supported_applied"] += int(applied)
                report["proposals"].append(
                    {
                        "id": pid,
                        "name": record["display_name"],
                        "science_fields": list(proposal["science"]),
                        "images": len(proposal["images"]),
                        "supported_images": sum(
                            i["supported"] for i in proposal["images"]
                        ),
                        "pronunciation_found": proposal["pronunciation"] is not None,
                        "issues": proposal["issues"],
                    }
                )
                if applied or published:
                    # Refresh the checkpoint to the post-import record so a normal
                    # restart does not immediately refetch our own supported update.
                    with sqlite3.connect(db) as conn:
                        updated = json.loads(
                            conn.execute(
                                "SELECT record_json FROM creature_profiles WHERE stable_key=?",
                                (record["stable_key"],),
                            ).fetchone()[0]
                        )
                    with store.conn:
                        store.conn.execute(
                            "UPDATE checkpoints SET input_hash=? WHERE stable_key=?",
                            (digest(updated, inputs), record["stable_key"]),
                        )
            except (SourceUnavailable, ValueError, OSError) as error:
                report["errors"].append(
                    {"name": record["display_name"], "error": str(error)}
                )
        with sqlite3.connect(db) as conn:
            report["audit"] = library.audit(
                conn,
                __import__("os").environ.get(
                    "BBS_AUDIO_CACHE", library.ROOT / "data/audio_cache"
                ),
            )
        report["pending_review"] = len(store.proposals())
        report["access_log"] = list(getattr(client, "events", []))
        report["http_requests"] = client.requests
        report["http_cache_hits"] = client.cache_hits
        return report
    finally:
        if own_client:
            client.close()
        store.close()
        if temporary:
            temporary.cleanup()
