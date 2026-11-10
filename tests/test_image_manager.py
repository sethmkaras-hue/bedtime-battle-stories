"""Adult-selected replacement reuses the existing importer and policy client."""

import io
import json
from pathlib import Path
import httpx
import pytest
from app import main
from app.chapters import store, images
from app.importer.network import PoliteClient
from app.importer import internet_images as imports
from test_chapters import story  # noqa: F401
from test_parent_review import login, parent  # noqa: F401


@pytest.fixture
def manager(story, tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setenv("BBS_CREATURE_IMAGE_DIR", str(tmp_path / "images"))
    client, worker, ids, audio = story
    record = images.current_record(main.DB, ids[0])
    content = io.BytesIO()
    Image.new("RGB", (800, 600), "navy").save(content, format="PNG")
    blob = content.getvalue()
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "commons.wikimedia.org":
            pages = {
                str(n): {
                    "pageid": n,
                    "title": "File:" + record["scientific_name"] + " " + str(n),
                    "imageinfo": [
                        {
                            "url": f"https://upload.wikimedia.org/{n}.png",
                            "thumburl": f"https://upload.wikimedia.org/thumb/{n}.png",
                            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:Fixture{n}",
                            "width": 800,
                            "height": 600,
                            "extmetadata": {
                                "ImageDescription": {
                                    "value": record["scientific_name"]
                                    + " life restoration"
                                }
                            },
                        }
                    ],
                }
                for n in range(25)
            }
            return httpx.Response(200, json={"query": {"pages": pages}})
        assert request.url.host == "upload.wikimedia.org"
        return httpx.Response(200, content=blob, headers={"content-type": "image/png"})

    def create(root, **kwargs):
        return PoliteClient(
            root, transport=httpx.MockTransport(handler), sleep=lambda _: None, **kwargs
        )

    monkeypatch.setattr(images, "PoliteClient", create)
    yield client, worker, record, login(client), calls


def search(manager):
    client, worker, record, headers, _ = manager
    response = client.post(
        f"/api/admin/image-manager/{record['id']}/search",
        headers=headers,
        json={"query": record["scientific_name"]},
    )
    assert response.status_code == 202, response.text
    jid = response.json()["job_id"]
    assert worker.once()
    assert (
        client.get("/api/admin/image-manager/jobs/" + jid).json()["status"] == "ready"
    )
    return jid


def test_image_search_pagination_preview_and_no_full_import(manager):
    client, worker, record, headers, calls = manager
    jid = search(manager)
    result = client.get(
        f"/api/admin/image-manager/{record['id']}/candidates/{jid}"
    ).json()
    assert (
        len(result["candidates"]) == 20
        and result["total"] == 25
        and result["next_offset"] == 20
    )
    assert result["candidates"][0]["license"] is None
    preview = client.get(result["candidates"][0]["preview_url"])
    assert (
        preview.status_code == 200 and preview.headers["content-type"] == "image/webp"
    )
    more = client.post(
        "/api/admin/image-manager/more",
        headers=headers,
        json={"search_id": jid, "offset": 20},
    )
    assert more.status_code == 202
    worker.once()
    assert (
        len(
            client.get(
                f"/api/admin/image-manager/{record['id']}/candidates/{jid}?offset=20"
            ).json()["candidates"]
        )
        == 5
    )
    assert all(
        r.url.host in {"commons.wikimedia.org", "upload.wikimedia.org"} for r in calls
    )
    assert all(
        r.url.params.get("gsrsearch") == record["scientific_name"]
        for r in calls
        if r.url.params.get("generator") == "search"
    )
    with store.connection(main.DB) as conn:
        assert not imports.registered(conn)


def test_replace_restore_preserves_files_versions_and_active_url(manager):
    client, worker, record, headers, calls = manager
    ids = [c["id"] for c in client.get("/api/creatures?category=dinosaur").json()][:8]
    adventure = client.post(
        "/api/story/tournaments",
        headers={"X-Bedtime-Client": "app"},
        json={
            "creature_ids": ids,
            "seed": 7,
            "request_key": "target-picture-update-001",
        },
    ).json()
    before = next(
        c for c in client.get("/api/creatures").json() if c["id"] == record["id"]
    )
    original = client.get(f"/api/admin/image-manager/{record['id']}/history").json()[0]
    jid = search(manager)
    candidate = client.get(
        f"/api/admin/image-manager/{record['id']}/candidates/{jid}"
    ).json()["candidates"][0]
    response = client.post(
        f"/api/admin/image-manager/{record['id']}/replace",
        headers=headers,
        json={"candidate_id": candidate["id"]},
    )
    assert response.status_code == 202
    worker.once()
    after = next(
        c for c in client.get("/api/creatures").json() if c["id"] == record["id"]
    )
    assert (
        after["image_reference"] != before["image_reference"]
        and after["image_kind"] == "internet"
    )
    url = after["image_reference"]
    persisted = client.get("/api/story/tournaments/" + adventure["id"]).json()
    participant = next(
        c
        for match in persisted["rounds"][0]["matches"]
        for c in (match["left"], match["right"])
        if c["id"] == record["id"]
    )
    assert participant["image_reference"] == url
    assert client.get(url).status_code == 200
    restore = client.post(
        f"/api/admin/image-manager/{record['id']}/restore",
        headers=headers,
        json={"history_id": original["id"]},
    )
    assert restore.status_code == 200, restore.text
    restored = next(
        c for c in client.get("/api/creatures").json() if c["id"] == record["id"]
    )
    assert restored["image_reference"] == before["image_reference"]
    assert client.get(url).status_code == 200
    history = client.get(f"/api/admin/image-manager/{record['id']}/history").json()
    assert len(history) == 2 and sum(h["active"] for h in history) == 1
    newer = next(h for h in history if not h["active"])
    client.post(
        f"/api/admin/image-manager/{record['id']}/restore",
        headers=headers,
        json={"history_id": newer["id"]},
    )
    assert (
        next(c for c in client.get("/api/creatures").json() if c["id"] == record["id"])[
            "image_reference"
        ]
        == url
    )


def test_missing_wrong_candidate_and_arbitrary_urls_are_rejected(manager):
    client, worker, record, headers, _ = manager
    endpoint = f"/api/admin/image-manager/{record['id']}/replace"
    assert (
        client.post(
            endpoint, headers=headers, json={"download_url": "http://127.0.0.1/secret"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            endpoint, headers=headers, json={"candidate_id": "a" * 32}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/admin/image-manager/999999/search", headers=headers, json={}
        ).status_code
        == 404
    )
    jid = search(manager)
    candidate = client.get(
        f"/api/admin/image-manager/{record['id']}/candidates/{jid}"
    ).json()["candidates"][0]
    assert (
        client.post(
            "/api/admin/image-manager/9999/replace",
            headers=headers,
            json={"candidate_id": candidate["id"]},
        ).status_code
        == 404
    )


def test_registered_but_unsafe_remote_url_still_fails_without_changing_current(manager):
    client, worker, record, headers, _ = manager
    jid = search(manager)
    with store.connection(main.DB) as conn:
        row = conn.execute(
            "SELECT * FROM story_image_candidates WHERE job_id=? LIMIT 1", (jid,)
        ).fetchone()
        data = json.loads(row["metadata"])
        data["download_url"] = "http://127.0.0.1/private"
        conn.execute(
            "UPDATE story_image_candidates SET metadata=? WHERE id=?",
            (json.dumps(data), row["id"]),
        )
    request = client.post(
        f"/api/admin/image-manager/{record['id']}/replace",
        headers=headers,
        json={"candidate_id": row["id"]},
    ).json()
    worker.once()
    assert (
        client.get("/api/admin/image-manager/jobs/" + request["job_id"]).json()[
            "status"
        ]
        == "failed"
    )
    current = next(
        c for c in client.get("/api/creatures").json() if c["id"] == record["id"]
    )
    assert current["artwork_placeholder"]


def test_image_controls_require_authentication_and_csrf(story):
    client, _, ids, _ = story
    assert (
        client.post(f"/api/admin/image-manager/{ids[0]}/search", json={}).status_code
        == 401
    )
    login(client)
    assert (
        client.post(f"/api/admin/image-manager/{ids[0]}/search", json={}).status_code
        == 403
    )


def test_restore_actual_previous_picture_and_reject_corrupt_version(manager):
    from test_internet_images import chosen, pixels

    client, worker, record, headers, calls = manager
    old = chosen(record)
    imports.install(main.DB, record, old, pixels("red"))
    original = client.get(f"/api/admin/image-manager/{record['id']}/history").json()[0]
    old_url = original["url"]
    old_bytes = client.get(old_url).content
    jid = search(manager)
    choice = client.get(
        f"/api/admin/image-manager/{record['id']}/candidates/{jid}"
    ).json()["candidates"][0]
    client.post(
        f"/api/admin/image-manager/{record['id']}/replace",
        headers=headers,
        json={"candidate_id": choice["id"]},
    )
    worker.once()
    latest = next(
        c for c in client.get("/api/creatures").json() if c["id"] == record["id"]
    )["image_reference"]
    assert latest != old_url
    restored = client.post(
        f"/api/admin/image-manager/{record['id']}/restore",
        headers=headers,
        json={"history_id": original["id"]},
    )
    assert restored.status_code == 200
    assert (
        next(c for c in client.get("/api/creatures").json() if c["id"] == record["id"])[
            "image_reference"
        ]
        == old_url
    )
    assert (
        client.get(old_url).content == old_bytes
        and client.get(latest).status_code == 200
    )
    with store.connection(main.DB) as conn:
        version = conn.execute(
            "SELECT * FROM internet_image_versions WHERE key=?",
            (old_url.rsplit("/", 1)[-1],),
        ).fetchone()
    Path(version["path"]).write_bytes(b"corrupt synthetic fixture")
    assert (
        client.post(
            f"/api/admin/image-manager/{record['id']}/restore",
            headers=headers,
            json={"history_id": original["id"]},
        ).status_code
        == 409
    )
