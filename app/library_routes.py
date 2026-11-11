"""Encyclopedia, validated local files, and queued local spoken-name requests."""

import json
import os
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

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
        from app.chapters.pronunciation import options as spoken_options

        options += spoken_options(
            conn, creature_id, record, request.app.state.audio.root
        )
        url = f"/api/library/pronunciations/{creature_id}/{key}"
        if not any(option["url"] == url for option in options):
            conn.execute(
                "INSERT OR REPLACE INTO library_asset_issues VALUES (?,?,?)",
                (
                    creature_id,
                    "pronunciation_audio",
                    "Current local name audio is missing or corrupt; tap its picture or speaker to prepare it.",
                ),
            )
            conn.commit()
            raise HTTPException(
                404,
                "Name audio is missing or corrupt. Tap its picture or speaker to prepare it.",
            )
    path = request.app.state.audio.root / "pronunciation" / (key + ".wav")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/image-coverage")
def image_coverage():
    from .importer.internet_images import coverage
    from .main import DB, ensure_database

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


class SpokenNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["kokoro", "piper"] = "kokoro"
    voice: str = Field(default="af_heart", min_length=1, max_length=150)
    speed: float = Field(default=0.8, ge=0.65, le=1.15)


@router.post("/creatures/{creature_id}/pronunciation", status_code=202)
def prepare_name(creature_id: int, body: SpokenNameRequest, request: Request):
    from app.chapters import pronunciation
    from app.chapters.routes import call, write
    from app.main import DB, ensure_database

    write(request)
    ensure_database()
    return call(
        pronunciation.prepare,
        DB,
        creature_id,
        body.model_dump(),
        request.app.state.audio,
    )


@router.get("/pronunciation-jobs/{job_id}")
def spoken_status(job_id: str):
    from app.chapters import store
    from app.main import DB, ensure_database

    ensure_database()
    with store.connection(DB) as conn:
        row = conn.execute(
            "SELECT * FROM story_jobs WHERE id=? AND kind='spoken_name'", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Spoken-name job not found")
    payload = json.loads(row["payload"])
    return {
        "status": row["status"],
        "asset": payload.get("asset"),
        "message": "A local name voice is unavailable. Try again or use a device voice."
        if row["status"] == "failed"
        else None,
    }
