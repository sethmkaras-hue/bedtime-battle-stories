"""Local sources and policy fixtures are synthetic, never real creature evidence."""

import csv
import json
import sqlite3
from pathlib import Path
import pytest
import httpx
from app import library
from app.importer.network import PoliteClient, SourceUnavailable
from app.importer.image_files import load_images
from app.importer.pronunciation_files import load_references
from app.importer.runner import execute
from app.importer.store import Store
from app.importer.review import approve
from test_importer import database


# From Wikimedia operations-mediawiki-config robots.txt at 38b99ce.
# The live Commons-specific additions must still be fetched at runtime.
WMF_RULES = "User-agent: *\nAllow: /w/api.php?action=mobileview&\nAllow: /w/load.php?\nDisallow: /w/\n"


def test_wikimedia_rule_logs_endpoint_method_status_rule_and_identity(
    tmp_path, monkeypatch
):
    ua = "BedtimeBattleStoriesImporter/1.0 (+https://example.test/contact)"
    monkeypatch.setenv("BBS_IMPORT_USER_AGENT", ua)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["user-agent"] == ua
        assert request.url.path == "/robots.txt"  # API must not be sent
        return httpx.Response(200, text=WMF_RULES)

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        with pytest.raises(SourceUnavailable, match="Disallow: /w/"):
            client.get(
                "https://commons.wikimedia.org/w/api.php",
                {"action": "query", "format": "json"},
            )
        event = client.events[-1]
        assert event["endpoint"].endswith("/w/api.php?action=query&format=json")
        assert event["method"] == "GET" and event["user_agent"] == ua
        assert event["http_status"] is None and event["request_sent"] is False
        assert event["robots_http_status"] == 200 and event["robots_group"] == "*"
        assert event["robots_rule"] == "Disallow: /w/" and len(calls) == 1
        assert (
            tmp_path / ("robots-" + event["robots_sha256"] + ".txt")
        ).read_text() == WMF_RULES
    finally:
        client.close()


def test_policy_uses_actual_ua_wildcards_and_most_specific_allow(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "BBS_IMPORT_USER_AGENT",
        "BedtimeBattleStoriesImporter/2.0 (+https://example.test)",
    )
    policy = "User-agent: *\nDisallow: /\n\nUser-agent: BedtimeBattleStoriesImporter\nDisallow: /w/*\nAllow: /w/api.php?action=query&*\n"
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(200, text=policy)
            if request.url.path == "/robots.txt"
            else httpx.Response(200, json={"ok": True})
        )

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        assert client.json(
            "https://commons.wikimedia.org/w/api.php",
            {"action": "query", "format": "json"},
        ) == {"ok": True}
        event = next(e for e in client.events if e["phase"] == "robots")
        assert (
            event["allowed"] and event["robots_group"] == "bedtimebattlestoriesimporter"
        )
        assert event["robots_rule"].startswith("Allow: /w/api.php")
        assert len(calls) == 2
    finally:
        client.close()


def test_http_rejection_is_distinct_from_robots_rejection(tmp_path):
    client = PoliteClient(
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 403)
        ),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(SourceUnavailable, match="HTTP 403"):
            client.get("https://commons.wikimedia.org/w/api.php")
        assert (
            client.events[-1]["http_status"] == 403
            and client.events[-1]["request_sent"]
        )
        assert next(e for e in client.events if e["phase"] == "robots")["allowed"]
    finally:
        client.close()


def test_unavailable_robots_fail_closed_and_preserve_http_status(tmp_path):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(403)

    client = PoliteClient(tmp_path, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(SourceUnavailable, match="policy unavailable"):
            client.get("https://commons.wikimedia.org/w/api.php")
        assert len(calls) == 1
        assert client.events[-1]["robots_http_status"] == 403
        assert client.events[-1]["http_status"] is None
    finally:
        client.close()


def test_cannot_disguise_importer_as_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("BBS_IMPORT_USER_AGENT", "Mozilla/5.0")
    with pytest.raises(ValueError, match="identification"):
        PoliteClient(tmp_path)


@pytest.fixture
def local_bundle(tmp_path, database):
    image = pytest.importorskip("PIL.Image")
    with sqlite3.connect(database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    name = record["scientific_name"]
    folder = tmp_path / "bundle"
    folder.mkdir()
    image.new("RGB", (800, 500), "navy").save(folder / "original.png")
    credit = {
        "title": "Synthetic source image",
        "identified_taxon": name,
        "source_url": "https://www.si.edu/object/fixture",
        "creator": "Synthetic fixture creator",
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "description": "Life reconstruction of " + name,
        "identity_evidence": "Synthetic exact-taxon caption, not real research",
        "identity_status": "supported",
    }
    (folder / "credit.json").write_text(json.dumps(credit))
    manifest = {
        "schema_version": 1,
        "entries": [
            {
                "scientific_name": name,
                "source_kind": "licensed_reference",
                "image_file": "original.png",
                "metadata_file": "credit.json",
                "retrieved_on": "2026-11-01",
            }
        ],
    }
    path = folder / "images.json"
    path.write_text(json.dumps(manifest))
    return path, credit, manifest, record


class NoNetwork:
    requests = 0
    cache_hits = 0

    def get(self, *a, **k):
        raise AssertionError("Offline imports must not contact sources")

    def json(self, *a, **k):
        raise AssertionError("Offline imports must not contact sources")


def test_alternative_image_stages_offline_then_publishes_only_after_review(
    local_bundle, database, tmp_path, monkeypatch
):
    path, credit, manifest, record = local_bundle
    refs = load_images(path)
    folder = tmp_path / "imports"
    result = execute(
        database,
        folder,
        pilot=1,
        offline=True,
        image_references=refs,
        client=NoNetwork(),
        progress=lambda *a, **k: None,
    )
    assert result["http_requests"] == 0
    store = Store(folder)
    try:
        proposal = store.proposals()[0]
        image = proposal["proposal"]["images"][0]
        assert image["supported"] and image["review_status"] == "pending"
        assert image["creator"] == credit["creator"] and image["license"] == "CC0-1.0"
        assert (folder / image["preview_file"]).is_file()
        with sqlite3.connect(database) as conn:
            current = json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )
        assert current["image"] == record["image"]
        monkeypatch.setattr(library, "ROOT", tmp_path / "published")
        approve(database, store, proposal["id"], ["image"])
        with sqlite3.connect(database) as conn:
            approved = json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )
        assert approved["id"] == record["id"] and not approved["image"]["placeholder"]
        assert approved["image"]["creator"] == credit["creator"]
        assert approved["image"]["license"] == credit["license"]
        assert approved["image"]["original_source_url"] == credit["source_url"]
        assert library.local_asset(approved["image"]["path"]).is_file()
        resumed = execute(
            database,
            folder,
            pilot=1,
            offline=True,
            image_references=refs,
            client=NoNetwork(),
            progress=lambda *a, **k: None,
        )
        with sqlite3.connect(database) as conn:
            preserved = json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )
        assert preserved["image"] == approved["image"]
    finally:
        store.close()


def test_manual_commons_metadata_and_original_are_imported_without_api(
    local_bundle, database, tmp_path
):
    path, credit, manifest, record = local_bundle
    data = {
        "query": {
            "pages": {
                "12": {
                    "pageid": 12,
                    "title": "File:Fixture",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/fixture.png",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture",
                            "extmetadata": {
                                k: {"value": v}
                                for k, v in {
                                    "Artist": credit["creator"],
                                    "LicenseShortName": "CC0",
                                    "LicenseUrl": credit["license_url"],
                                    "ImageDescription": credit["description"],
                                }.items()
                            },
                        }
                    ],
                }
            }
        }
    }
    (path.parent / "credit.json").write_text(json.dumps(data))
    manifest["entries"][0]["source_kind"] = "commons"
    path.write_text(json.dumps(manifest))
    result = execute(
        database,
        tmp_path / "imports",
        pilot=1,
        offline=True,
        image_references=load_images(path),
        client=NoNetwork(),
        progress=lambda *a, **k: None,
    )
    assert result["proposals"][0]["supported_images"] == 1
    assert result["http_requests"] == 0
    repeat = execute(
        database,
        tmp_path / "imports",
        pilot=1,
        offline=True,
        image_references=load_images(path),
        client=NoNetwork(),
        progress=lambda *a, **k: None,
    )
    assert repeat["resumed"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"identified_taxon": "Unrelated species"},
        {"identity_status": "uncertain"},
        {"description": "Photograph of unrelated species"},
        {"license_url": "https://creativecommons.org/licenses/by/4.0/"},
    ],
)
def test_uncertain_or_mismatched_manual_images_stay_in_review(
    local_bundle, database, tmp_path, change
):
    path, credit, manifest, record = local_bundle
    credit.update(change)
    (path.parent / "credit.json").write_text(json.dumps(credit))
    result = execute(
        database,
        tmp_path / "imports",
        pilot=1,
        offline=True,
        image_references=load_images(path),
        client=NoNetwork(),
        progress=lambda *a, **k: None,
    )
    assert (
        result["proposals"][0]["images"] == 1
        and result["proposals"][0]["supported_images"] == 0
    )
    store = Store(tmp_path / "imports")
    try:
        image = store.proposals()[0]["proposal"]["images"][0]
        assert (
            image["review_status"] == "pending"
            and image["issues"]
            and "original_file" not in image
        )
        with pytest.raises(ValueError, match="lacks supported"):
            approve(database, store, store.proposals()[0]["id"], ["image"])
    finally:
        store.close()


def test_manual_image_dry_run_has_no_work_directory_writes(
    local_bundle, database, tmp_path
):
    path, *_ = local_bundle
    work = tmp_path / "dry"
    before = database.read_bytes()
    execute(
        database,
        work,
        pilot=1,
        dry_run=True,
        offline=True,
        image_references=load_images(path),
        client=NoNetwork(),
        progress=lambda *a, **k: None,
    )
    assert not work.exists() and database.read_bytes() == before


def test_local_image_paths_and_restrictive_licenses_are_rejected(local_bundle):
    path, credit, manifest, _ = local_bundle
    manifest["entries"][0]["image_file"] = "../outside.png"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="within"):
        load_images(path)
    manifest["entries"][0]["image_file"] = "original.png"
    path.write_text(json.dumps(manifest))
    credit["license"] = "All rights reserved"
    (path.parent / "credit.json").write_text(json.dumps(credit))
    with pytest.raises(ValueError):
        load_images(path)


def csv_file(tmp_path, **updates):
    row = {
        "scientific_name": "Tyrannosaurus rex",
        "source_url": "https://www.nhm.ac.uk/fixture",
        "publisher": "Synthetic reference",
        "retrieved_on": "2026-11-01",
        "phonetic": "tie-RAN-oh-sore-us",
        "stress": "RAN",
        "tts_text": "tie ran oh sore us",
        "status": "verified",
        "verified_by": "Fixture researcher",
        "checked_on": "2026-11-01",
        "alternatives": "Fixture A;Fixture B",
    }
    row.update(updates)
    path = tmp_path / "references.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    return path


def test_csv_preserves_source_review_phonetic_stress_and_alternatives(tmp_path):
    reference = load_references(csv_file(tmp_path))["tyrannosaurus rex"]
    assert (
        reference["phonetic"] == "tie-RAN-oh-sore-us" and reference["stress"] == "RAN"
    )
    assert reference["source_url"] == "https://www.nhm.ac.uk/fixture"
    assert reference["source_verification"]["status"] == "verified"
    assert reference["status"] == "unverified"  # Explicit adult approval still required
    assert reference["alternatives"] == ["Fixture A", "Fixture B"]


@pytest.mark.parametrize(
    "changes",
    [{"stress": ""}, {"source_url": "file:///tmp/guide"}, {"verified_by": ""}],
)
def test_csv_rejects_unsourced_or_incomplete_guidance(tmp_path, changes):
    with pytest.raises(ValueError):
        load_references(csv_file(tmp_path, **changes))


def test_csv_duplicate_columns_are_refused(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("scientific_name,scientific_name\na,b\n")
    with pytest.raises(ValueError, match="unique"):
        load_references(path)
