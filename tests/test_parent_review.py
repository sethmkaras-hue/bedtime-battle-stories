"""Authenticated parent decisions; no public administrative mutation or filesystem API."""

import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import main
from app.importer.auth import ParentAuth, password_record
from app.importer.store import Store


@pytest.fixture
def parent(tmp_path, monkeypatch):
    folder = tmp_path / "importer"
    folder.mkdir()
    (folder / "parent-auth.json").write_text(
        json.dumps(password_record("test-parent-passphrase"))
    )
    monkeypatch.setenv("BBS_IMPORT_DIR", str(folder))
    monkeypatch.setenv("BBS_AUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("BBS_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(main, "DB", tmp_path / "app.sqlite3")
    monkeypatch.setattr(main, "CATALOG", False)
    monkeypatch.setattr(main, "SAMPLE", True)
    with TestClient(main.app) as client:
        with sqlite3.connect(main.DB) as conn:
            record = json.loads(
                conn.execute(
                    "SELECT record_json FROM creature_profiles WHERE creature_id=1"
                ).fetchone()[0]
            )
        store = Store(folder)
        payload = {
            "stable_key": record["stable_key"],
            "record": record,
            "science": {"time_period": "Source fixture period"},
            "evidence": [
                {
                    "id": "fixture",
                    "title": "Synthetic test source",
                    "url": "https://paleobiodb.org/test",
                    "supports": ["time_period"],
                }
            ],
            "pronunciation": {
                "phonetic": "tie-RAN-oh-sore-us",
                "stress": "RAN",
                "tts_text": "tie ran oh sore us",
                "source_url": "https://www.nhm.ac.uk/test",
            },
            "images": [],
            "issues": [],
            "display_name": "Tyrannosaurus",
            "scientific_name": "Tyrannosaurus rex",
            "stage": "imported_candidates",
        }
        pid = store.stage(record["stable_key"], "test-input", payload)
        store.close()
        yield client, pid, folder


def login(client):
    response = client.post(
        "/api/admin/login",
        json={"password": "test-parent-passphrase"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "SameSite=strict" in response.headers["set-cookie"]
    )
    return {"Origin": "http://testserver", "X-Parent-CSRF": response.json()["csrf"]}


def test_parent_review_requires_authentication_origin_and_csrf(parent):
    client, pid, folder = parent
    body = {"decision": "approve", "scopes": ["science"], "confirm": True}
    assert client.get("/api/admin/proposals").status_code == 401
    assert (
        client.post(f"/api/admin/proposals/{pid}/decision", json=body).status_code
        == 401
    )
    assert (
        client.post(
            "/api/admin/login",
            json={"password": "test-parent-passphrase"},
            headers={"Origin": "https://unrelated.test"},
        ).status_code
        == 403
    )
    headers = login(client)
    assert (
        client.post(
            f"/api/admin/proposals/{pid}/decision",
            json=body,
            headers={"Origin": "http://testserver"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/admin/proposals/{pid}/decision",
            json=body,
            headers={**headers, "Origin": "https://unrelated.test"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/admin/proposals/{pid}/decision",
            json={**body, "confirm": False},
            headers=headers,
        ).status_code
        == 422
    )
    assert client.get("/api/admin/proposals").status_code == 200


def test_explicit_approval_preserves_id_and_protects_reviewed_field(parent):
    client, pid, folder = parent
    headers = login(client)
    result = client.post(
        f"/api/admin/proposals/{pid}/decision",
        json={
            "decision": "approve",
            "scopes": ["science", "pronunciation"],
            "confirm": True,
        },
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["backup_created"]
    with sqlite3.connect(main.DB) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
        assert record["id"] == 1 and record["time_period"] == "Source fixture period"
        assert (
            record["pronunciation"]["status"] == "verified"
            and record["verification_status"] == "unverified"
        )
        assert "time_period" in record["reviewed_fields"]
    assert len(list((main.DB.parent / "backups").glob("*.sqlite3"))) == 1
    assert (
        client.post(
            f"/api/admin/proposals/{pid}/decision",
            json={"decision": "approve", "scopes": ["science"], "confirm": True},
            headers=headers,
        ).status_code
        == 409
    )
    assert client.post("/api/admin/logout", json={}, headers=headers).status_code == 200
    assert client.get("/api/admin/proposals").status_code == 401


def test_rejection_does_not_change_canonical_record(parent):
    client, pid, folder = parent
    headers = login(client)
    before = main.DB.read_bytes()
    result = client.post(
        f"/api/admin/proposals/{pid}/decision",
        json={"decision": "reject", "confirm": True},
        headers=headers,
    )
    assert result.status_code == 200 and main.DB.read_bytes() == before


def test_login_rate_limit_expiry_and_password_rotation(tmp_path):
    now = [1000.0]
    folder = tmp_path / "auth"
    folder.mkdir()
    file = folder / "parent-auth.json"
    file.write_text(json.dumps(password_record("test-parent-passphrase")))
    auth = ParentAuth(folder, clock=lambda: now[0])
    for _ in range(5):
        assert auth.login("incorrect", "fixture-ip") is None
    with pytest.raises(PermissionError):
        auth.login("test-parent-passphrase", "fixture-ip")
    now[0] += 601
    token, csrf = auth.login("test-parent-passphrase", "fixture-ip")
    assert auth.session(token)
    now[0] += 901
    assert auth.session(token) is None
    token, csrf = auth.login("test-parent-passphrase", "another-ip")
    file.write_text(json.dumps(password_record("replacement-parent-passphrase")))
    assert auth.session(token) is None


def test_review_preserves_existing_citation_identity(parent):
    client, pid, folder = parent
    with sqlite3.connect(main.DB) as conn:
        raw = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE creature_id=1"
        ).fetchone()[0]
        record = json.loads(raw)
        old = {
            "id": "fixture",
            "title": "Previously inspected evidence",
            "url": "https://paleobiodb.org/old",
            "supports": ["diet"],
        }
        record["sources"].append(old)
        conn.execute(
            "UPDATE creature_profiles SET record_json=? WHERE creature_id=1",
            (json.dumps(record),),
        )
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert response.status_code == 200
    with sqlite3.connect(main.DB) as conn:
        updated = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    citations = {source["id"]: source for source in updated["sources"]}
    assert citations["fixture"]["url"] == old["url"]
    assert any(key.startswith("fixture-review-") for key in citations)
