"""All reviewed records/media below are synthetic test fixtures, not catalog evidence."""

import copy
import json
from pathlib import Path
import sqlite3
import wave
import pytest
from fastapi.testclient import TestClient
from app import main, library
from app.audio.service import AudioService
from scripts.generate_pronunciations import generate


def record(key="test:fixture", **updates):
    data = {
        "stable_key": key,
        "display_name": "Test fixture",
        "scientific_name": "Fixture testensis",
        "category": "dinosaur",
        "taxon_group": "dinosaur",
        "taxon_rank": "species",
        "habitat": "land",
        "description": "Synthetic test data, not a scientific claim.",
    }
    data.update(updates)
    return data


def verified_pronunciation():
    return {
        "status": "verified",
        "phonetic": "test FIK chur",
        "stress": "Second syllable",
        "tts_text": "test fixture",
        "source_url": "https://example.test/fixture",
        "verified_by": "Test fixture reviewer",
        "checked_on": "2026-01-01",
    }


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "library.sqlite3")
    monkeypatch.setattr(main, "CATALOG", False)
    monkeypatch.setattr(main, "SAMPLE", False)
    monkeypatch.setenv("BBS_AUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("BBS_MODEL_DIR", str(tmp_path / "models"))
    main.initialize_database()
    return main.DB


def test_migrations_and_import_preserve_ids_and_verified_fields(database):
    with sqlite3.connect(database) as conn:
        library.import_records(
            conn, [record(id=100, pronunciation=verified_pronunciation())]
        )
        library.import_records(conn, [record(display_name="A new display label")])
        row = json.loads(
            conn.execute("SELECT record_json FROM creature_profiles").fetchone()[0]
        )
        assert row["id"] == 100 and row["pronunciation"]["status"] == "verified"
        assert conn.execute("SELECT id FROM creatures").fetchone()[0] == 100
        assert (
            conn.execute("SELECT COUNT(*) FROM library_migrations").fetchone()[0] == 1
        )
    main.initialize_database()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM creatures").fetchone()[0] == 1


def test_duplicate_taxa_ids_and_conflicts(database):
    with pytest.raises(ValueError):
        library.validate_records([record(), record(key="test:other")], False)
    with pytest.raises(ValueError):
        library.validate_records(
            [
                record(id=3),
                record(key="test:other", scientific_name="Another taxon", id=3),
            ],
            False,
        )
    with sqlite3.connect(database) as conn:
        library.import_records(conn, [record(id=3)])
    with pytest.raises(ValueError), sqlite3.connect(database) as conn:
        library.import_records(conn, [record(id=4)])
    with pytest.raises(ValueError), sqlite3.connect(database) as conn:
        library.import_records(
            conn, [record(key="test:another", id=3, scientific_name="Another taxon")]
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"length": {"minimum": 0, "maximum": 1, "unit": "m"}},
        {"length": {"minimum": 2, "maximum": 1, "unit": "m", "source_ids": ["source"]}},
        {"taxon_group": "pterosaur"},
        {"pronunciation": {"status": "verified", "phonetic": "invented"}},
        {"discovery_tags": ["fast_swimmers"]},
        {"image": {"placeholder": False, "license": "unknown"}},
    ],
)
def test_invalid_measurements_taxonomy_and_unsupported_claims(updates):
    with pytest.raises(ValueError):
        library.validate_records([record(**updates)], False)


def test_image_metadata_and_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "ROOT", tmp_path)
    art = {
        "placeholder": False,
        "path": "/static/creatures/test.webp",
        "creator": "Test artist",
        "original_source_url": "https://example.test/image",
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": "Test artist, synthetic fixture",
        "modifications": "Synthetic test image",
        "identified_taxon": "Fixture testensis",
        "verified_by": "Test reviewer",
        "checked_on": "2026-01-01",
    }
    with pytest.raises(ValueError, match="Missing image"):
        library.validate_records([record(image=art)])
    PIL = pytest.importorskip("PIL.Image")
    path = tmp_path / "static/creatures/test.webp"
    path.parent.mkdir(parents=True)
    PIL.new("RGB", (8, 8), "navy").save(path, format="WEBP")
    assert library.validate_records([record(image=art)])[0].image.license == "CC0-1.0"
    art["identified_taxon"] = "Unrelated species"
    with pytest.raises(ValueError):
        library.validate_records([record(image=art)])
    with pytest.raises(ValueError):
        library.local_asset("/static/../../secret")


class FakeProvider:
    name = "kokoro"

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def get_provider_info(self):
        return {"available": True, "voices": self.list_voices()}

    def list_voices(self):
        return [{"id": "test", "name": "Test"}]

    def version(self):
        return "fixture-v1"

    def generate_audio(self, text, voice, speed, destination):
        self.calls += 1
        with wave.open(str(destination), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"\0\0" * 800)


def test_bulk_generation_reuses_cache_and_does_not_generate_unverified(
    database, tmp_path
):
    provider = FakeProvider()
    service = AudioService(
        tmp_path / "cache", tmp_path / "models", {"kokoro": provider}
    )
    try:
        with sqlite3.connect(database) as conn:
            library.import_records(
                conn,
                [
                    record(pronunciation=verified_pronunciation()),
                    record(
                        key="test:unreviewed",
                        display_name="Other fixture",
                        scientific_name="Other fixture",
                    ),
                ],
            )
            a = generate(conn, service, voice="test")
            b = generate(conn, service, voice="test")
            assert (
                a["generated"] == 1 and len(a["unverified"]) == 1 and b["reused"] == 1
            )
            assert provider.calls == 1
            audit = library.audit(conn, service.root)
            assert (
                audit["ready_pronunciations"] == 1
                and audit["verified_pronunciations"] == 1
            )
            assert len(list((service.root / "pronunciation").glob("*.wav"))) == 1
            with pytest.raises(ValueError):
                generate(conn, service, provider="openai")
    finally:
        service.close()


def test_prebuilt_audio_api_never_submits_tts(database, tmp_path, monkeypatch):
    provider = FakeProvider()
    service = AudioService(
        tmp_path / "cache", tmp_path / "models", {"kokoro": provider}
    )
    monkeypatch.setattr(main, "create_service", lambda: service)
    with sqlite3.connect(database) as conn:
        library.import_records(
            conn, [record(id=7, pronunciation=verified_pronunciation())]
        )
        generate(conn, service, voice="test")

    def forbidden(*args, **kwargs):
        pytest.fail("Browsing/playback must not submit synthesis")

    monkeypatch.setattr(service, "submit", forbidden)
    with TestClient(main.app) as c:
        creature = c.get("/api/library/creatures/7").json()
        url = creature["pronunciation_audio"]["url"]
        assert c.get(url).status_code == 200
        assert c.get("/api/creatures").json()[0]["id"] == 7
        assert c.get("/api/library/creatures/999").status_code == 404
        assert c.get("/api/library/attributions").json() == []
        assert c.get("/api/library/audit").json()["ready_pronunciations"] == 1
        for path in (service.root / "pronunciation").glob("*.wav"):
            path.unlink()
        assert c.get(url).status_code == 404
        assert c.get("/api/library/creatures/7").json()["pronunciation_audio"] is None
    with sqlite3.connect(database) as conn:
        assert (
            conn.execute("SELECT count(*) FROM library_asset_issues").fetchone()[0] == 1
        )


def test_game_rating_is_separate_from_profile_display_name(database):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO creatures(id,name,scientific_name,category,habitat) VALUES (1,'Tyrannosaurus','Tyrannosaurus','dinosaur','land')"
        )
    main.initialize_database()
    rows = main.creatures()
    assert rows[0]["gameplay_rating"] == 5
    from app.adventure import rating, chapter

    renamed = {**rows[0], "name": "A different display name"}
    assert rating(renamed) == 5
    assert (
        chapter(rows[0], renamed, rows[0], "short", "land", "r0m0")[
            "verified_creature_context"
        ]
        == []
    )


def test_bundled_audit_does_not_fabricate_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "bundled.sqlite3")
    monkeypatch.setattr(main, "SAMPLE", False)
    monkeypatch.setattr(main, "CATALOG", True)
    main.initialize_database()
    with sqlite3.connect(main.DB) as conn:
        audit = library.audit(conn, tmp_path / "cache")
    assert audit["counts"] == {"dinosaur": 110, "shark": 42, "marine_reptile": 12}
    assert audit["total"] == 164 and audit["placeholders"] == 164
    assert (
        audit["licensed_images"]
        == audit["verified_pronunciations"]
        == audit["ready_pronunciations"]
        == 0
    )
    assert all(value == 0 for value in audit["verified_counts"].values())
    assert len(audit["records"]) == 164


def reviewed_record(**updates):
    fields = [
        "taxonomy",
        "description",
        "time_period",
        "habitat",
        "diet",
        "fun_facts",
        "physical_characteristics",
        "geographic_distribution",
    ]
    return record(
        verification_status="verified",
        verified_by="Test reviewer",
        checked_on="2026-01-01",
        subcategory="Test fixture group",
        time_period="Test fixture period",
        geographic_distribution=["Test fixture place"],
        physical_characteristics=["Synthetic test trait"],
        fun_facts=["Fixture one.", "Fixture two.", "Fixture three."],
        sources=[
            {
                "id": "fixture-source",
                "title": "Synthetic source, not a real citation",
                "url": "https://example.test/source",
                "checked_on": "2026-01-01",
                "supports": fields,
            }
        ],
        **updates,
    )


def test_verified_profiles_are_protected_and_unknown_measurements_allowed(database):
    with sqlite3.connect(database) as conn:
        library.import_records(conn, [reviewed_record()])
        result = library.import_records(
            conn, [record(description="Do not overwrite the reviewed fixture")]
        )
        assert result["protected"] == 1
        assert (
            json.loads(
                conn.execute("SELECT record_json FROM creature_profiles").fetchone()[0]
            )["description"]
            == "Synthetic test data, not a scientific claim."
        )
        assert (
            library.audit(conn, Path(database).parent / "cache")["verified_counts"][
                "dinosaur"
            ]
            == 1
        )


def test_reviewed_facts_reach_stories_without_changing_outcome_rules(database):
    from app.adventure import chapter

    with sqlite3.connect(database) as conn:
        library.import_records(conn, [reviewed_record()])
    c = main.creatures()[0]
    data = chapter(c, c, c, "short", "land", "r0m0")
    assert data["verified_creature_context"][0]["facts"] == [
        "Fixture one.",
        "Fixture two.",
        "Fixture three.",
    ]
    assert "Fixture one." in " ".join(data["paragraphs"])
    assert c["gameplay_rating"] == 3 and "gameplay_rating" not in c["profile"]


def test_media_optimization_produces_local_webp_with_attribution(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    from scripts.prepare_image import prepare

    monkeypatch.setattr(library, "ROOT", tmp_path)
    source = tmp_path / "source.png"
    PIL.new("RGB", (1200, 800), "navy").save(source)
    metadata = {
        "placeholder": False,
        "path": "/static/creatures/pending.webp",
        "creator": "Test artist",
        "original_source_url": "https://example.test/image",
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": "Synthetic test fixture",
        "modifications": "Original test image",
        "identified_taxon": "Fixture testensis",
        "verified_by": "Test reviewer",
        "checked_on": "2026-01-01",
    }
    image = prepare(source, metadata, "fixture")
    assert set(image["variants"]) == {"320", "640", "960"}
    assert image["creator"] == "Test artist" and "WebP" in image["modifications"]
    for width, path in image["variants"].items():
        with PIL.open(library.local_asset(path)) as f:
            assert f.format == "WEBP" and f.width == int(width)


def test_newer_migration_is_not_silently_downgraded(tmp_path):
    with sqlite3.connect(tmp_path / "future.sqlite3") as conn:
        conn.execute("CREATE TABLE library_migrations(version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO library_migrations VALUES (99)")
        with pytest.raises(ValueError, match="newer"):
            library.migrate(conn)


def test_unknown_habitat_does_not_break_random_compatible_selection(database):
    with sqlite3.connect(database) as conn:
        rows = [
            record(
                key=f"test:shark-{i}",
                display_name=f"Test shark {i}",
                scientific_name=f"Fixture shark {i}",
                category="shark",
                taxon_group="shark",
                habitat="marine",
            )
            for i in range(8)
        ]
        rows.append(
            record(
                key="test:unknown-shark",
                display_name="Unknown habitat fixture",
                scientific_name="Unknown fixture shark",
                category="shark",
                taxon_group="shark",
                habitat="unknown",
            )
        )
        library.import_records(conn, rows)
    known = main.random_selection("shark")["creature_ids"]
    assert len(known) == 8
    unknown = next(c for c in main.creatures() if c["habitat"] == "unknown")
    assert not unknown["eligible_for_tournament"] and unknown["id"] not in known


def test_search_uses_reviewed_display_name_without_rewriting_legacy_rows(database):
    with sqlite3.connect(database) as conn:
        library.import_records(conn, [record()])
        library.import_records(
            conn, [reviewed_record(display_name="Reviewed fixture title")]
        )
    assert len(main.creatures(q="reviewed fixture")) == 1
    with sqlite3.connect(database) as conn:
        assert (
            conn.execute("SELECT name FROM creatures").fetchone()[0] == "Test fixture"
        )
