"""Explicit robots opt-out does not weaken transport or image validation."""

import httpx
import pytest
from app.importer.network import PoliteClient, SourceUnavailable
from app.importer.api_policy import COMMONS_API
from app.importer.runner import execute
from test_importer import database, FakeClient

TARGETS = [
    "https://paleobiodb.org/data1.2/taxa/list.json?name=Tyrannosaurus",
    COMMONS_API + "?action=query&format=json",
]


@pytest.mark.parametrize(
    "setting", [None, "true", "", "0", "1", "no", "off", "invalid"]
)
@pytest.mark.parametrize("url", TARGETS)
def test_default_and_non_false_values_enforce_disallow(
    tmp_path, monkeypatch, setting, url
):
    if setting is None:
        monkeypatch.delenv("IMPORT_RESPECT_ROBOTS", raising=False)
    else:
        monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", setting)
    # The retired API switch cannot silently override the new default.
    monkeypatch.setenv("BBS_COMMONS_API_POLICY", "documented-api")
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
            client.get(url)
        assert client.respect_robots and len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("setting", ["false", "FALSE", " false "])
@pytest.mark.parametrize("url", TARGETS)
def test_explicit_false_sends_previously_disallowed_requests(
    tmp_path, monkeypatch, setting, url
):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", setting)
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        assert request.headers["user-agent"].startswith("BedtimeBattleStoriesImporter/")
        assert request.method == "GET"
        return httpx.Response(200, json={"query": {"pages": {}}})

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        assert client.get(url).status_code == 200
        assert not client.respect_robots and len(calls) == 1
        assert calls[0].url.path != "/robots.txt"
        assert client.events[0]["phase"] == "robots_disabled"
        assert client.events[0]["configuration"] == "IMPORT_RESPECT_ROBOTS=false"
        assert client.client.timeout.read == 25
    finally:
        client.close()


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("url", TARGETS)
def test_opt_out_never_retries_access_denials(tmp_path, monkeypatch, url, status):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    calls = []
    client = PoliteClient(
        tmp_path,
        sleep=lambda _: None,
        transport=httpx.MockTransport(
            lambda r: calls.append(r) or httpx.Response(status)
        ),
    )
    try:
        with pytest.raises(SourceUnavailable, match=f"HTTP {status}"):
            client.get(url)
        assert len(calls) == 1 and client.events[-1]["http_status"] == status
        assert not list(tmp_path.glob("*.body"))
    finally:
        client.close()


def test_opt_out_does_not_solve_or_cache_api_captcha(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    calls = []
    client = PoliteClient(
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: calls.append(r)
            or httpx.Response(200, text="<html><h1>Complete a CAPTCHA</h1></html>")
        ),
    )
    try:
        with pytest.raises(SourceUnavailable, match="non-JSON"):
            client.get(TARGETS[1])
        assert len(calls) == 1 and not list(tmp_path.glob("*.body"))
    finally:
        client.close()


def test_opt_out_keeps_redirect_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    calls = []
    client = PoliteClient(
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: calls.append(r)
            or httpx.Response(
                302, headers={"Location": "https://unapproved.test/redirect"}
            )
        ),
    )
    try:
        with pytest.raises(SourceUnavailable, match="Unapproved"):
            client.get(TARGETS[0])
        assert len(calls) == 1
    finally:
        client.close()


def test_opt_out_applies_to_allowed_redirects_without_robots_fetches(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    calls = []

    def handler(r):
        calls.append(r)
        return (
            httpx.Response(
                302,
                headers={"Location": "https://paleobiodb.org/data1.2/taxa/other.json"},
            )
            if len(calls) == 1
            else httpx.Response(200, json={"records": []})
        )

    client = PoliteClient(
        tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    try:
        assert client.get(TARGETS[0]).status_code == 200
        assert len(calls) == 2 and all(r.url.path != "/robots.txt" for r in calls)
    finally:
        client.close()


def test_opt_out_keeps_retries_backoff_and_per_host_pacing(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    now = {"time": 1000.0}
    times = []
    pauses = []

    def sleep(seconds):
        pauses.append(seconds)
        now["time"] += seconds

    def handler(r):
        times.append(now["time"])
        return (
            httpx.Response(429, headers={"Retry-After": "7"})
            if len(times) == 1
            else httpx.Response(200, json={"records": []})
        )

    client = PoliteClient(
        tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        clock=lambda: now["time"],
    )
    try:
        client.get(TARGETS[0])
        client.get(TARGETS[0] + "&limit=5")
        assert len(times) == 3 and 7 in pauses and times[2] - times[1] >= 1.2 - 1e-9
    finally:
        client.close()


def test_changing_robots_setting_invalidates_completed_checkpoints(
    database, tmp_path, monkeypatch
):
    folder = tmp_path / "state"
    client = FakeClient()
    run = lambda: execute(
        database, folder, pilot=1, client=client, progress=lambda *a, **k: None
    )
    monkeypatch.delenv("IMPORT_RESPECT_ROBOTS", raising=False)
    assert run()["processed"] == 1 and run()["resumed"] == 1
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "false")
    report = run()
    assert report["processed"] == 1 and not report["respect_robots"]
    assert run()["resumed"] == 1
    monkeypatch.setenv("IMPORT_RESPECT_ROBOTS", "true")
    assert run()["processed"] == 1
