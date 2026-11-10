"""Persistent chapter API and existing adult-session protected image manager."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.admin_routes import authorized

from . import images, store

router = APIRouter(prefix="/api/story")
admin = APIRouter(prefix="/api/admin")


def db():
    from app.main import DB, ensure_database

    ensure_database()
    return DB


def write(request):
    if request.headers.get("x-bedtime-client") != "app":
        raise HTTPException(403, "Use the adventure controls")
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Use the same application origin")


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Settings(Strict):
    duration_seconds: Literal[20, 30, 40, 50, 60] = 20
    tone: Literal["dramatic", "gentle"] = "dramatic"
    predictions_enabled: bool = True
    winner_mode: Literal["simulation"] = "simulation"
    connected_chapters: bool = True


class NewTournament(Strict):
    creature_ids: list[StrictInt] = Field(min_length=8, max_length=8)
    seed: StrictInt | None = Field(default=None, ge=0, lt=2**32)
    shuffle: bool = False
    request_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9-]+$")


class AudioPrefs(Strict):
    provider: Literal["kokoro", "piper", "browser", "openai"] = "kokoro"
    voice: str = Field(default="af_heart", max_length=150)
    speed: float = Field(default=0.95, ge=0.8, le=1.15)


class Prediction(Strict):
    desired_winner_id: StrictInt | None = None
    predicted_winner_id: StrictInt | None = None
    skipped: bool = False
    audio: AudioPrefs = Field(default_factory=AudioPrefs)


@router.get("/settings")
def get_settings():
    with store.connection(db()) as conn:
        return store.settings(conn)


@admin.put("/story/settings")
def set_settings(body: Settings, request: Request):
    authorized(request, True)
    with store.connection(db()) as conn:
        conn.execute(
            "UPDATE story_settings SET data=? WHERE id=1", (body.model_dump_json(),)
        )
    return body


@router.post("/tournaments", status_code=201)
def create(body: NewTournament, request: Request):
    write(request)
    from app.main import creatures

    all_creatures = {c["id"]: c for c in creatures()}
    tid = call(
        store.create,
        db(),
        all_creatures,
        body.creature_ids,
        body.seed
        if body.seed is not None
        else int.from_bytes(
            hashlib.sha256(body.request_key.encode()).digest()[:4], "big"
        ),
        body.shuffle,
        body.request_key,
    )
    return store.state(db(), tid, all_creatures)


@router.get("/tournaments")
def history(
    offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)
):
    with store.connection(db()) as conn:
        return [
            {
                "id": r["id"],
                "title": json.loads(r["data"])["outline"]["title"],
                "created": r["created"],
                "completed": conn.execute(
                    "SELECT COUNT(*) FROM story_battles WHERE tournament_id=? AND completed IS NOT NULL",
                    (r["id"],),
                ).fetchone()[0],
            }
            for r in conn.execute(
                "SELECT * FROM story_tournaments ORDER BY created DESC,id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        ]


@router.get("/tournaments/{tid}")
def state(tid: str):
    from app.main import creatures

    return call(store.state, db(), tid, {c["id"]: c for c in creatures()})


@router.post("/tournaments/{tid}/battles/{bid}/begin", status_code=202)
def begin(tid: str, bid: str, body: Prediction, request: Request):
    write(request)
    call(
        store.begin,
        db(),
        tid,
        bid,
        body.predicted_winner_id,
        body.skipped,
        body.audio.model_dump(),
        body.desired_winner_id,
        "desired_winner_id" in body.model_fields_set,
    )
    return chapter(tid, bid)


@router.get("/tournaments/{tid}/battles/{bid}")
def chapter(tid: str, bid: str):
    with store.connection(db()) as conn:
        row = call(store.battle, conn, tid, bid)
        chapter = conn.execute(
            "SELECT * FROM story_chapters WHERE battle_id=?", (bid,)
        ).fetchone()
        content = (
            json.loads(chapter["narrative"])
            if chapter and chapter["narrative"]
            else None
        )
        if content and not row["completed"]:
            content = {
                k: v
                for k, v in content.items()
                if k not in {"winner_id", "summary", "key_events"}
            }
        prediction = json.loads(row["prediction"]) if row["prediction"] else None
        if prediction and not row["completed"]:
            prediction = {
                k: v
                for k, v in prediction.items()
                if k not in {"actual_winner_id", "correct"}
            }
        return {
            "battle_id": bid,
            "chapter_number": row["number"],
            "status": chapter["status"] if chapter else "not_started",
            "narrative": content,
            "audio": json.loads(chapter["audio"])
            if chapter and chapter["audio"]
            else None,
            "prediction": prediction,
            "desired_choice": store.desire(row),
            "predictions_enabled": store.settings(conn)["predictions_enabled"],
            "choices": store.choices(row) if row["completed"] else None,
            "completed": bool(row["completed"]),
            "simulation": json.loads(row["simulation"])
            if row["completed"] and row["simulation"]
            else None,
            "message": "Your story is taking a little rest. Read along, or ask a grown-up to try again."
            if chapter and chapter["status"] == "failed"
            else None,
        }


@router.post("/tournaments/{tid}/battles/{bid}/complete")
def complete(tid: str, bid: str, request: Request):
    write(request)
    call(store.complete, db(), tid, bid)
    return state(tid)


class Confirmation(Strict):
    confirm: Literal[True]

    @field_validator("confirm", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Confirm explicitly")
        return value


@admin.post("/story/tournaments/{tid}/battles/{bid}/regenerate", status_code=202)
def regenerate(tid: str, bid: str, body: Confirmation, request: Request):
    authorized(request, True)
    with store.connection(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        call(store.battle, conn, tid, bid)
        old = conn.execute(
            "SELECT * FROM story_chapters WHERE battle_id=?", (bid,)
        ).fetchone()
        if not old:
            raise HTTPException(409, "Prepare the chapter first")
        if old["status"] in ("pending", "generating"):
            raise HTTPException(409, "Wait for the current chapter job")
        if old["narrative"]:
            conn.execute(
                "INSERT OR IGNORE INTO story_chapter_versions VALUES(?,?,?,?,?)",
                (bid, old["revision"], old["narrative"], old["audio"], old["created"]),
            )
        prefs = {
            **store.settings(conn),
            "audio": json.loads(old["settings"])["audio"],
            "speech_rate": json.loads(old["settings"])["audio"]["speed"],
        }
        conn.execute(
            "UPDATE story_chapters SET revision=revision+1,status='pending',settings=?,narrative=NULL,audio=NULL,error=NULL,updated=? WHERE battle_id=?",
            (json.dumps(prefs), store.now(), bid),
        )
        call(store.enqueue, conn, "chapter", bid, {})
    return {"status": "pending", "battle_id": bid}


@router.get("/audio/{bid}/{key}")
def audio(bid: str, key: str):
    import re

    if not re.fullmatch("[a-f0-9]{64}", key):
        raise HTTPException(404, "Audio not found")
    with store.connection(db()) as conn:
        rows = conn.execute(
            "SELECT audio FROM story_chapter_versions WHERE battle_id=?", (bid,)
        ).fetchall()
        options = [json.loads(r[0]) for r in rows if r[0]]
    value = next((v for v in options if v["sha256"] == key), None)
    if not value:
        raise HTTPException(404, "Audio not found")
    path = Path(value["path"]).resolve()
    root = Path(value["root"]).resolve()
    if (
        not path.is_relative_to(root)
        or path.suffix != ".wav"
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != key
    ):
        raise HTTPException(
            404, "Archived audio is missing; existing text remains available"
        )
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


class Search(Strict):
    query: str = Field(default="", max_length=200)
    refresh: bool = False


@admin.post("/image-manager/{cid}/search", status_code=202)
def search(cid: int, body: Search, request: Request):
    authorized(request, True)
    call(images.current_record, db(), cid)
    with store.connection(db()) as conn:
        job = call(store.enqueue, conn, "image_search", str(cid), body.model_dump())
    return {"job_id": job, "status": "pending"}


@admin.get("/image-manager/jobs/{jid}")
def image_job(jid: str, request: Request):
    authorized(request)
    with store.connection(db()) as conn:
        row = conn.execute(
            "SELECT * FROM story_jobs WHERE id=? AND kind LIKE 'image_%'", (jid,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Image job not found")
    payload = json.loads(row["payload"])
    return {
        "job_id": jid,
        "status": row["status"],
        "error": row["error"],
        "count": payload.get("count"),
        "diagnostics": payload.get("diagnostics", []),
    }


@admin.get("/image-manager/{cid}/candidates/{jid}")
def candidates(cid: int, jid: str, request: Request, offset: int = 0):
    authorized(request)
    if offset < 0 or offset > 160:
        raise HTTPException(422, "Invalid candidate page")
    with store.connection(db()) as conn:
        rows = conn.execute(
            "SELECT * FROM story_image_candidates WHERE creature_id=? AND job_id=? ORDER BY rowid LIMIT 20 OFFSET ?",
            (cid, jid, offset),
        ).fetchall()
        count = conn.execute(
            "SELECT COUNT(*) FROM story_image_candidates WHERE creature_id=? AND job_id=?",
            (cid, jid),
        ).fetchone()[0]
    return {
        "candidates": [
            {
                "id": r["id"],
                **json.loads(r["metadata"]),
                "preview_url": f"/api/admin/image-manager/previews/{r['id']}",
            }
            for r in rows
        ],
        "next_offset": offset + 20 if offset + 20 < count else None,
        "total": count,
    }


class More(Strict):
    search_id: str = Field(pattern="^[a-f0-9]{32}$")
    offset: StrictInt = Field(ge=0, le=160)


@admin.post("/image-manager/more", status_code=202)
def more(body: More, request: Request):
    authorized(request, True)
    with store.connection(db()) as conn:
        if not conn.execute(
            "SELECT 1 FROM story_jobs WHERE id=? AND kind='image_search'",
            (body.search_id,),
        ).fetchone():
            raise HTTPException(404, "Search not found")
        job = call(
            store.enqueue,
            conn,
            "image_previews",
            body.search_id + ":" + str(body.offset),
            body.model_dump(),
        )
    return {"job_id": job, "status": "pending"}


@admin.get("/image-manager/previews/{candidate_id}")
def preview(candidate_id: str, request: Request):
    authorized(request)
    with store.connection(db()) as conn:
        row = conn.execute(
            "SELECT preview_path FROM story_image_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "Preview unavailable")
    path = Path(row[0]).resolve()
    if (
        not path.is_relative_to(images.preview_root())
        or path.suffix != ".webp"
        or not path.is_file()
    ):
        raise HTTPException(404, "Preview unavailable")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


class Candidate(Strict):
    candidate_id: str = Field(pattern="^[a-f0-9]{32}$")


@admin.post("/image-manager/{cid}/replace", status_code=202)
def replace(cid: int, body: Candidate, request: Request):
    authorized(request, True)
    call(images.current_record, db(), cid)
    with store.connection(db()) as conn:
        if not conn.execute(
            "SELECT 1 FROM story_image_candidates WHERE id=? AND creature_id=?",
            (body.candidate_id, cid),
        ).fetchone():
            raise HTTPException(404, "Candidate not found for this creature")
        job = call(store.enqueue, conn, "image_install", str(cid), body.model_dump())
    return {"job_id": job, "status": "pending"}


@admin.get("/image-manager/{cid}/history")
def image_history(cid: int, request: Request):
    authorized(request)
    return call(images.history, db(), cid)


class Restore(Strict):
    history_id: str = Field(pattern="^[a-f0-9]{64}$")


@admin.post("/image-manager/{cid}/restore")
def restore(cid: int, body: Restore, request: Request):
    authorized(request, True)
    call(images.restore, db(), cid, body.history_id)
    return {"restored": body.history_id}


@admin.get("/story/tournaments/{tid}/battles/{bid}/versions")
def chapter_versions(tid: str, bid: str, request: Request):
    authorized(request)
    with store.connection(db()) as conn:
        call(store.battle, conn, tid, bid)
        rows = conn.execute(
            "SELECT * FROM story_chapter_versions WHERE battle_id=? ORDER BY revision DESC",
            (bid,),
        ).fetchall()
    return [
        {
            "revision": r["revision"],
            "created": r["created"],
            "narrative": json.loads(r["narrative"]) if r["narrative"] else None,
            "audio": json.loads(r["audio"]) if r["audio"] else None,
        }
        for r in rows
    ]


class Desire(Strict):
    desired_winner_id: StrictInt | None = None


@router.post("/tournaments/{tid}/battles/{bid}/desire")
def save_desired(tid: str, bid: str, body: Desire, request: Request):
    write(request)
    call(store.save_desire, db(), tid, bid, body.desired_winner_id)
    return chapter(tid, bid)
