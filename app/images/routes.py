"""Image metadata/serving and authenticated nonblocking regeneration requests."""

import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from app.admin_routes import authorized
from . import core

router = APIRouter(prefix="/api/creature-images")
admin_router = APIRouter(prefix="/api/admin/creature-images")
_guard = threading.Lock()
_supervisor = None
_process = None


def db():
    from app.main import DB, ensure_database

    ensure_database()
    return DB


def runtime():
    return (
        Path(os.environ.get("BBS_IMAGE_VENV", core.ROOT / ".venv-images"))
        / "bin/python"
    )


def supervise(database):
    global _process
    # Persistent queue owns work; the app process never imports a diffusion model.
    while True:
        with core.connect(database) as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM creature_image_jobs WHERE status='queued'"
            ).fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM creature_image_jobs WHERE status='generating'"
            ).fetchone()[0]
        if not pending and not active:
            return
        code = _process.poll() if _process is not None else None
        if code is not None and (code in {3, 130} or code < 0):
            return  # Resource failure: retain durable work without a restart storm.
        if pending and (_process is None or _process.poll() is not None):
            if core.worker_running(database):
                time.sleep(2)
                continue
            try:
                log = core.output_root()
                log.mkdir(parents=True, exist_ok=True)
                with (log / "worker.log").open("ab") as stream:
                    _process = subprocess.Popen(
                        [
                            str(runtime()),
                            str(core.ROOT / "scripts/generate_creature_images.py"),
                            "--pending",
                            "--db",
                            str(database),
                        ],
                        cwd=core.ROOT,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        env={
                            **os.environ,
                            "OMP_NUM_THREADS": "2",
                            "OPENBLAS_NUM_THREADS": "1",
                        },
                    )
            except OSError as error:
                with core.connect(database) as conn:
                    conn.execute(
                        "UPDATE creature_image_jobs SET status='failed',error=? WHERE status='queued'",
                        ("Worker could not start: " + str(error),),
                    )
                return
        time.sleep(2)


def launch(database):
    global _supervisor, _process
    with _guard:
        if _supervisor is None or not _supervisor.is_alive():
            _process = None
            _supervisor = threading.Thread(
                target=supervise,
                args=(database,),
                daemon=True,
                name="image-generation-supervisor",
            )
            _supervisor.start()


@router.get("/status")
def status():
    result = core.status(db())
    try:
        result["model_configuration"] = core.model_config()
        result["model_available"] = runtime().is_file()
    except (ValueError, OSError, RuntimeError) as error:
        result["model_configuration"] = None
        result["model_available"] = False
        result["setup_error"] = str(error)
    return result


@router.get("/metadata/{creature_id}")
def metadata(creature_id: int):
    with core.connect(db()) as conn:
        active = conn.execute(
            "SELECT * FROM creature_generated_images WHERE creature_id=?",
            (creature_id,),
        ).fetchone()
        jobs = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM creature_image_jobs WHERE creature_id=? ORDER BY updated DESC",
                (creature_id,),
            )
        ]
    return {
        "image": core.render_asset(active)
        if active and core.valid_asset(active)
        else None,
        "jobs": [
            {
                **{k: v for k, v in row.items() if k != "settings_json"},
                "settings": json.loads(row["settings_json"]),
            }
            for row in jobs
        ],
    }


@router.get("/files/{creature_id}/{key}")
def image_file(creature_id: int, key: str):
    if not re.fullmatch("[0-9a-f]{64}", key):
        raise HTTPException(404, "Image not found")
    with core.connect(db()) as conn:
        asset = conn.execute(
            "SELECT * FROM creature_generated_image_versions WHERE creature_id=? AND key=?",
            (creature_id, key),
        ).fetchone()
    if not core.valid_asset(asset):
        raise HTTPException(
            404, "Generated image is missing or invalid; resume generation"
        )
    return FileResponse(
        asset["path"],
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


class Regenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creature_id: int = Field(gt=0, strict=True)


@admin_router.post("/regenerate", status_code=202)
def regenerate(body: Regenerate, request: Request):
    authorized(request, True)
    if not runtime().is_file():
        raise HTTPException(
            503, "Install the isolated image runtime with SETUP_CREATURE_IMAGES.sh"
        )
    try:
        settings = core.defaults()
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(503, str(error)) from error
    chosen = [row for row in core.records(db()) if row["id"] == body.creature_id]
    if not chosen:
        raise HTTPException(404, "Creature not found")
    result = core.enqueue(db(), chosen, settings, force=True)
    launch(db())
    return {
        **result,
        "status": "queued",
        "message": "One CPU worker will process the queued illustration. Previous artwork stays available until success.",
    }
