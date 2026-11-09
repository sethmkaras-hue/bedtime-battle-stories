"""Scientific/media fixtures are deliberately synthetic, not canonical evidence."""

from pathlib import Path
import json
import sqlite3
import httpx
import pytest
from app import main, library
from app.importer import sources
from app.importer.network import PoliteClient, SourceUnavailable
from app.importer.runner import execute, collect, apply_supported, digest
from app.importer.store import Store, backup


def taxon(name="Tyrannosaurus"):
    return {
        "records": [
            {
                "taxon_name": name,
                "accepted_name": name,
                "taxon_rank": "genus",
                "orig_no": "txn:1",
                "parent_name": "Tyrannosauridae",
                "early_interval": "Late Cretaceous",
                "late_interval": "Late Cretaceous",
            }
        ]
    }


def html(name="Tyrannosaurus"):
    return f"<html><h1>{name}</h1><dl><dt>Diet:</dt><dd>carnivorous</dd><dt>Length:</dt><dd>10-12 m</dd><dt>When it lived:</dt><dd>Late Cretaceous</dd><dt>Found in:</dt><dd>Example fossil locality</dd><dt>Pronunciation:</dt><dd>tie-RAN-oh-sore-us</dd></dl></html>"


def test_exact_taxonomy_not_synonym_or_fuzzy():
    assert (
        sources.pbdb_match(taxon(), "Tyrannosaurus")[0]["time_period"]
        == "Late Cretaceous"
    )
    bad = taxon()
    bad["records"][0]["accepted_name"] = "Another genus"
    with pytest.raises(SourceUnavailable):
        sources.pbdb_match(bad, "Tyrannosaurus")
    with pytest.raises(SourceUnavailable):
        sources.pbdb_match(taxon(), "Triceratops")
    with pytest.raises(SourceUnavailable):
        sources.gbif_match(
            {"matchType": "FUZZY", "canonicalName": "Fixture"}, "Fixture"
        )
    assert (
        sources.gbif_match(
            {
                "matchType": "EXACT",
                "status": "ACCEPTED",
                "rank": "SPECIES",
                "canonicalName": "Fixture testensis",
                "kingdom": "Animalia",
                "confidence": 100,
            },
            "Fixture testensis",
        )[0]["taxon_rank"]
        == "species"
    )


def test_museum_fields_and_pronunciation_are_literal_not_invented():
    facts = sources.parse_nhm_facts(html(), "Tyrannosaurus")
    assert facts["diet"] == "meat" and facts["length"]["minimum"] == 10
    assert "weight" not in facts and "offensive_adaptations" not in facts
    pron = sources.parse_pronunciation(html(), "Tyrannosaurus")
    assert pron["phonetic"] == "tie-RAN-oh-sore-us" and pron["stress"] == "RAN"
    with pytest.raises(SourceUnavailable):
        sources.parse_pronunciation(html(), "Triceratops")
    with pytest.raises(SourceUnavailable):
        sources.parse_pronunciation(
            "<h1>Tyrannosaurus</h1><p>Pronunciation not provided.</p>", "Tyrannosaurus"
        )


def test_image_requires_depicts_identity_license_and_medium():
    page = {"pageid": 1, "title": "File:Not proof of species.jpg"}
    info = {
        "url": "https://upload.wikimedia.org/test.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Test",
        "extmetadata": {
            "LicenseShortName": {"value": "CC BY-SA 4.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
            "Artist": {"value": '<a href="https://example.test">Fixture artist</a>'},
            "ImageDescription": {"value": "Life reconstruction of Tyrannosaurus."},
        },
    }
    candidate = sources.image_candidate(
        info, page, {"Q1"}, "Q1", "Tyrannosaurus", False
    )
    assert candidate["supported"] and candidate["creator"] == "Fixture artist"
    assert candidate["license"] == "CC-BY-SA-4.0"
    assert not sources.image_candidate(
        info, page, {"Q2"}, "Q1", "Tyrannosaurus", False
    )["supported"]
    info["extmetadata"]["LicenseShortName"]["value"] = "All rights reserved"
    assert not sources.image_candidate(
        info, page, {"Q1"}, "Q1", "Tyrannosaurus", False
    )["supported"]
    info["extmetadata"]["LicenseShortName"]["value"] = "CC BY-SA 4.0"
    info["extmetadata"]["ImageDescription"]["value"] = (
        "Tyrannosaurus fossil skull reconstruction"
    )
    assert not sources.image_candidate(
        info, page, {"Q1"}, "Q1", "Tyrannosaurus", False
    )["supported"]


def test_robots_denial_and_unapproved_redirect_are_not_bypassed(tmp_path):
    calls = []

    def denied(r):
        calls.append(str(r.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    client = PoliteClient(
        tmp_path / "cache", transport=httpx.MockTransport(denied), sleep=lambda n: None
    )
    with pytest.raises(SourceUnavailable):
        client.get("https://www.nhm.ac.uk/discover/test")
    assert len(calls) == 1 and calls[0].endswith("robots.txt")
    client.close()

    def redirect(r):
        return (
            httpx.Response(404)
            if r.url.path == "/robots.txt"
            else httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        )

    client = PoliteClient(
        tmp_path / "other",
        transport=httpx.MockTransport(redirect),
        sleep=lambda n: None,
    )
    with pytest.raises(SourceUnavailable):
        client.get("https://www.nhm.ac.uk/discover/test")
    client.close()


def test_http_cache_conditional_refresh_and_retry(tmp_path):
    calls = []
    attempts = {"n": 0}
    sleeps = []

    def handler(r):
        calls.append(r)
        if r.url.path == "/robots.txt":
            return httpx.Response(404)
        if r.headers.get("if-none-match") == "fixture":
            return httpx.Response(304)
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text="cached response", headers={"ETag": "fixture"})

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    assert client.get("https://paleobiodb.org/test").text == "cached response"
    before = len(calls)
    assert (
        client.get("https://paleobiodb.org/test").text == "cached response"
        and len(calls) == before
    )
    client.refresh = True
    assert client.get("https://paleobiodb.org/test").text == "cached response"
    assert calls[-1].headers["if-none-match"] == "fixture" and 2 in sleeps
    client.close()


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "app.sqlite3")
    monkeypatch.setattr(main, "SAMPLE", True)
    monkeypatch.setattr(main, "CATALOG", False)
    main.initialize_database()
    return main.DB


class FakeClient:
    requests = 0
    cache_hits = 0

    def get(self, url, params=None, **kw):
        self.requests += 1
        if "paleobiodb" in url:
            data = taxon(params["name"])
            data["records"][0]["taxon_rank"] = (
                "species" if " " in params["name"] else "genus"
            )
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
        if "nhm.ac.uk" in url:
            name = Path(url).stem.capitalize()
            return httpx.Response(
                200, text=html(name), request=httpx.Request("GET", url)
            )
        raise SourceUnavailable("Synthetic source is unavailable")

    def json(self, *a, **k):
        raise SourceUnavailable("Synthetic image source is unavailable")


def test_pilot_resume_dry_run_and_supported_metadata(database, tmp_path):
    client = FakeClient()
    folder = tmp_path / "imports"
    report = execute(
        database, folder, pilot=4, client=client, progress=lambda *a, **kw: None
    )
    assert report["processed"] == 4 and report["source_supported_applied"] == 4
    first = client.requests
    resumed = execute(
        database, folder, pilot=4, client=client, progress=lambda *a, **kw: None
    )
    assert resumed["resumed"] == 4 and client.requests == first
    with sqlite3.connect(database) as conn:
        r = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
        assert (
            r["verification_status"] == "unverified"
            and r["import_stage"] == "source_supported"
        )
        assert conn.execute("SELECT count(*) FROM creatures").fetchone()[0] == 24
    before = Path(database).read_bytes()
    dry = execute(
        database,
        tmp_path / "dry",
        pilot=2,
        dry_run=True,
        client=client,
        progress=lambda *a, **kw: None,
    )
    assert (
        dry["processed"] == 2
        and not (tmp_path / "dry").exists()
        and Path(database).read_bytes() == before
    )


def test_interruption_after_staging_resumes_application(database, tmp_path):
    with sqlite3.connect(database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    folder = tmp_path / "import"
    store = Store(folder)
    payload = {
        "science": {"time_period": "Source fixture period"},
        "evidence": [
            {
                "id": "fixture",
                "title": "Synthetic evidence",
                "url": "https://paleobiodb.org/test",
                "supports": ["time_period"],
            }
        ],
        "record": record,
        "images": [],
        "pronunciation": None,
        "issues": [],
        "stable_key": record["stable_key"],
    }
    store.stage(record["stable_key"], digest(record), payload)
    store.close()
    report = execute(
        database, folder, pilot=1, client=FakeClient(), progress=lambda *a, **kw: None
    )
    assert report["resumed"] == 1 and report["source_supported_applied"] == 1
    with sqlite3.connect(database) as conn:
        assert (
            json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )["time_period"]
            == "Source fixture period"
        )


def test_reviewed_fields_and_citations_survive_automatic_refresh(database):
    with sqlite3.connect(database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
        record["time_period"] = "Parent reviewed period"
        record["reviewed_fields"] = {
            "time_period": {"reviewer": "parent", "checked_on": "2026-01-01"}
        }
        library.import_records(conn, [record])
    proposal = {
        "science": {"time_period": "Different automated period"},
        "evidence": [
            {
                "id": "api",
                "title": "Synthetic data",
                "url": "https://paleobiodb.org/test",
                "supports": ["time_period"],
            }
        ],
    }
    apply_supported(database, record, proposal)
    with sqlite3.connect(database) as conn:
        updated = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    assert updated["time_period"] == "Parent reviewed period"


def test_proposal_dedup_and_backup(database, tmp_path):
    store = Store(tmp_path / "state")
    payload = {
        "record": {"ignored": "snapshot"},
        "evidence": [{"retrieved_on": "2026-01-01"}],
        "science": {"time_period": "Fixture"},
    }
    a = store.stage("test:taxon", "a", payload)
    payload["evidence"][0]["retrieved_on"] = "2026-01-02"
    payload["record"] = {"ignored": "changed snapshot"}
    b = store.stage("test:taxon", "b", payload)
    assert a == b
    saved = backup(database)
    assert saved.is_file()
    with sqlite3.connect(saved) as conn:
        assert conn.execute("SELECT count(*) FROM creatures").fetchone()[0] == 24
    store.close()


def test_image_acquisition_is_cached_and_staged_not_canonical(database, tmp_path):
    import io

    PIL = pytest.importorskip("PIL.Image")
    image = io.BytesIO()
    PIL.new("RGB", (640, 400), "navy").save(image, format="PNG")
    with sqlite3.connect(database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    name = record["scientific_name"]
    calls = []

    def handler(request):
        calls.append(str(request.url))
        q = request.url.params
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "paleobiodb.org":
            data = taxon(name)
            data["records"][0]["taxon_rank"] = "species"
            return httpx.Response(200, json=data)
        if request.url.host == "www.nhm.ac.uk":
            return httpx.Response(200, text=html(record["display_name"]))
        if request.url.host == "www.wikidata.org":
            if q["action"] == "wbsearchentities":
                return httpx.Response(200, json={"search": [{"id": "Q1"}]})
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q1": {
                            "claims": {
                                "P225": [{"mainsnak": {"datavalue": {"value": name}}}],
                                "P105": [
                                    {
                                        "mainsnak": {
                                            "datavalue": {"value": {"id": "Q7432"}}
                                        }
                                    }
                                ],
                            }
                        }
                    }
                },
            )
        if request.url.host == "commons.wikimedia.org":
            if q["action"] == "wbgetentities":
                return httpx.Response(
                    200,
                    json={
                        "entities": {
                            "M1": {
                                "statements": {
                                    "P180": [
                                        {
                                            "mainsnak": {
                                                "datavalue": {"value": {"id": "Q1"}}
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "1": {
                                "pageid": 1,
                                "title": "File:Synthetic fixture",
                                "imageinfo": [
                                    {
                                        "url": "https://upload.wikimedia.org/fixture.png",
                                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture",
                                        "extmetadata": {
                                            "LicenseShortName": {"value": "CC0"},
                                            "LicenseUrl": {
                                                "value": "https://creativecommons.org/publicdomain/zero/1.0/"
                                            },
                                            "Artist": {
                                                "value": "Synthetic fixture artist"
                                            },
                                            "ImageDescription": {
                                                "value": "Life reconstruction of "
                                                + name
                                            },
                                        },
                                    }
                                ],
                            }
                        }
                    }
                },
            )
        if request.url.host == "upload.wikimedia.org":
            return httpx.Response(
                200, content=image.getvalue(), headers={"Content-Type": "image/png"}
            )
        raise AssertionError("Unexpected test request")

    client = PoliteClient(
        tmp_path / "http", transport=httpx.MockTransport(handler), sleep=lambda n: None
    )
    a = collect(client, record, tmp_path / "staging", museum_pages=True)
    assert (
        a["science"]["length"]["minimum"] == 10
        and a["pronunciation"]["stress"] == "RAN"
    )
    assert (
        a["images"][0]["supported"]
        and (tmp_path / "staging" / a["images"][0]["preview_file"]).is_file()
    )
    assert not any("wikidata.org" in url for url in calls)
    before = len(calls)
    collect(client, record, tmp_path / "staging", museum_pages=True)
    assert len(calls) == before  # All response and original-image bytes reused.
    with sqlite3.connect(database) as conn:
        canonical = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
        assert (
            canonical["image"]["placeholder"]
            and canonical["pronunciation"]["status"] == "unverified"
        )
    client.close()


def test_staged_file_lookup_cannot_expose_auth_or_other_server_files(tmp_path):
    from app.importer.review import safe_file

    (tmp_path / "parent-auth.json").write_text("fixture hash")
    for path in [
        "parent-auth.json",
        "../secret",
        "/etc/passwd",
        "previews/../../parent-auth.json",
    ]:
        with pytest.raises(ValueError):
            safe_file(tmp_path, path)
