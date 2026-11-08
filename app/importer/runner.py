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
from .network import PoliteClient, SourceUnavailable, atomic
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
VERSION = 1


def digest(record):
    return hashlib.sha256(
        (str(VERSION) + json.dumps(record, sort_keys=True)).encode()
    ).hexdigest()


def preview_image(client, candidate, folder):
    from PIL import Image, ImageOps
    import warnings

    response = client.get(candidate["download_url"], limit=20_000_000)
    sha = hashlib.sha256(response.content).hexdigest()
    original = folder / "originals" / (sha + ".image")
    atomic(original, response.content)
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
    client, record, folder, dry_run=False, pronunciation_index=None, museum_pages=False
):
    patch, evidence, issues = sources.science(client, record)
    if museum_pages:
        museum, refs, errors = sources.museum_facts(client, record)
        patch.update(museum)
        evidence += refs
        issues += errors
        pron, errors = sources.pronunciation(client, record, pronunciation_index)
        issues += errors
    else:
        pron = None
        issues.append(
            "Museum/educational page acquisition needs a source-terms review; enable --allow-museum-pages after reviewing site terms."
        )
    try:
        candidates = sources.images(client, record)
    except (SourceUnavailable, ValueError, KeyError) as error:
        candidates = []
        issues.append(str(error))
    downloaded = 0
    for i, candidate in enumerate(candidates):
        if candidate["supported"] and not dry_run and downloaded < 2:
            try:
                candidates[i] = preview_image(client, candidate, folder)
                downloaded += 1
            except (SourceUnavailable, ValueError, OSError) as error:
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
    if not proposal["science"] or record["verification_status"] == "verified":
        return False
    new = json.loads(json.dumps(record))
    protected = record.get("reviewed_fields", {})
    patch = {k: v for k, v in proposal["science"].items() if k not in protected}
    new.update(patch)
    new["import_stage"] = (
        "source_supported"
        if record.get("import_stage") != "manually_reviewed"
        else "manually_reviewed"
    )
    by_id = {s["id"]: s for s in record["sources"]}
    ids = {}
    for source in proposal["evidence"]:
        identity = {k: v for k, v in source.items() if k != "retrieved_on"}
        suffix = hashlib.sha256(
            json.dumps(
                {"source": identity, "fields": proposal["science"]}, sort_keys=True
            ).encode()
        ).hexdigest()[:12]
        sid = source["id"] + "-" + suffix
        ids[source["id"]] = sid
        if sid not in by_id:
            by_id[sid] = {
                k: v
                for k, v in source.items()
                if k in {"id", "title", "url", "publisher", "supports", "retrieved_on"}
            }
            by_id[sid]["id"] = sid
    for measurement in ["length", "weight"]:
        if measurement in patch:
            new[measurement]["source_ids"] = [
                ids.get(s, s) for s in new[measurement]["source_ids"]
            ]
    new["sources"] = list(by_id.values())
    parsed = library.CreatureRecord.model_validate(new).model_dump(mode="json")
    if parsed == record:
        return False
    with sqlite3.connect(db, timeout=5) as conn:
        library.import_records(conn, [parsed])
    return True


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
):
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
        "proposals": [],
        "errors": [],
        "dry_run": dry_run,
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
        if all_records:
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
            fingerprint = digest(record)
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
                    applied = apply_supported(db, record, json.loads(saved["payload"]))
                    report["source_supported_applied"] += int(applied)
                    if applied:
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
                                (digest(updated), record["stable_key"]),
                            )
                continue
            progress(f"[{n + 1}/{len(records)}] {record['display_name']}", flush=True)
            try:
                proposal = collect(
                    client, record, folder, dry_run, pronunciation_index, museum_pages
                )
                if dry_run:
                    pid = None
                else:
                    pid = store.stage(record["stable_key"], fingerprint, proposal)
                applied = False
                if apply and not dry_run and record.get("id") is not None:
                    try:
                        applied = apply_supported(db, record, proposal)
                    except ValueError as error:
                        proposal["issues"].append(
                            "Canonical validation refused update: " + str(error)
                        )
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
                if applied:
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
                            (digest(updated), record["stable_key"]),
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
        report["http_requests"] = client.requests
        report["http_cache_hits"] = client.cache_hits
        return report
    finally:
        if own_client:
            client.close()
        store.close()
        if temporary:
            temporary.cleanup()
