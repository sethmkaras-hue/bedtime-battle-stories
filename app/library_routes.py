"""Read-only encyclopedia and prebuilt asset delivery. No TTS submission here."""

import json
import os
import re
import sqlite3
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from . import library

router = APIRouter(prefix="/api/library")


def connection():
    from . import main

    main.ensure_database()
    conn = sqlite3.connect(main.DB)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/creatures/{creature_id}")
def profile(creature_id: int):
    from .main import creatures

    row = next((r for r in creatures() if r["id"] == creature_id), None)
    if row is None:
        raise HTTPException(404, "Creature not found")
    return row


@router.get("/audit")
def audit():
    with connection() as conn:
        return library.audit(
            conn, os.environ.get("BBS_AUDIO_CACHE", library.ROOT / "data/audio_cache")
        )


@router.get("/attributions")
def attributions():
    with connection() as conn:
        records = [
            json.loads(r[0])
            for r in conn.execute("SELECT record_json FROM creature_profiles")
        ]
        return [
            {"id": r["id"], "name": r["display_name"], **r["image"]}
            for r in records
            if not r["image"]["placeholder"]
        ]


@router.get("/pronunciations/{creature_id}/{key}")
def pronunciation_file(creature_id: int, key: str, request: Request):
    if re.fullmatch("[0-9a-f]{64}", key) is None:
        raise HTTPException(404, "Pronunciation not found")
    with connection() as conn:
        result = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE creature_id=?",
            (creature_id,),
        ).fetchone()
        if result is None:
            raise HTTPException(404, "Creature not found")
        record = json.loads(result[0])
        options = library.audio_options(
            conn, creature_id, record, request.app.state.audio.root
        )
        url = f"/api/library/pronunciations/{creature_id}/{key}"
        if not any(option["url"] == url for option in options):
            conn.execute(
                "INSERT OR REPLACE INTO library_asset_issues VALUES (?,?,?)",
                (
                    creature_id,
                    "pronunciation_audio",
                    "Verified current local pronunciation is missing; run GENERATE_PRONUNCIATIONS.sh",
                ),
            )
            conn.commit()
            raise HTTPException(
                404,
                "Pronunciation is not prepared. A parent can run the generation utility.",
            )
    path = request.app.state.audio.root / "pronunciation" / (key + ".wav")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/image-coverage")
def image_coverage():
    from .main import DB, ensure_database
    from .importer.internet_images import coverage

    ensure_database()
    return coverage(DB)


@router.get("/sources-credits")
def sources_credits():
    from .main import creatures

    result = []
    for creature in creatures():
        profile = creature.get("profile", {})
        result.append(
            {
                "id": creature["id"],
                "name": creature["name"],
                "scientific_name": profile.get("scientific_name"),
                "sources": profile.get("sources", []),
                "pronunciation": profile.get("pronunciation", {}),
                "image": creature.get("internet_image")
                or creature.get("generated_image")
                or profile.get("image", {}),
                "image_kind": creature.get("image_kind", "licensed_or_placeholder"),
            }
        )
    return result


@router.get("/images/{creature_id}/{key}")
def internet_image_file(creature_id: int, key: str):
    from .images.core import valid_asset

    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise HTTPException(404, "Image not found")
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='internet_image_versions'"
        ).fetchone():
            raise HTTPException(404, "Image not found")
        asset = conn.execute(
            "SELECT * FROM internet_image_versions WHERE creature_id=? AND key=?",
            (creature_id, key),
        ).fetchone()
        if not asset or not valid_asset(dict(asset)):
            raise HTTPException(404, "Image missing or corrupt; rerun the importer")
    return FileResponse(
        asset["path"],
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
