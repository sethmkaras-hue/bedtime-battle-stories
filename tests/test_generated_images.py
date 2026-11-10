"""Local image workflow uses synthetic backend output; no weights/network required."""

import copy
import fcntl
import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import main, library
from app.images import core
from app.images.prompts import prompt, seed_for, STYLE
from app.images.hardware import check
from app.images import routes
from test_importer import database
from test_parent_review import parent, login


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(core.os, "nice", lambda _: None)
    return {
        "model": core.MODEL_ID,
        "revision": "a" * 40,
        "model_path": str(tmp_path / "model"),
        "model_license": core.MODEL_LICENSE,
        "resolution": 512,
        "steps": 2,
        "guidance": 7.5,
        "threads": 2,
        "base_seed": 42,
        "output_dir": str(tmp_path / "generated"),
        "device": "cpu",
        "dtype": "float32",
        "batch_size": 1,
    }


def first(db):
    return core.records(db)[0]


class FixtureBackend:
    calls = 0

    def __init__(self, settings):
        pass

    def generate(
        self, settings, destination, stop=lambda: False, progress=lambda n: None
    ):
        from PIL import Image, ImageDraw

        type(self).calls += 1
        image = Image.new(
            "RGB", (settings["resolution"], settings["resolution"]), "navy"
        )
        ImageDraw.Draw(image).rectangle(
            (0, 0, settings["resolution"] // 2, settings["resolution"] // 2),
            fill="purple",
        )
        progress(1)
        image.save(destination, format="PNG")

    def close(self):
        pass


def generate(db, settings, force=False):
    pytest.importorskip("PIL.Image")
    core.enqueue(db, [first(db)], settings, force)
    return core.worker(
        db, FixtureBackend, progress=lambda *a, **k: None, install_signals=False
    )


def test_prompt_uses_only_reviewed_anatomical_evidence(database):
    record = first(database)
    record["physical_characteristics"] = ["Unsupported movie-inspired spikes"]
    record["description"] = "Unverified anatomy"
    positive = prompt(record)
    assert (
        STYLE in positive["prompt"] and record["scientific_name"] in positive["prompt"]
    )
    assert (
        "Unsupported" not in positive["prompt"]
        and "Unverified anatomy" not in positive["prompt"]
    )
    record["reviewed_fields"]["physical_characteristics"] = {
        "reviewer": "Fixture",
        "checked_on": "2026-11-01",
    }
    positive = prompt(record)
    assert "Unsupported movie-inspired spikes" in positive["prompt"]
    assert not positive["accuracy_verified"]
    # The phrase is deliberately synthetic: review stamps, not names, control use.
    assert seed_for(record) == seed_for(copy.deepcopy(record))


@pytest.mark.parametrize("category", ["dinosaur", "shark", "marine_reptile"])
def test_consistent_style_and_single_animal_constraints(database, category):
    record = first(database)
    record["category"] = category
    result = prompt(record)
    assert STYLE in result["prompt"] and "entire body" in result["prompt"]
    assert ("underwater" in result["prompt"]) is (category != "dinosaur")
    assert (
        "gore" in result["negative_prompt"] and "watermark" in result["negative_prompt"]
    )


def test_hardware_low_ram_fails_clearly(settings):
    with pytest.raises(RuntimeError, match="Insufficient available RAM"):
        check(settings, {"available_bytes": 1024**3})


def test_settings_paths_seeds_and_cpu_constraints(database, settings, tmp_path):
    record = first(database)
    result = core.enqueue(database, [record], settings)
    key = result["queued"][0]
    assert core.file_for(settings, key, "../../Tyrannosaurus").parent == Path(
        settings["output_dir"]
    )
    with core.connect(database) as conn:
        job = json.loads(
            conn.execute("SELECT settings_json FROM creature_image_jobs").fetchone()[0]
        )
    assert job["seed"] == seed_for(record) and job["device"] == "cpu"
    with pytest.raises(ValueError):
        core.validate_settings({**settings, "device": "cuda"})
    with pytest.raises(ValueError):
        core.file_for(settings, "../secret", "Creature")


def test_generation_persists_webp_and_preserves_scientific_profiles(database, settings):
    pytest.importorskip("PIL.Image")
    before = core.records(database)
    report = generate(database, settings)
    assert report["completed"] == 1 and report["failed"] == 0
    assert core.records(database) == before
    with core.connect(database) as conn:
        asset = conn.execute("SELECT * FROM creature_generated_images").fetchone()
    assert core.valid_asset(asset)
    metadata = json.loads(asset["metadata_json"])
    assert metadata["model"] == core.MODEL_ID and metadata["seed"] == seed_for(
        before[0]
    )
    assert metadata["status"] == "ready" and metadata["accuracy_verified"] is False
    assert core.status(database)["generated"] == 1


def test_resume_skips_valid_assets_and_deduplicates_queued_jobs(database, settings):
    FixtureBackend.calls = 0
    record = first(database)
    a = core.enqueue(database, [record], settings)
    b = core.enqueue(database, [record], settings, force=True)
    assert a["queued"] == b["queued"]
    generate(database, settings)
    assert core.enqueue(database, [record], settings)["skipped"] == [record["id"]]
    assert FixtureBackend.calls == 1


def test_failed_regeneration_keeps_previous_working_image(database, settings):
    pytest.importorskip("PIL.Image")
    generate(database, settings)
    with core.connect(database) as conn:
        old = dict(conn.execute("SELECT * FROM creature_generated_images").fetchone())
    old_bytes = Path(old["path"]).read_bytes()

    class Failure(FixtureBackend):
        def generate(self, *a, **k):
            raise MemoryError("Synthetic RAM failure")

    result = core.enqueue(database, [first(database)], settings, force=True)
    assert result["queued"][0] != old["key"]
    report = core.worker(
        database, Failure, progress=lambda *a, **k: None, install_signals=False
    )
    assert report["failed"] == 1 and Path(old["path"]).read_bytes() == old_bytes
    with core.connect(database) as conn:
        active = conn.execute("SELECT * FROM creature_generated_images").fetchone()
    assert active["key"] == old["key"] and core.valid_asset(active)


def test_retry_failed_and_interrupted_jobs(database, settings):
    pytest.importorskip("PIL.Image")
    result = core.enqueue(database, [first(database)], settings)
    with core.connect(database) as conn:
        conn.execute("UPDATE creature_image_jobs SET status='generating'")
    core.worker(
        database, FixtureBackend, progress=lambda *a, **k: None, install_signals=False
    )
    with core.connect(database) as conn:
        assert (
            conn.execute("SELECT status FROM creature_image_jobs").fetchone()[0]
            == "ready"
        )
    # Corrupt/missing files are regenerated, never treated as a completed cache.
    with core.connect(database) as conn:
        path = conn.execute("SELECT path FROM creature_generated_images").fetchone()[0]
    Path(path).unlink()
    assert core.enqueue(database, [first(database)], settings)["queued"]


def test_second_worker_cannot_load_another_model(database, settings):
    core.enqueue(database, [first(database)], settings)
    with Path(database).with_suffix(".image-generation.lock").open("a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def forbidden(*args):
            raise AssertionError("Second model must not load")

        assert core.worker(database, forbidden, install_signals=False)["busy"]


def test_fastapi_serves_registered_generated_image_and_overlays_cards(
    database, settings, monkeypatch
):
    pytest.importorskip("PIL.Image")
    generate(database, settings)
    monkeypatch.setattr(main, "DB", database)
    with TestClient(main.app) as client:
        creature = next(
            c
            for c in client.get("/api/creatures").json()
            if c["id"] == first(database)["id"]
        )
        assert (
            creature["image_kind"] == "ai_generated"
            and creature["profile"]["verification_status"] == "unverified"
        )
        response = client.get(creature["image_reference"])
        assert (
            response.status_code == 200
            and response.headers["content-type"] == "image/webp"
        )
        assert response.content[:4] == b"RIFF"
        assert client.get("/api/creature-images/files/1/not-a-key").status_code == 404
        assert client.get("/api/creature-images/status").json()["generated"] == 1


def test_regeneration_is_authenticated_queued_and_nonblocking(
    parent, settings, monkeypatch
):
    client, pid, folder = parent
    monkeypatch.setattr(routes, "runtime", lambda: Path(__file__))
    monkeypatch.setattr(core, "defaults", lambda: settings)
    started = []
    monkeypatch.setattr(routes, "launch", lambda db: started.append(db))
    body = {"creature_id": 1}
    assert (
        client.post("/api/admin/creature-images/regenerate", json=body).status_code
        == 401
    )
    response = client.post(
        "/api/admin/creature-images/regenerate", json=body, headers=login(client)
    )
    assert response.status_code == 202 and started
    first_key = response.json()["queued"][0]
    assert client.post(
        "/api/admin/creature-images/regenerate", json=body, headers=login(client)
    ).json()["queued"] == [first_key]
    assert (
        client.get("/api/creature-images/metadata/1").json()["jobs"][0]["settings"][
            "device"
        ]
        == "cpu"
    )


def test_successful_regeneration_retains_servable_immutable_old_version(
    database, settings, monkeypatch
):
    pytest.importorskip("PIL.Image")
    generate(database, settings)
    with core.connect(database) as conn:
        old = dict(conn.execute("SELECT * FROM creature_generated_images").fetchone())
    generate(database, settings, force=True)
    monkeypatch.setattr(main, "DB", database)
    with TestClient(main.app) as client:
        response = client.get(
            f"/api/creature-images/files/{old['creature_id']}/{old['key']}"
        )
        assert response.status_code == 200
    assert core.enqueue(database, [first(database)], settings)["skipped"]


def test_failed_generation_can_retry_successfully(database, settings):
    pytest.importorskip("PIL.Image")

    class Failure(FixtureBackend):
        def generate(self, *args, **kwargs):
            raise ValueError("Synthetic transient failure")

    core.enqueue(database, [first(database)], settings)
    assert (
        core.worker(
            database, Failure, progress=lambda *a, **k: None, install_signals=False
        )["failed"]
        == 1
    )
    generate(database, settings)
    assert (
        core.status(database)["generated"] == 1 and core.status(database)["failed"] == 0
    )


@pytest.mark.parametrize("bad", ["blank", "wrong_size"])
def test_invalid_backend_pixels_do_not_replace_existing_artwork(
    database, settings, bad
):
    pytest.importorskip("PIL.Image")
    generate(database, settings)
    with core.connect(database) as conn:
        old = dict(conn.execute("SELECT * FROM creature_generated_images").fetchone())

    class Invalid(FixtureBackend):
        def generate(self, settings, destination, *args):
            from PIL import Image

            Image.new(
                "RGB", (128, 128) if bad == "wrong_size" else (512, 512), "black"
            ).save(destination, format="PNG")

    core.enqueue(database, [first(database)], settings, force=True)
    assert (
        core.worker(
            database, Invalid, progress=lambda *a, **k: None, install_signals=False
        )["failed"]
        == 1
    )
    with core.connect(database) as conn:
        assert (
            conn.execute("SELECT key FROM creature_generated_images").fetchone()[0]
            == old["key"]
        )
    assert core.valid_asset(old)


def test_storage_failure_halts_without_loading_model(database, settings, monkeypatch):
    import logging

    core.enqueue(database, [first(database)], settings)

    def denied(*args, **kwargs):
        raise PermissionError("Synthetic output permission failure")

    monkeypatch.setattr(logging, "FileHandler", denied)

    def forbidden(*args):
        raise AssertionError("No model should load after storage failure")

    report = core.worker(
        database, forbidden, progress=lambda *a, **k: None, install_signals=False
    )
    assert report["halted"] and report["failed"] == 1
    assert core.status(database)["failed"] == 1


def test_clean_interruption_retains_queued_work(database, settings):
    from app.images.backend import Interrupted

    class Stop(FixtureBackend):
        def generate(self, *args, **kwargs):
            raise Interrupted("Synthetic stop request")

    core.enqueue(database, [first(database)], settings)
    report = core.worker(
        database, Stop, progress=lambda *a, **k: None, install_signals=False
    )
    assert report["interrupted"] and report["completed"] == 0
    with core.connect(database) as conn:
        assert (
            conn.execute("SELECT status FROM creature_image_jobs").fetchone()[0]
            == "queued"
        )


def test_cli_can_stage_batch_without_loading_model(database, settings, monkeypatch):
    from scripts import generate_creature_images
    import sys

    monkeypatch.setattr(core, "defaults", lambda: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_creature_images.py",
            "--pilot",
            "1",
            "--enqueue-only",
            "--db",
            str(database),
        ],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Enqueue-only must not start diffusion")

    monkeypatch.setattr(core, "worker", forbidden)
    assert generate_creature_images.main() == 0
    with core.connect(database) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM creature_image_jobs WHERE status='queued'"
            ).fetchone()[0]
            == 1
        )


def test_external_cli_worker_is_detected_without_spawning_another(database):
    assert not core.worker_running(database)
    with core.lock_path(database).open("a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert core.worker_running(database)
    assert not core.worker_running(database)


def test_normal_scientific_import_does_not_search_images(database, tmp_path):
    from test_importer import FakeClient
    from app.importer.runner import execute

    class ScienceOnly(FakeClient):
        def json(self, *args, **kwargs):
            raise AssertionError("Normal scientific import must not search Commons")

    report = execute(
        database,
        tmp_path / "scientific",
        pilot=1,
        client=ScienceOnly(),
        progress=lambda *a, **k: None,
    )
    assert report["processed"] == 1 and report["proposals"][0]["images"] == 0


def test_resume_does_not_replay_stale_failed_versions_over_a_working_image(
    database, settings
):
    pytest.importorskip("PIL.Image")

    class Failure(FixtureBackend):
        def generate(self, *a, **k):
            raise ValueError("Synthetic failed version")

    core.enqueue(database, [first(database)], settings)
    core.worker(database, Failure, progress=lambda *a, **k: None, install_signals=False)
    assert core.retry_failed(database) == 1
    core.worker(database, Failure, progress=lambda *a, **k: None, install_signals=False)
    generate(database, settings, force=True)
    assert core.retry_failed(database) == 0
