from typing import Literal
import hmac
import json
from fastapi import APIRouter, HTTPException, Request, Response, Path as ApiPath
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict, field_validator
from .importer.store import Store, root
from .importer.review import approve, safe_file
from .importer.persistence import ContentError, pending, failure, issues

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
    image_index: int = Field(default=0, ge=0, strict=True)
    confirm: Literal[True]

    @field_validator("confirm", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirm the decision explicitly")
        return value

    phonetic: str | None = Field(default=None, max_length=100)
    stress: str | None = Field(default=None, max_length=100)
    tts_text: str | None = Field(default=None, max_length=200)


@router.post("/proposals/{pid}/decision")
def decide(body: Decision, request: Request, pid: int = ApiPath(gt=0)):
    authorized(request, True)
    store = Store()
    record = None
    try:
        row = store.get(pid)
        record = json.loads(row["payload"]) if row else None
        pending(store, pid)
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
    except (ValueError, KeyError, OSError) as error:
        context = failure(
            error, operation="parent_" + body.decision, record=record, proposal_id=pid
        )
        detail = {
            "code": error.code
            if isinstance(error, ContentError)
            else "invalid_content",
            "message": str(error)
            if isinstance(error, ContentError)
            else "Imported content failed validation; correct the listed fields",
            **context,
        }
        if isinstance(error, ContentError):
            detail["issues"] = error.issues
        raise HTTPException(
            error.status if isinstance(error, ContentError) else 422, detail
        ) from error
    finally:
        store.close()


async def request_validation_error(request, error):
    # Preserve auth/CSRF even when request parsing fails before the route runs.
    if request.url.path != "/api/admin/login":
        try:
            authorized(request, request.method in {"POST", "PUT", "PATCH", "DELETE"})
        except HTTPException as denied:
            return JSONResponse(
                status_code=denied.status_code, content={"detail": denied.detail}
            )
    # Do not log request bodies, passwords, cookies, tokens or Pydantic inputs.
    problem = [{k: e[k] for k in ("loc", "msg", "type")} for e in error.errors()]
    pid = request.path_params.get("pid")
    if isinstance(pid, str) and pid.isdecimal():
        pid = int(pid)
    record = None
    if isinstance(pid, int):
        store = Store()
        try:
            row = store.get(pid)
            if row:
                record = json.loads(row["payload"])
        finally:
            store.close()
    context = {
        "operation": "parent_decision"
        if "/decision" in request.url.path
        else "parent_request",
        "proposal_id": pid,
        "creature": (record or {}).get("display_name"),
        "stable_key": (record or {}).get("stable_key"),
        "issues": problem,
    }
    import logging

    logging.getLogger(__name__).warning(
        "Parent request validation failed: %s", json.dumps(context)
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "invalid_request",
                "message": "Request fields are invalid; see the listed fields",
                **context,
            }
        },
    )
