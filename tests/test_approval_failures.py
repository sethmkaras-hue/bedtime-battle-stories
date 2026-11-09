"""Regressions from the parent-review boundary; synthetic data only."""

import json
import sqlite3
import pytest
from app import main, library
from app.importer.store import Store
from test_parent_review import parent, login


def test_sourced_habitat_can_be_approved(parent):
    client, pid, folder = parent
    store = Store(folder)
    row = store.get(pid)
    payload = json.loads(row["payload"])
    payload["science"]["habitat"] = "land"
    payload["evidence"][0]["supports"].append("habitat")
    with store.conn:
        store.conn.execute(
            "UPDATE proposals SET payload=? WHERE id=?", (json.dumps(payload), pid)
        )
    store.close()
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert response.status_code == 200, response.text
    with sqlite3.connect(main.DB) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    assert record["reviewed_fields"]["habitat"]["reviewer"] == "parent-review"


def test_missing_proposal_is_not_reported_as_bad_content(parent):
    client, pid, folder = parent
    response = client.post(
        "/api/admin/proposals/999999/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert response.status_code == 404, response.text


def test_double_decision_is_conflict_not_validation_failure(parent):
    client, pid, folder = parent
    headers = login(client)
    body = {"decision": "reject", "confirm": True}
    assert (
        client.post(
            f"/api/admin/proposals/{pid}/decision", headers=headers, json=body
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/admin/proposals/{pid}/decision", headers=headers, json=body
    )
    assert response.status_code == 409, response.text


def test_image_license_identifier_and_declaration_must_agree():
    data = {
        "placeholder": False,
        "path": "/static/creatures/test.webp",
        "creator": "Synthetic creator",
        "original_source_url": "https://example.test/art",
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Synthetic credit",
        "modifications": "WebP conversion",
        "identified_taxon": "Fixture testensis",
        "verified_by": "Fixture reviewer",
        "checked_on": "2026-11-01",
    }
    with pytest.raises(ValueError, match="license"):
        library.Image.model_validate(data)


def test_partial_approval_keeps_unprocessed_guidance(parent):
    client, pid, folder = parent
    headers = login(client)
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=headers,
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert response.status_code == 200
    assert response.json()["remaining_scopes"] == ["pronunciation"]
    pending = client.get("/api/admin/proposals").json()["pending"]
    assert len(pending) == 1 and pending[0]["applied_scopes"] == ["science"]
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=headers,
        json={"decision": "approve", "scopes": ["pronunciation"], "confirm": True},
    )
    assert response.status_code == 200 and response.json()["remaining_scopes"] == []
    assert client.get("/api/admin/proposals").json()["pending"] == []


@pytest.mark.parametrize(
    "body,field",
    [
        ({"decision": "approve", "scopes": ["science"]}, "confirm"),
        (
            {
                "decision": "approve",
                "scopes": ["science"],
                "confirm": True,
                "image_index": "0",
            },
            "image_index",
        ),
        ({"decision": "approve", "scopes": ["unknown"], "confirm": True}, "scopes"),
        ({"decision": "approve", "scopes": ["science"], "confirm": 1}, "confirm"),
    ],
)
def test_invalid_request_has_actionable_field_details_and_safe_logs(
    parent, body, field, caplog
):
    client, pid, folder = parent
    response = client.post(
        f"/api/admin/proposals/{pid}/decision", headers=login(client), json=body
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_request" and detail["creature"] == "Tyrannosaurus"
    assert any(field in issue["loc"] for issue in detail["issues"])
    assert "parent_decision" in caplog.text and "Tyrannosaurus" in caplog.text
    assert "test-parent-passphrase" not in caplog.text
    assert "input_value" not in response.text


@pytest.mark.parametrize("identifier", ["not-a-number", "0", "-1"])
def test_invalid_path_identifiers_remain_validation_errors(parent, identifier):
    client, pid, folder = parent
    result = client.post(
        f"/api/admin/proposals/{identifier}/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert (
        result.status_code == 422
        and result.json()["detail"]["code"] == "invalid_request"
    )


def test_science_range_validation_is_shared_with_automatic_imports(parent, caplog):
    from app.importer.runner import apply_supported

    client, pid, folder = parent
    store = Store(folder)
    row = store.get(pid)
    payload = json.loads(row["payload"])
    payload["science"]["length"] = {
        "minimum": 0,
        "maximum": 5.0,
        "unit": "m",
        "source_ids": ["fixture"],
    }
    with store.conn:
        store.conn.execute(
            "UPDATE proposals SET payload=? WHERE id=?", (json.dumps(payload), pid)
        )
    before = main.DB.read_bytes()
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert response.status_code == 422
    assert any(
        "length" in issue["loc"] for issue in response.json()["detail"]["issues"]
    )
    with pytest.raises(ValueError):
        apply_supported(main.DB, payload["record"], payload)
    assert main.DB.read_bytes() == before and store.get(pid)["status"] == "pending"
    assert "automatic_science" in caplog.text and "Tyrannosaurus" in caplog.text
    store.close()


def test_missing_license_is_reported_without_writing_profile(parent):
    import hashlib

    client, pid, folder = parent
    store = Store(folder)
    row = store.get(pid)
    payload = json.loads(row["payload"])
    sha = hashlib.sha256(b"synthetic original").hexdigest()
    (folder / "originals").mkdir()
    (folder / "originals" / f"{sha}.image").write_bytes(b"synthetic original")
    payload["images"] = [
        {
            "supported": True,
            "original_file": f"originals/{sha}.image",
            "sha256": sha,
            "identified_taxon": payload["scientific_name"],
            "creator": "Synthetic creator",
            "original_source_url": "https://example.test/fixture",
            "license": "CC0-1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
    ]
    with store.conn:
        store.conn.execute(
            "UPDATE proposals SET payload=? WHERE id=?", (json.dumps(payload), pid)
        )
    before = main.DB.read_bytes()
    result = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["image"], "confirm": True},
    )
    assert result.status_code == 422
    assert (
        "attribution" in result.text.lower()
        and result.json()["detail"]["creature"] == "Tyrannosaurus"
    )
    assert main.DB.read_bytes() == before and store.get(pid)["status"] == "pending"
    store.close()


def test_database_constraint_failure_is_logged_and_does_not_apply(
    parent, monkeypatch, caplog
):
    client, pid, folder = parent

    def conflict(*args, **kwargs):
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: creature_profiles.scientific_identity"
        )

    monkeypatch.setattr(library, "import_records", conflict)
    before = main.DB.read_bytes()
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=login(client),
        json={"decision": "approve", "scopes": ["science"], "confirm": True},
    )
    assert (
        response.status_code == 409
        and response.json()["detail"]["code"] == "database_conflict"
    )
    assert main.DB.read_bytes() == before and "parent_approval" in caplog.text


def test_shared_source_normalization_does_not_mutate_proposal(parent):
    from app.importer.runner import apply_supported

    client, pid, folder = parent
    store = Store(folder)
    payload = json.loads(store.get(pid)["payload"])
    store.close()
    payload["science"]["length"] = {
        "minimum": 3.0,
        "maximum": 4.0,
        "unit": "m",
        "source_ids": ["fixture"],
    }
    before = json.loads(json.dumps(payload))
    apply_supported(main.DB, payload["record"], payload)
    assert payload == before


def test_protected_measurement_retains_its_citation_during_bulk_import(parent):
    client, pid, folder = parent
    with sqlite3.connect(main.DB) as conn:
        record = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
        record["length"] = {
            "minimum": 3.0,
            "maximum": 4.0,
            "unit": "m",
            "source_ids": ["old-range"],
        }
        record["sources"].append(
            {
                "id": "old-range",
                "title": "Synthetic reviewed range",
                "url": "https://example.test/old",
            }
        )
        record["reviewed_fields"]["length"] = {
            "reviewer": "Fixture reviewer",
            "checked_on": "2026-11-01",
        }
        library.import_records(conn, [record])
        replacement = json.loads(json.dumps(record))
        replacement["sources"] = [
            {
                "id": "new-range",
                "title": "New synthetic range",
                "url": "https://example.test/new",
            }
        ]
        replacement["length"] = {
            "minimum": 5.0,
            "maximum": 6.0,
            "unit": "m",
            "source_ids": ["new-range"],
        }
        library.import_records(conn, [replacement])
        saved = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=1"
            ).fetchone()[0]
        )
    assert saved["length"]["source_ids"] == ["old-range"]
    assert "old-range" in {source["id"] for source in saved["sources"]}


def test_blank_guidance_is_not_verified(parent):
    client, pid, folder = parent
    response = client.post(
        f"/api/admin/proposals/{pid}/decision",
        headers=login(client),
        json={
            "decision": "approve",
            "scopes": ["pronunciation"],
            "confirm": True,
            "phonetic": "  ",
        },
    )
    assert response.status_code == 422 and "phonetic" in response.text


def test_resume_reports_invalid_content_instead_of_aborting(parent):
    from app.importer.runner import execute, digest
    from test_importer import FakeClient

    client, pid, folder = parent
    store = Store(folder)
    payload = json.loads(store.get(pid)["payload"])
    payload["science"]["length"] = {
        "minimum": 0,
        "maximum": 1.0,
        "unit": "m",
        "source_ids": ["fixture"],
    }
    with store.conn:
        store.conn.execute(
            "UPDATE proposals SET payload=? WHERE id=?", (json.dumps(payload), pid)
        )
        store.conn.execute(
            "UPDATE checkpoints SET input_hash=? WHERE proposal_id=?",
            (digest(payload["record"]), pid),
        )
    store.close()
    report = execute(
        main.DB, folder, pilot=1, client=FakeClient(), progress=lambda *a, **k: None
    )
    assert (
        report["resumed"] == 1
        and report["errors"][0]["operation"] == "automatic_science"
    )
    assert report["errors"][0]["creature"] == "Tyrannosaurus"
