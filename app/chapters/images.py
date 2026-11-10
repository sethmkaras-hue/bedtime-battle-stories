"""Adult-targeted reuse of the importer and immutable image versions."""

import hashlib
import io
import json
from pathlib import Path
from app import library
from app.importer import internet_images as imports
from app.importer.network import PoliteClient, atomic
from app.importer.store import root as import_root
from . import store


def preview_root():
    return (import_root() / "image-manager").resolve()


def current_record(db, cid):
    with store.connection(db) as conn:
        row = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE creature_id=?", (cid,)
        ).fetchone()
    if not row:
        raise LookupError("Creature not found")
    return json.loads(row[0])


def snapshot(db, cid):
    from app.main import creatures

    creature = next((c for c in creatures() if c["id"] == cid), None)
    if not creature:
        raise LookupError("Creature not found")
    view = {
        k: v
        for k, v in creature.items()
        if k
        in {
            "image_reference",
            "image_variants",
            "image_kind",
            "artwork_placeholder",
            "internet_image",
            "generated_image",
        }
    }
    metadata = {"view": view, "canonical": creature.get("profile", {}).get("image", {})}
    with store.connection(db) as conn:
        if creature.get("image_kind") == "internet":
            row = conn.execute(
                "SELECT * FROM internet_image_versions WHERE creature_id=? AND key=?",
                (cid, view["image_reference"].rsplit("/", 1)[-1]),
            ).fetchone()
            metadata["asset"] = dict(row) if row else None
            kind = "internet"
        elif creature.get("image_kind") == "ai_generated":
            row = conn.execute(
                "SELECT * FROM creature_generated_image_versions WHERE creature_id=? AND key=?",
                (cid, view["image_reference"].rsplit("/", 1)[-1]),
            ).fetchone()
            metadata["asset"] = dict(row) if row else None
            kind = "generated"
        else:
            kind = "canonical"
        identity = hashlib.sha256(
            json.dumps(
                {"creature": cid, "url": view.get("image_reference"), "kind": kind},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        conn.execute(
            "INSERT OR IGNORE INTO story_image_history VALUES(?,?,?,?,?,?)",
            (
                identity,
                cid,
                kind,
                (metadata.get("asset") or {}).get("key"),
                json.dumps(metadata),
                store.now(),
            ),
        )
    return identity


def overlay(conn, item):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='story_image_choice'"
    ).fetchone():
        return
    row = conn.execute(
        "SELECT h.* FROM story_image_choice c JOIN story_image_history h ON h.id=c.history_id WHERE c.creature_id=?",
        (item["id"],),
    ).fetchone()
    if not row:
        return
    # sqlite callers can use tuple rows; select explicit known columns.
    metadata = json.loads(row[4])
    kind = row[2]
    if kind in ("internet", "generated"):
        if not metadata.get("asset") or not imports.valid_asset(metadata["asset"]):
            return
    elif not metadata["canonical"].get(
        "placeholder"
    ) and not library.canonical_image_available(metadata["canonical"]):
        return
    for key in ("generated_image", "internet_image", "image_kind"):
        item.pop(key, None)
    item.update(metadata["view"])


def history(db, cid):
    snapshot(db, cid)
    from app.main import creatures

    current = next(c for c in creatures() if c["id"] == cid).get("image_reference")
    with store.connection(db) as conn:
        rows = conn.execute(
            "SELECT * FROM story_image_history WHERE creature_id=? ORDER BY created DESC",
            (cid,),
        ).fetchall()
    result = []
    for row in rows:
        metadata = json.loads(row["metadata"])
        view = metadata["view"]
        credit = (
            view.get("internet_image")
            or view.get("generated_image")
            or metadata["canonical"]
        )
        result.append(
            {
                "id": row["id"],
                "creature_id": cid,
                "url": view.get("image_reference"),
                "source": credit.get("original_source_url"),
                "creator": credit.get("creator"),
                "license": credit.get("license") or credit.get("model_license"),
                "installed_on": credit.get("installed_on")
                or credit.get("generated_at"),
                "recorded_on": row["created"],
                "active": current == view.get("image_reference"),
                "kind": row["kind"],
            }
        )
    return result


def restore(db, cid, hid):
    snapshot(db, cid)
    with store.connection(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM story_image_history WHERE id=? AND creature_id=?", (hid, cid)
        ).fetchone()
        if not row:
            raise LookupError("Image version not found")
        metadata = json.loads(row["metadata"])
        if row["kind"] in ("internet", "generated"):
            if not metadata.get("asset") or not imports.valid_asset(metadata["asset"]):
                raise ValueError("Previous file is missing or corrupt")
        elif not metadata["canonical"].get(
            "placeholder"
        ) and not library.canonical_image_available(metadata["canonical"]):
            raise ValueError("Previous file is missing or corrupt")
        conn.execute(
            "INSERT OR REPLACE INTO story_image_choice VALUES(?,?)", (cid, hid)
        )
        conn.execute(
            "UPDATE creatures SET image_reference=? WHERE id=?",
            (metadata["view"].get("image_reference"), cid),
        )


def previews(db, job_id, offset=0):
    with store.connection(db) as conn:
        rows = conn.execute(
            "SELECT * FROM story_image_candidates WHERE job_id=? ORDER BY rowid LIMIT 20 OFFSET ?",
            (job_id, offset),
        ).fetchall()
    client = PoliteClient(import_root() / "http")
    try:
        from PIL import Image, ImageOps

        for row in rows:
            if row["preview_path"] and Path(row["preview_path"]).is_file():
                continue
            candidate = json.loads(row["metadata"])
            try:
                response = client.get(
                    candidate.get("thumbnail_url") or candidate["download_url"],
                    limit=2_000_000,
                )
                with Image.open(io.BytesIO(response.content)) as image:
                    if image.width * image.height > 25_000_000:
                        raise ValueError("Preview too large")
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((320, 320))
                    output = io.BytesIO()
                    image.save(output, format="WEBP", quality=80)
                path = preview_root() / (row["id"] + ".webp")
                atomic(path, output.getvalue())
                with store.connection(db) as conn:
                    conn.execute(
                        "UPDATE story_image_candidates SET preview_path=? WHERE id=?",
                        (str(path), row["id"]),
                    )
            except Exception:
                # A failed thumbnail never grants permission or changes the image.
                import logging

                logging.getLogger(__name__).info(
                    "Preview unavailable candidate=%s", row["id"], exc_info=True
                )
    finally:
        client.close()


def work(db, job):
    payload = json.loads(job["payload"])
    cid = int(job["target"]) if job["kind"] != "image_previews" else None
    if job["kind"] == "image_search":
        record = current_record(db, cid)
        client = PoliteClient(
            import_root() / "http", refresh=payload.get("refresh", False)
        )
        try:
            found, diagnostics = imports.discover(
                client, record, query=payload.get("query", "")
            )
            if record["category"] == "shark" and not payload.get("query"):
                alternative, notes = imports.gbif_images(client, record)
                seen = {c["download_url"] for c in found}
                found += [c for c in alternative if c["download_url"] not in seen]
                diagnostics += notes
        finally:
            client.close()
        ranked = imports.ranked(found)
        with store.connection(db) as conn:
            for item in ranked:
                key = hashlib.sha256(
                    (job["id"] + ":" + item["download_url"]).encode()
                ).hexdigest()[:32]
                conn.execute(
                    "INSERT OR IGNORE INTO story_image_candidates VALUES(?,?,?,?,NULL)",
                    (key, job["id"], cid, json.dumps(item)),
                )
            conn.execute(
                "UPDATE story_jobs SET payload=? WHERE id=?",
                (
                    json.dumps(
                        {**payload, "diagnostics": diagnostics, "count": len(ranked)}
                    ),
                    job["id"],
                ),
            )
        previews(db, job["id"])
    elif job["kind"] == "image_previews":
        previews(db, payload["search_id"], payload["offset"])
    elif job["kind"] == "image_install":
        with store.connection(db) as conn:
            row = conn.execute(
                "SELECT * FROM story_image_candidates WHERE id=? AND creature_id=?",
                (payload["candidate_id"], cid),
            ).fetchone()
        if not row:
            raise LookupError("Candidate not found for this creature")
        item = json.loads(row["metadata"])
        record = current_record(db, cid)
        client = PoliteClient(import_root() / "http")
        try:
            response = client.get(item["download_url"], limit=20_000_000)
        finally:
            client.close()
        snapshot(db, cid)
        if not imports.install(db, record, item, response.content, explicit=True):
            raise ValueError("Image was not installed")
        with store.connection(db) as conn:
            conn.execute("DELETE FROM story_image_choice WHERE creature_id=?", (cid,))
        snapshot(db, cid)
    else:
        raise ValueError("Unknown image job")
