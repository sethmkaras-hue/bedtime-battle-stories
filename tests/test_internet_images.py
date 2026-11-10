"""Automatic local imports with synthetic images and fully mocked HTTP."""

import copy
import io
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_importer import database  # noqa: F401

from app import main
from app.importer import internet_images as images
from app.importer.network import PoliteClient, SourceUnavailable


def first(db):
    with sqlite3.connect(db) as conn:
        return json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles ORDER BY creature_id LIMIT 1"
            ).fetchone()[0]
        )


def pixels(color="navy", size=(800, 600), format="PNG"):
    Image = pytest.importorskip("PIL.Image")
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=format)
    return output.getvalue()


def info(name="Tyrannosaurus rex", **overrides):
    result = {
        "url": "https://upload.wikimedia.org/fixture.png",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture",
        "width": 1200,
        "height": 800,
        "mime": "image/png",
        "extmetadata": {
            "ImageDescription": {
                "value": name + " life restoration, full-body reconstruction"
            }
        },
    }
    result.update(overrides)
    return result


def chosen(record, **overrides):
    return images.candidate(
        info(record["scientific_name"], **overrides),
        {"title": "File:" + record["scientific_name"]},
        record,
    )


@pytest.mark.parametrize(
    "rights", [None, "All rights reserved", "CC BY-NC 4.0", "Unknown"]
)
def test_rights_metadata_never_gates_selection(database, rights):
    record = first(database)
    data = info(record["scientific_name"])
    if rights:
        data["extmetadata"]["LicenseShortName"] = {"value": rights}
    result = images.candidate(
        data, {"title": "File:" + record["scientific_name"]}, record
    )
    assert result["supported"] and result["creator"] is None
    assert result["license"] == rights
    assert images.ranked([result]) == [result]


def test_rank_prioritizes_identity_then_quality_then_open_tie(database):
    top = chosen(first(database))
    low = copy.deepcopy(top)
    low.update(identity_confidence=90, quality_score=1000, open_license=True)
    assert images.ranked([low, top])[0] == top
    open_version = {**top, "open_license": True, "license": "CC0"}
    assert images.ranked([top, open_version])[0] == open_version
    fossil = chosen(first(database))
    fossil["quality_score"] -= 25
    assert images.ranked([fossil, top])[0] == top


@pytest.mark.parametrize(
    "description",
    [
        "Triceratops restoration",
        "Tyrannosaurus rex versus Triceratops",
        "Tyrannosaurus rex cartoon toy",
        "Probably Tyrannosaurus rex",
    ],
)
def test_wrong_ambiguous_and_child_unsuitable_images_rejected(description):
    record = {"scientific_name": "Tyrannosaurus rex", "category": "dinosaur"}
    item = info()
    item["extmetadata"]["ImageDescription"]["value"] = description
    assert not images.candidate(item, {"title": "File:Tyrannosaurus rex"}, record)[
        "supported"
    ]


def test_another_species_title_rejected():
    record = {
        "scientific_name": "Tyrannosaurus rex",
        "category": "dinosaur",
        "_other_taxa": ["Triceratops"],
    }
    assert not images.candidate(info(), {"title": "File:Triceratops"}, record)[
        "supported"
    ]


def test_sharks_require_photo_and_exact_species():
    record = {
        "scientific_name": "Carcharodon carcharias",
        "category": "shark",
        "modern_status": "living",
    }
    data = info("Carcharodon carcharias", mime="image/jpeg")
    data["extmetadata"]["ImageDescription"]["value"] = (
        "Carcharodon carcharias underwater photograph"
    )
    assert images.candidate(data, {"title": "File:Carcharodon carcharias"}, record)[
        "supported"
    ]
    data["extmetadata"]["ImageDescription"]["value"] = "Carcharodon carcharias painting"
    assert not images.candidate(data, {"title": "File:Carcharodon carcharias"}, record)[
        "supported"
    ]


def test_search_pagination_categories_deduplication_no_wikidata(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "commons.wikimedia.org"
        assert request.url.path != "/robots.txt"
        params = request.url.params
        assert params["iiprop"] == "url|size|mime|extmetadata"
        assert params.get("gsrlimit", params.get("gcmlimit")) == "50"
        if params.get("generator") == "categorymembers":
            return httpx.Response(200, json={"query": {"pages": {}}})
        offset = int(params.get("gsroffset", 0))
        data = {
            "query": {
                "pages": {
                    str(n): {
                        "pageid": n,
                        "title": "File:Tyrannosaurus rex " + str(n),
                        "imageinfo": [
                            info(url=f"https://upload.wikimedia.org/{n}.png")
                        ],
                    }
                    for n in range(offset, offset + 20)
                }
            }
        }
        if not offset:
            data["continue"] = {"gsroffset": 20, "continue": "gsroffset||"}
        return httpx.Response(200, json=data)

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        found, errors = images.discover(
            client,
            {
                "scientific_name": "Tyrannosaurus rex",
                "display_name": "Tyrannosaurus",
                "category": "dinosaur",
                "synonyms": ["Manospondylus"],
            },
        )
        assert len(found) == 40 and not errors
        assert any("gsroffset" in c.url.params for c in calls)
        assert any(c.url.params.get("generator") == "categorymembers" for c in calls)
        assert any("Manospondylus" in c.url.params.get("gsrsearch", "") for c in calls)
    finally:
        client.close()


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_install_webp_and_preserve_science_audio(database, tmp_path, format):
    original = first(database)
    assert images.install(
        database, original, chosen(original), pixels(format=format), tmp_path / "images"
    )
    assert first(database) == original
    with images.connect(database) as conn:
        asset = dict(conn.execute("SELECT * FROM internet_creature_images").fetchone())
        assert images.valid_asset(asset)
        metadata = json.loads(asset["metadata_json"])
        assert metadata["license"] is None and metadata["private_local_only"]
        assert Path(asset["path"]).read_bytes()[8:12] == b"WEBP"
        assert (
            conn.execute(
                "SELECT image_reference FROM creatures WHERE id=?", (original["id"],)
            )
            .fetchone()[0]
            .startswith("/api/library/images/")
        )


def test_failed_or_lower_confidence_replacement_preserves_image(database, tmp_path):
    record = first(database)
    item = chosen(record)
    images.install(database, record, item, pixels(), tmp_path)
    with images.connect(database) as conn:
        old = dict(conn.execute("SELECT * FROM internet_creature_images").fetchone())
    with pytest.raises((ValueError, OSError)):
        images.install(database, record, item, b"not an image", tmp_path)
    worse = {**item, "identity_confidence": 70}
    assert not images.install(database, record, worse, pixels("red"), tmp_path)
    with images.connect(database) as conn:
        assert (
            dict(conn.execute("SELECT * FROM internet_creature_images").fetchone())
            == old
        )


def test_identity_change_during_download_refuses_database_write(database, tmp_path):
    record = first(database)
    changed = copy.deepcopy(record)
    changed["scientific_name"] = "Other species"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE creature_profiles SET record_json=? WHERE creature_id=?",
            (json.dumps(changed), record["id"]),
        )
    with pytest.raises(ValueError, match="identity changed"):
        images.install(database, record, chosen(record), pixels(), tmp_path)
    with images.connect(database) as conn:
        assert not conn.execute("SELECT * FROM internet_creature_images").fetchall()


def test_file_versions_served_with_correct_mime_and_cache(
    database, tmp_path, monkeypatch
):
    record = first(database)
    monkeypatch.setattr(main, "DB", database)
    item = chosen(record)
    images.install(database, record, item, pixels(), tmp_path)
    with sqlite3.connect(database) as conn:
        old = images.render(images.registered(conn)[record["id"]])["url"]
    images.install(database, record, item, pixels("red"), tmp_path)
    with TestClient(main.app) as client:
        result = next(
            c for c in client.get("/api/creatures").json() if c["id"] == record["id"]
        )
        assert result["image_kind"] == "internet" and "generated_image" not in result
        assert result["image_reference"] != old
        for url in [old, result["image_reference"]]:
            response = client.get(url)
            assert (
                response.status_code == 200
                and response.headers["content-type"] == "image/webp"
            )
            assert "immutable" in response.headers["cache-control"]
        assert client.get("/api/library/images/1/not-a-key").status_code == 404
        assert client.get("/api/library/image-coverage").json()["internet_images"] == 1
        assert any(
            c["image"].get("license") is None
            for c in client.get("/api/library/sources-credits").json()
        )


def test_production_approval_and_generation_routes_absent(database, monkeypatch):
    monkeypatch.setattr(main, "DB", database)
    with TestClient(main.app) as client:
        assert (
            client.post(
                "/api/admin/proposals/1/decision", json={"decision": "approve"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/admin/creature-images/regenerate", json={"creature_id": 1}
            ).status_code
            == 404
        )
        html = client.get("/").text
        assert 'id="open-parent-review"' not in html
        assert 'id="regenerate-creature-image"' not in html
        assert "Sources &amp; Credits" in html


def test_304_without_valid_cache_retries_unconditionally(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert "if-none-match" not in request.headers
        return httpx.Response(304 if len(calls) == 1 else 200, content=b"content")

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        assert client.get("https://upload.wikimedia.org/a.png").content == b"content"
        assert len(calls) == 2
    finally:
        client.close()


def test_304_reuses_valid_download_and_429_honors_retry(tmp_path):
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if len(calls) == 2:
            return httpx.Response(200, content=b"cached", headers={"ETag": '"one"'})
        assert request.headers["if-none-match"] == '"one"'
        return httpx.Response(304)

    client = PoliteClient(
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        refresh=True,
    )
    try:
        assert client.get("https://upload.wikimedia.org/a.png").content == b"cached"
        assert client.get("https://upload.wikimedia.org/a.png").content == b"cached"
        assert 7 in sleeps and client.cache_hits == 1
    finally:
        client.close()


class FixtureClient:
    respect_robots = False
    requests = 0
    cache_hits = 0
    events = []

    def get(self, url, limit=0):
        self.requests += 1
        return httpx.Response(
            200, content=pixels(), headers={"content-type": "image/png"}
        )


def test_automatic_resume_and_independent_science_failure(
    database, tmp_path, monkeypatch
):
    client = FixtureClient()
    record = first(database)
    monkeypatch.setenv("BBS_CREATURE_IMAGE_DIR", str(tmp_path / "images"))

    def discover(client, record, use_wikidata=False):
        return [chosen(record)], []

    monkeypatch.setattr(images, "discover", discover)
    monkeypatch.setattr(
        images.sources, "science", lambda *a: ({}, [], ["PBDB HTTP 403"])
    )
    run = lambda **kw: images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        client=client,
        progress=lambda *a, **k: None,
        **kw,
    )
    report = run()
    assert report["images_installed"] == 1 and report["science_updated"] == 0
    assert client.requests == 1 and first(database) == record
    second = run()
    assert (
        second["images_installed"] == 0
        and second["images_retained"] == 1
        and client.requests == 1
    )
    with images.connect(database) as conn:
        asset = dict(conn.execute("SELECT * FROM internet_creature_images").fetchone())
    Path(asset["path"]).unlink()
    assert run()["images_installed"] == 1 and client.requests == 2


def test_bad_first_download_tries_next_candidate(database, tmp_path, monkeypatch):
    record = first(database)
    top = chosen(record)
    second = {
        **top,
        "quality_score": top["quality_score"] - 1,
        "download_url": "https://upload.wikimedia.org/second.png",
    }

    class Client(FixtureClient):
        def get(self, url, limit=0):
            if url == top["download_url"]:
                raise SourceUnavailable("HTTP 403; access denied")
            return super().get(url, limit)

    monkeypatch.setenv("BBS_CREATURE_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(images, "discover", lambda *a: ([top, second], []))
    report = images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        client=Client(),
        offline=False,
        progress=lambda *a, **k: None,
    )
    assert report["images_installed"] == 1 and report["failed_downloads"] == 1


def test_dry_run_preserves_database_and_does_not_download(
    database, tmp_path, monkeypatch
):
    client = FixtureClient()
    before = Path(database).read_bytes()
    monkeypatch.setattr(
        images, "discover", lambda client, record, *args: ([chosen(record)], [])
    )
    monkeypatch.setattr(images.sources, "science", lambda *a: ({}, [], []))
    report = images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        dry_run=True,
        client=client,
        progress=lambda *a, **k: None,
    )
    assert not report["images_installed"] and not client.requests
    assert Path(database).read_bytes() == before


def test_scientific_updates_survive_image_failure(database, tmp_path, monkeypatch):
    monkeypatch.setattr(
        images.sources,
        "science",
        lambda *a: (
            {"time_period": "Fixture interval"},
            [
                {
                    "id": "fixture",
                    "title": "Fixture",
                    "url": "https://paleobiodb.org/test",
                    "supports": ["time_period"],
                }
            ],
            [],
        ),
    )
    monkeypatch.setattr(images, "discover", lambda *a: ([], ["Commons HTTP 403"]))
    report = images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        client=FixtureClient(),
        progress=lambda *a, **k: None,
    )
    assert report["science_updated"] == 1 and not report["images_installed"]
    assert first(database)["time_period"] == "Fixture interval"


def test_private_manual_manifest_accepts_missing_license(
    database, tmp_path, monkeypatch
):
    monkeypatch.setenv("BBS_CREATURE_IMAGE_DIR", str(tmp_path / "installed"))
    from app.importer.image_files import load_images

    record = first(database)
    (tmp_path / "photo.png").write_bytes(pixels())
    metadata = {
        "title": record["scientific_name"] + " restoration",
        "identified_taxon": record["scientific_name"],
        "source_url": "https://example.org/fixture",
        "description": record["scientific_name"] + " life restoration",
        "identity_evidence": "Exact supplied caption",
        "identity_status": "supported",
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    manifest = {
        "schema_version": 1,
        "entries": [
            {
                "scientific_name": record["scientific_name"],
                "image_file": "photo.png",
                "metadata_file": "metadata.json",
                "source_kind": "licensed_reference",
                "retrieved_on": "2026-11-01",
            }
        ],
    }
    (tmp_path / "images.json").write_text(json.dumps(manifest))
    references = load_images(tmp_path / "images.json", private=True)
    report = images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        offline=True,
        image_references=references,
        client=FixtureClient(),
        progress=lambda *a, **k: None,
    )
    assert report["images_installed"] == 1
    with sqlite3.connect(database) as conn:
        metadata = images.render(images.registered(conn)[record["id"]])
    assert (
        metadata["license"] is None
        and metadata["original_source_url"] == "https://example.org/fixture"
    )


def test_unverified_pronunciation_is_saved_without_approval_or_false_verification(
    database,
):
    record = first(database)
    guidance = {
        "status": "unverified",
        "phonetic": "fixture-PHON",
        "stress": "PHON",
        "tts_text": "fixture phon",
        "source_url": "https://example.org/reference",
    }
    assert images.automatic_pronunciation(database, record, guidance)
    saved = first(database)["pronunciation"]
    assert saved["phonetic"] == "fixture-PHON" and saved["status"] == "unverified"
    assert saved["verified_by"] is None


def test_verified_supplied_pronunciation_applies_without_parent_endpoint(database):
    record = first(database)
    guidance = {
        "status": "unverified",
        "phonetic": "fixture-PHON",
        "stress": "PHON",
        "tts_text": "fixture phon",
        "source_url": "https://example.org/reference",
        "source_verification": {
            "status": "verified",
            "verified_by": "Supplied source inspector",
            "checked_on": "2026-11-01",
        },
    }
    assert images.automatic_pronunciation(database, record, guidance)
    saved = first(database)["pronunciation"]
    assert (
        saved["status"] == "verified"
        and saved["verified_by"] == "Supplied source inspector"
    )
    assert not images.automatic_pronunciation(
        database, first(database), {"phonetic": "replacement"}
    )


def test_gbif_alternative_requires_exact_species_and_supported_media_host():
    record = {
        "scientific_name": "Carcharodon carcharias",
        "category": "shark",
        "modern_status": "living",
    }

    class GBIF:
        def json(self, url, params):
            if url == images.sources.GBIF:
                return {
                    "matchType": "EXACT",
                    "status": "ACCEPTED",
                    "canonicalName": record["scientific_name"],
                    "rank": "SPECIES",
                    "kingdom": "Animalia",
                    "confidence": 100,
                    "usageKey": 1,
                }
            return {
                "results": [
                    {
                        "key": 12,
                        "species": record["scientific_name"],
                        "media": [
                            {
                                "type": "StillImage",
                                "identifier": "https://static.inaturalist.org/photos/1.jpg",
                                "format": "image/jpeg",
                            }
                        ],
                    },
                    {
                        "key": 13,
                        "species": "Other species",
                        "media": [
                            {
                                "type": "StillImage",
                                "identifier": "https://static.inaturalist.org/wrong.jpg",
                            }
                        ],
                    },
                ]
            }

    found, issues = images.gbif_images(GBIF(), record)
    assert len(found) == 1 and not issues and found[0]["supported"]
    assert found[0]["license"] is None


def test_database_failure_keeps_working_manifest(database, tmp_path, monkeypatch):
    record = first(database)
    item = chosen(record)
    images.install(database, record, item, pixels(), tmp_path)
    with sqlite3.connect(database) as conn:
        old = images.registered(conn)[record["id"]]

    def fail(*a):
        raise sqlite3.OperationalError("fixture disk full")

    monkeypatch.setattr(images, "connect", fail)
    with pytest.raises(sqlite3.OperationalError):
        images.install(database, record, item, pixels("red"), tmp_path)
    with sqlite3.connect(database) as conn:
        assert images.registered(conn)[record["id"]] == old
    assert images.valid_asset(old)


def test_science_inspected_fields_remain_protected(database, tmp_path, monkeypatch):
    record = first(database)
    record["time_period"] = "Inspected interval"
    record["reviewed_fields"]["time_period"] = {
        "reviewer": "Fixture",
        "checked_on": "2026-11-01",
    }
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE creature_profiles SET record_json=? WHERE creature_id=?",
            (json.dumps(record), record["id"]),
        )
    monkeypatch.setattr(
        images.sources,
        "science",
        lambda *a: (
            {"time_period": "Lower-priority replacement"},
            [
                {
                    "id": "fixture",
                    "title": "Fixture",
                    "url": "https://paleobiodb.org/test",
                    "supports": ["time_period"],
                }
            ],
            [],
        ),
    )
    monkeypatch.setattr(images, "discover", lambda *a: ([], []))
    images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        client=FixtureClient(),
        progress=lambda *a, **k: None,
    )
    assert first(database)["time_period"] == "Inspected interval"


def test_changed_pronunciation_references_invalidate_science_checkpoint(
    database, tmp_path, monkeypatch
):
    record = first(database)
    monkeypatch.setenv("BBS_CREATURE_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(
        images.sources,
        "science",
        lambda *a: (
            {"time_period": "Fixture interval"},
            [
                {
                    "id": "fixture",
                    "title": "Fixture",
                    "url": "https://paleobiodb.org/test",
                    "supports": ["time_period"],
                }
            ],
            [],
        ),
    )
    monkeypatch.setattr(
        images, "discover", lambda client, record, *a: ([chosen(record)], [])
    )
    client = FixtureClient()
    run = lambda **kwargs: images.execute(
        database,
        tmp_path / "state",
        pilot=1,
        client=client,
        progress=lambda *a, **k: None,
        **kwargs,
    )
    assert run()["images_installed"] == 1
    guidance = {
        "status": "unverified",
        "phonetic": "fixture-PHON",
        "stress": "PHON",
        "tts_text": "fixture phon",
        "source_url": "https://example.org/reference",
    }
    report = run(
        pronunciation_references={record["scientific_name"].casefold(): guidance}
    )
    assert report["pronunciations_updated"] == 1
    assert report["images_retained"] == 1 and client.requests == 1
    assert first(database)["pronunciation"]["phonetic"] == "fixture-PHON"


def test_missing_canonical_file_is_reported_as_placeholder(database):
    record = first(database)
    record["image"].update(
        placeholder=False, path="/static/creatures/missing-fixture.webp"
    )
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE creature_profiles SET record_json=? WHERE creature_id=?",
            (json.dumps(record), record["id"]),
        )
    assert images.coverage(database)["images_retained"] == 0


def test_ten_creature_pilot_resumes_after_fifth_install(tmp_path, monkeypatch):
    pytest.importorskip("PIL.Image")
    db = tmp_path / "pilot.sqlite3"
    monkeypatch.setattr(main, "DB", db)
    monkeypatch.setattr(main, "CATALOG", True)
    monkeypatch.setattr(main, "SAMPLE", False)
    monkeypatch.setenv("BBS_CREATURE_IMAGE_DIR", str(tmp_path / "images"))
    main.initialize_database()
    monkeypatch.setattr(images.sources, "science", lambda *a: ({}, [], []))
    monkeypatch.setattr(
        images, "discover", lambda client, record, *a: ([chosen(record)], [])
    )
    client = FixtureClient()

    def interrupt(message, **kwargs):
        if message.startswith("[6/10]"):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        images.execute(
            db, tmp_path / "state", pilot=10, client=client, progress=interrupt
        )
    assert images.coverage(db)["internet_images"] == 5
    report = images.execute(
        db, tmp_path / "state", pilot=10, client=client, progress=lambda *a, **k: None
    )
    assert report["images_installed"] == 5 and report["images_retained"] == 5
    assert report["coverage"]["internet_images"] == 10
    assert report["coverage"]["total"] == 164 and client.requests == 10
    assert (
        images.execute(
            db,
            tmp_path / "state",
            pilot=10,
            client=client,
            progress=lambda *a, **k: None,
        )["images_installed"]
        == 0
    )
    assert client.requests == 10


def test_new_commons_queries_retain_maxlag_and_api_error_handling(tmp_path):
    from app.importer.api_policy import metadata_request

    query = {
        "action": "query",
        "generator": "search",
        "gsrsearch": '"Tyrannosaurus"',
        "gsrnamespace": 6,
        "gsrlimit": 50,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "format": "json",
        "gsroffset": 50,
        "continue": "gsroffset||",
    }
    assert metadata_request(str(httpx.URL(images.sources.COMMONS, params=query)))
    category = {
        **query,
        "generator": "categorymembers",
        "gcmtitle": "Category:Tyrannosaurus",
        "gcmnamespace": 6,
        "gcmtype": "file",
        "gcmlimit": 50,
        "gcmcontinue": "file|Fixture",
    }
    assert metadata_request(str(httpx.URL(images.sources.COMMONS, params=category)))
    assert not metadata_request(
        str(httpx.URL(images.sources.COMMONS, params={**query, "gsrlimit": 5000}))
    )
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        assert request.url.params["maxlag"] == "5"
        return httpx.Response(
            200,
            json={"error": {"code": "maxlag"}}
            if len(calls) == 1
            else {"query": {"pages": {}}},
        )

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    try:
        assert client.json(images.sources.COMMONS, query) == {"query": {"pages": {}}}
        assert len(calls) == 2 and 5 in sleeps
    finally:
        client.close()


def test_manually_identified_working_canonical_art_is_not_downgraded(
    database, tmp_path, monkeypatch
):
    from app import library

    record = first(database)
    monkeypatch.setattr(library, "ROOT", tmp_path)
    existing = tmp_path / "static/creatures/fixture.webp"
    existing.parent.mkdir(parents=True)
    webp, _ = images.convert(pixels())
    existing.write_bytes(webp)
    record["image"].update(
        placeholder=False,
        path="/static/creatures/fixture.webp",
        approval_method="manual",
        verified_by="Fixture inspector",
    )
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE creature_profiles SET record_json=? WHERE creature_id=?",
            (json.dumps(record), record["id"]),
        )
    assert not images.install(
        database, record, chosen(record), pixels("red"), tmp_path / "new-images"
    )
    assert existing.read_bytes() == webp
    with images.connect(database) as conn:
        assert not conn.execute("SELECT * FROM internet_creature_images").fetchall()
