from typing import Literal
import hmac
import json
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from .importer.store import Store, root
from .importer.review import approve, safe_file

router = APIRouter(prefix="/api/admin")
COOKIE = "bedtime_parent"


def same_origin(request):
    origin = request.headers.get("origin")
    if not origin or origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Parent actions require the same app origin")


def authorized(request, write=False):
    session = request.app.state.parent_auth.session(request.cookies.get(COOKIE))
    if not session:
        raise HTTPException(401, "Unlock parent review first")
    if write:
        same_origin(request)
        if not hmac.compare_digest(
            request.headers.get("x-parent-csrf", ""), session["csrf"]
        ):
            raise HTTPException(403, "Parent action token is missing or expired")
    return session


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)


@router.get("/session")
def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    auth = request.app.state.parent_auth
    current = auth.session(request.cookies.get(COOKIE))
    return {
        "configured": auth.configured(),
        "unlocked": current is not None,
        "csrf": current["csrf"] if current else None,
    }


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    same_origin(request)
    auth = request.app.state.parent_auth
    if not auth.configured():
        raise HTTPException(
            503, "A parent must run scripts/configure_parent.py on the server first"
        )
    try:
        result = auth.login(
            body.password, request.client.host if request.client else "unknown"
        )
    except PermissionError as error:
        raise HTTPException(429, str(error)) from error
    if result is None:
        raise HTTPException(401, "Passphrase was not accepted")
    token, csrf = result
    response.set_cookie(
        COOKIE,
        token,
        max_age=900,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/admin",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"unlocked": True, "csrf": csrf}


@router.post("/logout")
def logout(request: Request, response: Response):
    authorized(request, True)
    request.app.state.parent_auth.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/api/admin")
    return {"unlocked": False}


@router.get("/proposals")
def proposals(request: Request, response: Response):
    authorized(request)
    response.headers["Cache-Control"] = "no-store"
    store = Store()
    try:
        result = store.proposals()
        for row in result:
            for i, image in enumerate(row["proposal"]["images"]):
                has_preview = bool(image.get("preview_file"))
                image.pop("original_file", None)
                image.pop("preview_file", None)
                if image.get("supported") and has_preview:
                    image["preview_url"] = f"/api/admin/proposals/{row['id']}/image/{i}"
            row["proposal"].pop("record", None)
        from . import main, library
        import sqlite3, os

        with sqlite3.connect(main.DB) as conn:
            audit = library.audit(
                conn,
                os.environ.get("BBS_AUDIO_CACHE", library.ROOT / "data/audio_cache"),
            )
        return {
            "pending": result,
            "coverage": {k: v for k, v in audit.items() if k != "records"},
            "missing": audit["records"],
        }
    finally:
        store.close()


@router.get("/proposals/{pid}/image/{index}")
def preview(pid: int, index: int, request: Request):
    authorized(request)
    store = Store()
    try:
        row = store.get(pid)
        if not row:
            raise ValueError("Proposal not found")
        images = json.loads(row["payload"]).get("images", [])
        if not 0 <= index < len(images):
            raise ValueError("Image not found")
        path = safe_file(store.root, images[index].get("preview_file", ""))
        return FileResponse(
            path,
            media_type="image/webp",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    except (ValueError, KeyError) as error:
        raise HTTPException(404, "Preview is unavailable") from error
    finally:
        store.close()


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    scopes: list[Literal["science", "image", "pronunciation"]] = Field(
        default_factory=list, max_length=3
    )
    image_index: int = Field(default=0, ge=0)
    confirm: Literal[True]
    phonetic: str | None = Field(default=None, max_length=100)
    stress: str | None = Field(default=None, max_length=100)
    tts_text: str | None = Field(default=None, max_length=200)


@router.post("/proposals/{pid}/decision")
def decide(pid: int, body: Decision, request: Request):
    authorized(request, True)
    store = Store()
    try:
        if body.decision == "reject":
            store.decide(pid, "rejected")
            return {"rejected": pid}
        from . import main

        edits = {
            k: v
            for k, v in body.model_dump().items()
            if k in {"phonetic", "stress", "tts_text"} and v is not None
        }
        return approve(main.DB, store, pid, body.scopes, body.image_index, edits)
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    finally:
        store.close()
