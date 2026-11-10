"""Commons metadata handling with explicit robots opt-out; synthetic responses."""

from email.utils import formatdate
import hashlib
import io
import json
import sqlite3
from pathlib import Path
import httpx
import pytest
from app.importer.api_policy import COMMONS_API, metadata_request
from app.importer.network import PoliteClient, SourceUnavailable
from app.importer.runner import collect
from test_importer import database


@pytest.fixture(autouse=True)
def explicit_robots_opt_out(monkeypatch):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")


PARAMS = {
    "action": "query",
    "generator": "search",
    "gsrsearch": "Tyrannosaurus rex",
    "gsrnamespace": "6",
    "gsrlimit": "5",
    "prop": "imageinfo",
    "iiprop": "url|extmetadata",
    "format": "json",
}


def api_url(params=None):
    return str(httpx.URL(COMMONS_API, params=params or PARAMS))


def test_explicit_opt_out_allows_metadata_when_crawler_paths_are_blocked(
    tmp_path,
):
    calls = []

    def handler(request):
        calls.append(request)
        # The explicitly disabled robots policy must not fetch robots.txt.
        assert request.url.path == "/w/api.php"
        assert request.method == "GET" and request.url.params["maxlag"] == "5"
        assert request.headers["user-agent"].startswith("BedtimeBattleStoriesImporter/")
        return httpx.Response(200, json={"query": {"pages": {}}})

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        client.robots["commons.wikimedia.org"] = (
            "A crawler policy cannot authorize or deny this scoped API request"
        )
        assert client.json(COMMONS_API, PARAMS) == {"query": {"pages": {}}}
        assert len(calls) == 1
        event = next(
            event for event in client.events if event["phase"] == "robots_disabled"
        )
        assert (
            event["allowed"]
            and not event["robots_applied"]
            and event["configuration"] == "IMPORT_RESPECT_ROBOTS=false"
        )
        assert client.events[-1]["http_status"] == 200
    finally:
        client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://commons.wikimedia.org/wiki/File:Creature.jpg",
        "https://commons.wikimedia.org/w/index.php?action=query&format=json",
        "https://commons.wikimedia.org/w/api.php/?action=query&format=json",
        "https://commons.wikimedia.org/w/%61pi.php?action=query&format=json",
        "https://www.wikidata.org/w/api.php?action=query&format=json",
        "http://commons.wikimedia.org/w/api.php?action=query&format=json",
        "https://commons.wikimedia.org:444/w/api.php?action=query&format=json",
        "https://commons.wikimedia.org.evil.test/w/api.php?action=query&format=json",
        "https://commons.wikimedia.org/w/api.php?action=edit&format=json",
        "https://commons.wikimedia.org/w/api.php?action=parse&format=json",
        "https://commons.wikimedia.org/w/api.php?action=query&action=edit&format=json",
        "https://commons.wikimedia.org/w/api.php?action=query&prop=revisions&format=json",
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&token=secret",
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&maxlag=60",
        "https://commons.wikimedia.org/w/api.php?action=query&format=xml",
    ],
)
def test_api_metadata_classifier_does_not_expand_to_other_urls_or_actions(url):
    assert not metadata_request(url)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://commons.wikimedia.org/wiki/File:Creature.jpg",
        "https://commons.wikimedia.org/w/index.php",
        "https://www.wikidata.org/w/api.php?action=query&format=json",
        "https://www.nhm.ac.uk/discover/creature.html",
        "https://commons.wikimedia.org/w/api.php?action=edit&format=json",
    ],
)
def test_other_requests_still_obey_robots(tmp_path, endpoint, monkeypatch):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "true")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        with pytest.raises(SourceUnavailable, match="robots.txt disallows"):
            client.get(endpoint)
        assert len(calls) == 1 and not any(
            e["phase"] == "api_policy" for e in client.events
        )
    finally:
        client.close()


def test_redirect_from_api_to_webpage_cannot_inherit_api_exception(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "true")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/w/api.php":
            return httpx.Response(302, headers={"Location": "/wiki/Blocked"})
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, text="User-agent: *\nDisallow: /wiki/\n")

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        with pytest.raises(SourceUnavailable, match="robots.txt disallows"):
            client.get(COMMONS_API, PARAMS)
        assert [r.url.path for r in calls] == ["/robots.txt", "/w/api.php"]
    finally:
        client.close()


@pytest.mark.parametrize("response", ["maxlag", "ratelimited", 429, 503])
def test_api_backoff_then_success_does_not_cache_errors(tmp_path, response):
    requests = []
    sleeps = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                response if isinstance(response, int) else 200,
                json={"error": {"code": response}},
                headers={"Retry-After": "7"},
            )
        return httpx.Response(200, json={"query": {"pages": {}}})

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    try:
        assert client.json(COMMONS_API, PARAMS) == {"query": {"pages": {}}}
        assert len(requests) == 2 and 7 in sleeps
        assert (
            client.json(COMMONS_API, PARAMS) == {"query": {"pages": {}}}
            and len(requests) == 2
        )
        assert all(
            "error" not in json.loads(p.read_text()) for p in tmp_path.glob("*.body")
        )
    finally:
        client.close()


def test_persistent_maxlag_is_bounded_and_not_cached(tmp_path):
    calls = []
    sleeps = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json={"error": {"code": "maxlag"}})

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    try:
        with pytest.raises(SourceUnavailable, match="API maxlag"):
            client.json(COMMONS_API, PARAMS)
        assert len(calls) == 3 and 5 in sleeps and 10 in sleeps
        assert not list(tmp_path.glob("*.body"))
    finally:
        client.close()


@pytest.mark.parametrize("retry", ["120", formatdate(1_000_120, usegmt=True)])
def test_long_retry_after_defers_instead_of_retrying_early(tmp_path, retry):
    calls = []
    client = PoliteClient(
        tmp_path,
        clock=lambda: 1_000_000,
        sleep=lambda _: None,
        transport=httpx.MockTransport(
            lambda r: calls.append(r)
            or httpx.Response(429, headers={"Retry-After": retry})
        ),
    )
    try:
        with pytest.raises(SourceUnavailable, match="resume later"):
            client.json(COMMONS_API, PARAMS)
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("response", [401, 403, "permissiondenied", "badvalue"])
def test_server_denials_are_not_retried_or_cached(tmp_path, response):
    calls = []
    client = PoliteClient(
        tmp_path,
        sleep=lambda _: None,
        transport=httpx.MockTransport(
            lambda r: calls.append(r)
            or httpx.Response(
                response if isinstance(response, int) else 200,
                json={"error": {"code": response}},
            )
        ),
    )
    try:
        with pytest.raises(SourceUnavailable):
            client.json(COMMONS_API, PARAMS)
        assert len(calls) == 1 and not list(tmp_path.glob("*.body"))
    finally:
        client.close()


def test_api_media_entity_reads_are_limited_to_claims(tmp_path):
    request = api_url(
        {
            "action": "wbgetentities",
            "ids": "M123|M456",
            "props": "claims",
            "format": "json",
        }
    )
    assert metadata_request(request)
    assert not metadata_request(request.replace("claims", "sitelinks"))
    assert not metadata_request(request.replace("wbgetentities", "wbeditentity"))


@pytest.mark.parametrize("scenario", ["accepted", "unlicensed", "ambiguous"])
def test_image_api_policy_preserves_license_gate_science_and_audio(
    database, tmp_path, scenario
):
    acceptable = scenario == "accepted"
    image = pytest.importorskip("PIL.Image")
    from app.importer import sources

    with sqlite3.connect(database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    before = database.read_bytes()
    cache = tmp_path / "audio_cache"
    cache.mkdir()
    audio = cache / "existing.wav"
    audio.write_bytes(b"existing verified cache sentinel")
    old_audio = hashlib.sha256(audio.read_bytes()).hexdigest()
    name = record["scientific_name"]
    image_bytes = io.BytesIO()
    image.new("RGB", (300, 200), "navy").save(image_bytes, format="PNG")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /w/\n")
        if request.url.host == "paleobiodb.org":
            return httpx.Response(200, json={"records": []})
        if request.url.host == "upload.wikimedia.org":
            assert acceptable
            return httpx.Response(200, content=image_bytes.getvalue())
        assert (
            request.url.host == "commons.wikimedia.org"
            and request.url.path == "/w/api.php"
        )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "1": {
                            "pageid": 1,
                            "title": "File:Synthetic",
                            "imageinfo": [
                                {
                                    "url": "https://upload.wikimedia.org/synthetic.png",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Synthetic",
                                    "extmetadata": {
                                        key: {"value": value}
                                        for key, value in {
                                            "Artist": "Fixture creator",
                                            "LicenseShortName": "CC0"
                                            if scenario != "unlicensed"
                                            else "All rights reserved",
                                            "LicenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
                                            "ImageDescription": (
                                                "Possibly a life reconstruction of "
                                                if scenario == "ambiguous"
                                                else "Life reconstruction of "
                                            )
                                            + name,
                                        }.items()
                                    },
                                }
                            ],
                        }
                    }
                }
            },
        )

    client = PoliteClient(
        tmp_path / "http", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        proposal = collect(client, record, tmp_path / "stage")
        assert proposal["images"][0]["supported"] is acceptable
        assert proposal["images"][0]["review_status"] == "pending"
        assert proposal["images"][0]["creator"] == "Fixture creator"
        assert bool(proposal["images"][0].get("preview_file")) is acceptable
        assert (
            any(
                r.url.host == "upload.wikimedia.org" and r.url.path != "/robots.txt"
                for r in calls
            )
            is acceptable
        )
        assert (
            database.read_bytes() == before
            and hashlib.sha256(audio.read_bytes()).hexdigest() == old_audio
        )
        assert not any(
            r.url.host == "commons.wikimedia.org" and r.url.path == "/robots.txt"
            for r in calls
        )
    finally:
        client.close()


def test_api_requests_keep_per_host_throttling(tmp_path):
    clock = {"now": 1000.0}
    times = []

    def pause(seconds):
        clock["now"] += seconds

    def handler(request):
        times.append(clock["now"])
        return httpx.Response(200, json={"query": {"pages": {}}})

    client = PoliteClient(
        tmp_path,
        delay=1.2,
        sleep=pause,
        clock=lambda: clock["now"],
        transport=httpx.MockTransport(handler),
    )
    try:
        client.json(COMMONS_API, PARAMS)
        client.json(COMMONS_API, {**PARAMS, "gsrsearch": "Triceratops"})
        assert len(times) == 2 and times[1] - times[0] >= 1.2 - 1e-9
    finally:
        client.close()
