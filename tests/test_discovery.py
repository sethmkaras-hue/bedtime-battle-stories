"""Offline discovery evidence; fixtures are synthetic and never catalog claims."""

import copy
import json
import sqlite3
import httpx
import pytest
from app import main, library
from app.importer import sources
from app.importer.network import PoliteClient, SourceUnavailable
from app.importer.pronunciation_files import load_references
from app.importer.runner import collect, execute
from app.importer.store import Store
from app.importer.review import approve
from test_importer import database, FakeClient
from test_library import FakeProvider
from app.audio.service import AudioService
from scripts.generate_pronunciations import generate


def info(description="Life reconstruction of Tyrannosaurus rex"):
    return {
        "url": "https://upload.wikimedia.org/fixture.png",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture",
        "extmetadata": {
            "ImageDescription": {"value": description},
            "Artist": {"value": "Fixture creator"},
            "LicenseShortName": {"value": "CC BY-SA 4.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
        },
    }


def commons_client(tmp_path, denied_wikidata=False, empty=False):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "www.wikidata.org":
            assert denied_wikidata
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        assert request.url.host == "commons.wikimedia.org"
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert request.url.params["action"] == "query"
        assert request.url.params["gsrsearch"] == '"Tyrannosaurus rex"'
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {}
                    if empty
                    else {
                        "1": {
                            "pageid": 1,
                            "title": "File:Uninformative name",
                            "imageinfo": [info()],
                        }
                    }
                }
            },
        )

    return PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda n: None
    ), calls


@pytest.mark.parametrize("optional", [False, True])
def test_commons_search_does_not_require_wikidata(tmp_path, optional, monkeypatch):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    client, calls = commons_client(tmp_path, denied_wikidata=optional)
    try:
        result = sources.images(
            client,
            {"scientific_name": "Tyrannosaurus rex", "category": "dinosaur"},
            use_wikidata=optional,
        )
        assert len(result) == 1 and result[0]["supported"]
        assert (
            result[0]["review_status"] == "pending"
            and result[0]["taxon_entity"] is None
        )
        assert (
            calls[0].url.host == "commons.wikimedia.org"
        )  # search precedes optional lookup
        if not optional:
            assert all(r.url.host != "www.wikidata.org" for r in calls)
        else:
            assert result[0]["identity_notes"]
    finally:
        client.close()


@pytest.mark.parametrize(
    "description",
    [
        "Life reconstruction of Triceratops horridus",
        "Triceratops horridus compared with Tyrannosaurus rex",
        "Life reconstruction of Tyrannosaurus rex and Triceratops horridus",
        "Possibly Tyrannosaurus rex reconstruction",
        "Tyrannosaurus rex fossil skull",
        "An unrelated animal",
    ],
)
def test_unrelated_and_ambiguous_subjects_are_not_downloadable(description):
    candidate = sources.image_candidate(
        info(description),
        {"title": "File:Tyrannosaurus rex.jpg"},
        set(),
        None,
        "Tyrannosaurus rex",
        False,
    )
    assert not candidate["supported"] and candidate["review_status"] == "pending"


def test_living_sharks_require_photographs_and_exact_species():
    def check(description):
        return sources.image_candidate(
            info(description), {}, set(), None, "Carcharodon carcharias", True
        )["supported"]

    assert check("Photograph of Carcharodon carcharias underwater")
    assert not check("Life reconstruction of Carcharodon carcharias")
    assert not check("Photograph of Carcharhinus leucas")


@pytest.mark.parametrize(
    "label,url",
    [
        ("All rights reserved", "https://creativecommons.org/licenses/by-sa/4.0/"),
        ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by/4.0/"),
        ("CC BY-SA 4.0", "https://creativecommons.org.evil.test/licenses/by-sa/4.0/"),
    ],
)
def test_license_declaration_must_match(label, url):
    data = info()
    data["extmetadata"]["LicenseShortName"]["value"] = label
    data["extmetadata"]["LicenseUrl"]["value"] = url
    assert not sources.image_candidate(
        data, {}, set(), None, "Tyrannosaurus rex", False
    )["supported"]


def test_empty_commons_preserves_image_fallback(tmp_path, monkeypatch):
    client, calls = commons_client(tmp_path, empty=True)
    monkeypatch.setattr(sources, "science", lambda *a: ({}, [], []))
    record = {
        "id": 1,
        "stable_key": "fixture",
        "display_name": "Tyrannosaurus",
        "scientific_name": "Tyrannosaurus rex",
        "category": "dinosaur",
        "image": {"placeholder": True},
    }
    before = copy.deepcopy(record)
    try:
        proposal = collect(client, record, tmp_path)
    finally:
        client.close()
    assert proposal["images"] == [] and record == before
    assert any("No Commons image candidates" in issue for issue in proposal["issues"])


def manifest(tmp_path, name="Tyrannosaurus rex", **updates):
    entry = {
        "scientific_name": name,
        "source_url": "https://www.nhm.ac.uk/fixture-reference",
        "publisher": "Synthetic educational fixture",
        "retrieved_on": "2026-11-01",
        "phonetic": "tie-RAN-oh-sore-us",
        "stress": "RAN",
        "tts_text": "tie ran oh sore us",
        "alternatives": ["Fixture alternate"],
        "status": "verified",
        "verified_by": "Fixture researcher",
        "checked_on": "2026-11-01",
    }
    entry.update(updates)
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": [entry]}))
    return path


def test_supplied_guidance_retains_evidence_without_automatic_verification(tmp_path):
    refs = load_references(manifest(tmp_path))
    pron = refs["tyrannosaurus rex"]
    assert pron["status"] == "unverified" and pron["source_url"].endswith(
        "fixture-reference"
    )
    assert pron["source_verification"] == {
        "status": "verified",
        "verified_by": "Fixture researcher",
        "checked_on": "2026-11-01",
    }
    assert pron["alternatives"] == ["Fixture alternate"]


def test_saved_html_is_parsed_locally_with_exact_heading(tmp_path):
    path = manifest(
        tmp_path,
        reference_file="source.html",
        phonetic=None,
        stress=None,
        tts_text=None,
    )
    html = tmp_path / "source.html"
    html.write_text("<h1>Tyrannosaurus rex</h1><p>Pronounced: tie-RAN-oh-sore-us</p>")
    pron = load_references(path)["tyrannosaurus rex"]
    assert pron["reference_sha256"] and pron["phonetic"] == "tie-RAN-oh-sore-us"
    html.write_text("<h1>Triceratops</h1><p>Pronounced: try-SAIR-ah-tops</p>")
    with pytest.raises(SourceUnavailable):
        load_references(path)


def test_pronunciation_cannot_leak_across_taxon_sections():
    html = "<h1>Tyrannosaurus</h1><p>No guide here.</p><h1>Triceratops</h1><p>Pronounced: try-SAIR-ah-tops</p>"
    with pytest.raises(SourceUnavailable):
        sources.parse_pronunciation(html, "Tyrannosaurus")
    assert sources.parse_pronunciation(html, "Triceratops")["stress"] == "SAIR"


@pytest.mark.parametrize(
    "updates",
    [
        {"phonetic": None},
        {"source_url": "file:///tmp/source"},
        {
            "reference_file": "../outside.html",
            "phonetic": None,
            "stress": None,
            "tts_text": None,
        },
        {"status": "verified", "verified_by": None},
    ],
)
def test_invalid_reference_is_refused(tmp_path, updates):
    with pytest.raises(ValueError):
        load_references(manifest(tmp_path, **updates))


def test_references_stage_without_museum_requests_and_invalidate_resume(
    database, tmp_path
):
    with sqlite3.connect(database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    refs = load_references(manifest(tmp_path, name=record["scientific_name"]))

    class NoMuseum(FakeClient):
        def get(self, url, *args, **kwargs):
            assert "nhm.ac.uk" not in url
            return super().get(url, *args, **kwargs)

    client = NoMuseum()
    folder = tmp_path / "imports"
    run = lambda **kwargs: execute(
        database,
        folder,
        pilot=1,
        client=client,
        progress=lambda *a, **k: None,
        **kwargs,
    )
    run()
    assert run()["resumed"] == 1
    assert run(pronunciation_references=refs)["processed"] == 1
    assert run(pronunciation_references=refs)["resumed"] == 1
    store = Store(folder)
    try:
        row = next(r for r in store.proposals() if r["proposal"]["pronunciation"])
        assert row["proposal"]["pronunciation"]["status"] == "unverified"
        with sqlite3.connect(database) as conn:
            before = json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )
            assert before["pronunciation"] == record["pronunciation"]
        provider = FakeProvider()
        service = AudioService(
            tmp_path / "audio", tmp_path / "models", {"kokoro": provider}
        )
        try:
            with sqlite3.connect(database) as conn:
                assert generate(conn, service, voice="test")["generated"] == 0
                assert provider.calls == 0
            approve(database, store, row["id"], ["pronunciation"])
            with sqlite3.connect(database) as conn:
                generated = generate(conn, service, voice="test")
                assert generated["generated"] == 1
                assert generate(conn, service, voice="test")["reused"] == 1
                assert provider.calls == 1
        finally:
            service.close()
        # A revised file is a new proposal, not an overwrite of approved guidance.
        revised = copy.deepcopy(refs)
        revised[library.normalize(record["scientific_name"])]["tts_text"] = (
            "different candidate text"
        )
        run(pronunciation_references=revised)
        with sqlite3.connect(database) as conn:
            current = json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )
        assert (
            current["id"] == record["id"]
            and current["pronunciation"]["tts_text"] != "different candidate text"
        )
        assert current["pronunciation"]["alternatives"] == ["Fixture alternate"]
    finally:
        store.close()


def test_duplicate_reference_identity_is_rejected(tmp_path):
    path = manifest(tmp_path)
    data = json.loads(path.read_text())
    data["entries"].append(
        dict(data["entries"][0], scientific_name="TYRANNOSAURUS REX")
    )
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Duplicate"):
        load_references(path)


def test_missing_original_attribution_is_not_downloadable():
    data = info()
    del data["descriptionurl"]
    assert not sources.image_candidate(
        data, {}, set(), None, "Tyrannosaurus rex", False
    )["supported"]
