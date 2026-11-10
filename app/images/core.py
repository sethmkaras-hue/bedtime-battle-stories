"""Durable single-worker generation queue; stdlib only until converting output."""

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import time
import uuid
from .prompts import prompt, seed_for

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "stable-diffusion-v1-5/stable-diffusion-v1-5"
MODEL_LICENSE = "CreativeML Open RAIL-M"
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


def now():
    return datetime.now(timezone.utc).isoformat()


def output_root():
    return Path(
        os.environ.get("BBS_IMAGE_DIR", ROOT / "data/generated_images")
    ).resolve()


def model_root():
    return Path(
        os.environ.get("BBS_IMAGE_MODEL_DIR", ROOT / "data/models/illustrations")
    ).resolve()


def model_config():
    path = model_root() / "image-model.json"
    if not path.is_file():
        raise RuntimeError(
            "Local image model is not installed. Run SETUP_CREATURE_IMAGES.sh --download first."
        )
    data = json.loads(path.read_text())
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("revision", "")):
        raise ValueError("Model setup must record an immutable 40-character revision")
    root = Path(data["model_path"])
    required = data.get("required_files", ["model_index.json"])
    if not all((root / name).is_file() for name in required):
        raise RuntimeError(
            "Local model files are missing; rerun SETUP_CREATURE_IMAGES.sh --download"
        )
    return data


def defaults():
    config = model_config()
    return {
        "model": config["model"],
        "revision": config["revision"],
        "model_path": config["model_path"],
        "model_license": config["license"],
        "resolution": 512,
        "steps": 20,
        "guidance": 7.5,
        "threads": 2,
        "base_seed": 42,
        "output_dir": str(output_root()),
        "device": "cpu",
        "dtype": "float32",
        "batch_size": 1,
    }


def validate_settings(settings):
    if settings["device"] != "cpu" or settings.get("batch_size") != 1:
        raise ValueError("Only CPU batch size one is supported")
    if settings["resolution"] not in {256, 384, 512, 640, 768}:
        raise ValueError("Resolution must be 256, 384, 512, 640 or 768")
    if (
        not 1 <= settings["steps"] <= 100
        or not 1 <= settings["threads"] <= 32
        or not 0 <= settings["guidance"] <= 20
    ):
        raise ValueError("Invalid steps, threads or guidance")
    if not re.fullmatch(r"[0-9a-f]{40}", settings["revision"]):
        raise ValueError("Model revision must be immutable")
    return settings


def connect(db):
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""CREATE TABLE IF NOT EXISTS creature_image_jobs (
      key TEXT PRIMARY KEY,creature_id INTEGER NOT NULL,name TEXT NOT NULL,settings_json TEXT NOT NULL,
      status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,error TEXT,elapsed REAL,step INTEGER NOT NULL DEFAULT 0,updated TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS creature_generated_images (
      creature_id INTEGER PRIMARY KEY,key TEXT NOT NULL,path TEXT NOT NULL,root TEXT NOT NULL,sha256 TEXT NOT NULL,metadata_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS creature_generated_image_versions (key TEXT PRIMARY KEY,creature_id INTEGER NOT NULL,path TEXT NOT NULL,root TEXT NOT NULL,sha256 TEXT NOT NULL,metadata_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS creature_image_config (id INTEGER PRIMARY KEY CHECK(id=1),settings_json TEXT NOT NULL);
    """)
    conn.execute(
        "INSERT OR IGNORE INTO creature_generated_image_versions SELECT key,creature_id,path,root,sha256,metadata_json FROM creature_generated_images"
    )
    conn.commit()
    return conn


def records(db):
    with sqlite3.connect(db) as conn:
        return [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT record_json FROM creature_profiles ORDER BY creature_id"
            )
        ]


def file_for(settings, key, name):
    if not re.fullmatch("[0-9a-f]{64}", key):
        raise ValueError("Invalid image key")
    slug = re.sub("[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "creature"
    return Path(settings["output_dir"]).resolve() / (slug + "-" + key + ".webp")


def valid_asset(row):
    if row is None:
        return False
    try:
        path = Path(row["path"]).resolve()
        root = Path(row["root"]).resolve()
        if (
            not path.is_relative_to(root)
            or path.suffix != ".webp"
            or not path.is_file()
        ):
            return False
        with path.open("rb") as stream:
            head = stream.read(12)
            stream.seek(0)
            return (
                head[:4] == b"RIFF"
                and head[8:] == b"WEBP"
                and hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"]
            )
    except OSError:
        return False


def enqueue(db, chosen, settings, force=False):
    validate_settings(settings)
    queued = []
    skipped = []
    with connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR REPLACE INTO creature_image_config VALUES (1,?)",
            (json.dumps(settings),),
        )
        for record in chosen:
            specification = {
                **settings,
                **prompt(record),
                "seed": seed_for(record, settings["base_seed"]),
                "creature_id": record["id"],
                "stable_key": record["stable_key"],
                "scientific_name": record["scientific_name"],
            }
            # Runtime location and thread scheduling do not change intended pixels.
            identity = {
                k: v
                for k, v in specification.items()
                if k not in {"threads", "model_path", "output_dir"}
            }
            key = hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()
            ).hexdigest()
            active = conn.execute(
                "SELECT key FROM creature_image_jobs WHERE creature_id=? AND status IN ('queued','generating')",
                (record["id"],),
            ).fetchone()
            if active:
                queued.append(active["key"])
                continue
            asset = conn.execute(
                "SELECT * FROM creature_generated_images WHERE creature_id=?",
                (record["id"],),
            ).fetchone()
            if (
                not force
                and asset
                and json.loads(asset["metadata_json"]).get("recipe_key", asset["key"])
                == key
                and valid_asset(asset)
            ):
                skipped.append(record["id"])
                continue
            specification["recipe_key"] = key
            if force:
                key = hashlib.sha256((key + uuid.uuid4().hex).encode()).hexdigest()
            conn.execute(
                """INSERT INTO creature_image_jobs(key,creature_id,name,settings_json,status,updated) VALUES (?,?,?,?,'queued',?)
              ON CONFLICT(key) DO UPDATE SET status='queued',error=NULL,step=0,settings_json=excluded.settings_json,updated=excluded.updated""",
                (
                    key,
                    record["id"],
                    record["display_name"],
                    json.dumps(specification),
                    now(),
                ),
            )
            queued.append(key)
    return {"queued": queued, "skipped": skipped}


def retry_failed(db):
    count = 0
    with connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = {
            row[0]
            for row in conn.execute(
                "SELECT creature_id FROM creature_image_jobs WHERE status IN ('queued','generating')"
            )
        }
        seen = set()
        for job in conn.execute(
            "SELECT * FROM creature_image_jobs WHERE status='failed' ORDER BY updated DESC"
        ).fetchall():
            creature = job["creature_id"]
            if creature in seen or creature in active:
                continue
            seen.add(creature)
            asset = conn.execute(
                "SELECT * FROM creature_generated_images WHERE creature_id=?",
                (creature,),
            ).fetchone()
            if valid_asset(asset):
                continue
            conn.execute(
                "UPDATE creature_image_jobs SET status='queued',error=NULL,updated=? WHERE key=?",
                (now(), job["key"]),
            )
            count += 1
    return count


def status(db):
    with connect(db) as conn:
        total = conn.execute("SELECT COUNT(*) FROM creature_profiles").fetchone()[0]
        assets = conn.execute("SELECT * FROM creature_generated_images").fetchall()
        ready = sum(valid_asset(row) for row in assets)
        jobs = [
            dict(row)
            for row in conn.execute(
                "SELECT key,creature_id,name,status,attempts,error,elapsed,step,updated FROM creature_image_jobs ORDER BY updated DESC"
            )
        ]
        setting = conn.execute(
            "SELECT settings_json FROM creature_image_config WHERE id=1"
        ).fetchone()
        elapsed = [
            j["elapsed"]
            for j in jobs
            if j["status"] == "ready" and j["elapsed"] is not None
        ]
        mean = sum(elapsed) / len(elapsed) if elapsed else None
        return {
            "total": total,
            "generated": ready,
            "remaining": max(0, total - ready),
            "failed": sum(j["status"] == "failed" for j in jobs),
            "average_seconds": mean,
            "estimated_remaining_seconds": mean * max(0, total - ready)
            if mean is not None
            else None,
            "settings": json.loads(setting[0]) if setting else None,
            "jobs": jobs,
            "output_dir": str(output_root()),
        }


def render_asset(row):
    metadata = json.loads(row["metadata_json"])
    return {
        "url": f"/api/creature-images/files/{row['creature_id']}/{row['key']}",
        "key": row["key"],
        **metadata,
    }


def lock_path(db):
    return Path(db).resolve().with_suffix(".image-generation.lock")


def worker_running(db):
    with lock_path(db).open("a+") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(guard, fcntl.LOCK_UN)
    return False


def worker(db, backend_factory=None, progress=print, install_signals=True):
    from .backend import DiffusionBackend, Interrupted

    backend_factory = backend_factory or DiffusionBackend
    lock = lock_path(db)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"busy": True, "completed": 0, "failed": 0}
        stop = {"value": False}
        prior = {}
        if install_signals:
            for sig in (signal.SIGINT, signal.SIGTERM):
                prior[sig] = signal.signal(
                    sig, lambda *_: stop.__setitem__("value", True)
                )
        report = {"busy": False, "completed": 0, "failed": 0, "halted": False}
        backend = None
        loaded = None
        try:
            from app.importer.store import backup

            backup(db)
            with connect(db) as conn:
                conn.execute(
                    "UPDATE creature_image_jobs SET status='queued',error='Interrupted worker; retry pending' WHERE status='generating'"
                )
            try:
                os.nice(10)
            except OSError:
                pass
            while not stop["value"]:
                with connect(db) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT * FROM creature_image_jobs WHERE status='queued' ORDER BY updated LIMIT 1"
                    ).fetchone()
                    if not row:
                        break
                    job = dict(row)
                    conn.execute(
                        "UPDATE creature_image_jobs SET status='generating',attempts=attempts+1,updated=? WHERE key=?",
                        (now(), job["key"]),
                    )
                settings = json.loads(job["settings_json"])
                destination = file_for(settings, job["key"], job["name"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                logger = logging.getLogger("creature_images")
                handler = logging.FileHandler(destination.parent / "generation.log")
                handler.setFormatter(
                    logging.Formatter("%(asctime)s %(levelname)s %(message)s")
                )
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
                started = time.monotonic()
                temporary = destination.with_suffix(".png.part")
                webp = destination.with_suffix(".webp.part")
                try:
                    progress(
                        f"[{report['completed'] + report['failed'] + 1}] {job['name']}: generating on CPU ({settings['resolution']}px, {settings['steps']} steps)",
                        flush=True,
                    )
                    logger.info(
                        "Generating creature=%s id=%s key=%s",
                        job["name"],
                        job["creature_id"],
                        job["key"],
                    )
                    signature = (
                        settings["model_path"],
                        settings["revision"],
                        settings["threads"],
                    )
                    if loaded != signature:
                        if backend:
                            backend.close()
                        backend = None
                        loaded = None
                        backend = backend_factory(settings)
                        loaded = signature

                    def step(index):
                        with connect(db) as conn:
                            conn.execute(
                                "UPDATE creature_image_jobs SET step=?,updated=? WHERE key=?",
                                (index, now(), job["key"]),
                            )

                    backend.generate(settings, temporary, lambda: stop["value"], step)
                    if stop["value"]:
                        raise Interrupted("Stopped before publication")
                    from PIL import Image

                    with Image.open(temporary) as original:
                        if original.size != (
                            settings["resolution"],
                            settings["resolution"],
                        ):
                            raise ValueError(
                                "Backend output dimensions do not match requested resolution"
                            )
                        image = original.convert("RGB")
                        extrema = image.getextrema()
                        if all(high - low < 2 for low, high in extrema):
                            raise ValueError(
                                "Blank/constant output rejected; previous image preserved"
                            )
                        image.save(webp, format="WEBP", quality=90, method=6)
                    with Image.open(webp) as checked:
                        if checked.format != "WEBP":
                            raise ValueError("Output is not WebP")
                        checked.verify()
                    digest = hashlib.sha256(webp.read_bytes()).hexdigest()
                    elapsed = time.monotonic() - started
                    metadata = {
                        **settings,
                        "generated_at": now(),
                        "generation_seconds": elapsed,
                        "status": "ready",
                        "image_kind": "ai_generated",
                        "accuracy_verified": False,
                        "runtime": getattr(
                            backend, "info", {"backend": type(backend).__name__}
                        ),
                    }
                    # Publish validated pixels first; the old active manifest is changed only on success.
                    webp.replace(destination)
                    with connect(db) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        current = conn.execute(
                            "SELECT record_json FROM creature_profiles WHERE creature_id=?",
                            (job["creature_id"],),
                        ).fetchone()
                        if (
                            current is None
                            or json.loads(current[0])["scientific_name"]
                            != settings["scientific_name"]
                        ):
                            raise ValueError(
                                "Creature scientific identity changed during generation; enqueue again"
                            )
                        conn.execute(
                            "INSERT OR REPLACE INTO creature_generated_images VALUES (?,?,?,?,?,?)",
                            (
                                job["creature_id"],
                                job["key"],
                                str(destination),
                                str(destination.parent),
                                digest,
                                json.dumps(metadata),
                            ),
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO creature_generated_image_versions VALUES (?,?,?,?,?,?)",
                            (
                                job["key"],
                                job["creature_id"],
                                str(destination),
                                str(destination.parent),
                                digest,
                                json.dumps(metadata),
                            ),
                        )
                        conn.execute(
                            "UPDATE creatures SET image_reference=? WHERE id=?",
                            (
                                f"/api/creature-images/files/{job['creature_id']}/{job['key']}",
                                job["creature_id"],
                            ),
                        )
                        conn.execute(
                            "UPDATE creature_image_jobs SET status='ready',error=NULL,elapsed=?,step=?,updated=? WHERE key=?",
                            (elapsed, settings["steps"], now(), job["key"]),
                        )
                    report["completed"] += 1
                    summary = status(db)
                    pending_count = sum(
                        job["status"] == "queued" for job in summary["jobs"]
                    )
                    eta = (
                        summary["average_seconds"] * pending_count
                        if summary["average_seconds"] is not None
                        else None
                    )
                    progress(
                        f"Completed {job['name']} in {elapsed:.1f}s; saved {destination.name}. Generated {summary['generated']}/{summary['total']}; queued {pending_count}; measured run ETA {eta} seconds.",
                        flush=True,
                    )
                    logger.info(
                        "Completed creature=%s elapsed=%s", job["name"], elapsed
                    )
                except Interrupted as error:
                    report["interrupted"] = True
                    with connect(db) as conn:
                        conn.execute(
                            "UPDATE creature_image_jobs SET status='queued',error=?,updated=? WHERE key=?",
                            (str(error), now(), job["key"]),
                        )
                    stop["value"] = True
                except Exception as error:
                    # Catch backend failures, including RAM errors; never replace active artwork.
                    report["failed"] += 1
                    message = f"{type(error).__name__}: {error}"
                    with connect(db) as conn:
                        conn.execute(
                            "UPDATE creature_image_jobs SET status='failed',error=?,updated=? WHERE key=?",
                            (message, now(), job["key"]),
                        )
                    logger.exception(
                        "Failed creature=%s id=%s", job["name"], job["creature_id"]
                    )
                    progress(f"FAILED {job['name']}: {message}", flush=True)
                    if isinstance(error, (MemoryError, RuntimeError)):
                        report["halted"] = True
                        stop["value"] = True
                finally:
                    temporary.unlink(missing_ok=True)
                    webp.unlink(missing_ok=True)
                    logger.removeHandler(handler)
                    handler.close()
            return report
        except (OSError, sqlite3.Error) as error:
            report.update(
                failed=report["failed"] + 1,
                halted=True,
                error=f"{type(error).__name__}: {error}",
            )
            try:
                with connect(db) as conn:
                    conn.execute(
                        "UPDATE creature_image_jobs SET status='failed',error=?,updated=? WHERE status='generating'",
                        (report["error"], now()),
                    )
            except sqlite3.Error:
                pass
            progress("Worker stopped: " + report["error"], flush=True)
            logging.getLogger("creature_images").error(
                "Worker storage/database failure: %s", report["error"]
            )
            return report
        finally:
            if backend:
                backend.close()
            for sig, callback in prior.items():
                signal.signal(sig, callback)
