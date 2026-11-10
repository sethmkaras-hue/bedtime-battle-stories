"""Persistent chapter rules, real WAV measurement with synthetic CPU providers."""

import copy
import json
import uuid
import wave

import pytest
from app import main
from app.audio.service import AudioService
from app.chapters import store, simulation, narrative
from app.chapters.worker import Coordinator
from test_parent_review import parent, login  # noqa: F401

HEADERS = {"X-Bedtime-Client": "app"}


class Voice:
    name = "kokoro"
    calls = 0

    def is_available(self):
        return True

    def list_voices(self):
        return [{"id": "fixture", "name": "Synthetic voice"}]

    def version(self):
        return "synthetic-duration-v1"

    def get_provider_info(self):
        return {"available": True, "voices": self.list_voices(), "reason": ""}

    def generate_audio(self, text, voice, speed, path):
        type(self).calls += 1
        duration = len(text.split()) / (2.15 * speed)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * round(duration * 8000))


@pytest.fixture
def story(parent, tmp_path, monkeypatch):
    client, _, folder = parent
    main.app.state.chapters.close()
    monkeypatch.setenv("BBS_CHAPTER_AUDIO", str(tmp_path / "archived"))
    audio = AudioService(
        tmp_path / "chapter-cache", tmp_path / "models", providers={"kokoro": Voice()}
    )
    worker = Coordinator(main.DB, audio, start=False)
    ids = [c["id"] for c in client.get("/api/creatures?category=dinosaur").json()][:8]
    yield client, worker, ids, audio
    audio.close()


def new(story, seed=123, request_key=None):
    client, worker, ids, audio = story
    response = client.post(
        "/api/story/tournaments",
        headers=HEADERS,
        json={
            "creature_ids": ids,
            "seed": seed,
            "request_key": request_key or uuid.uuid4().hex,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def begin(story, state, predicted=None, skipped=True):
    client, worker, _, _ = story
    cid = state["chapter"]["battle_id"]
    path = f"/api/story/tournaments/{state['id']}/battles/{cid}"
    response = client.post(
        path + "/begin",
        headers=HEADERS,
        json={
            "predicted_winner_id": predicted,
            "skipped": skipped,
            "audio": {"provider": "kokoro", "voice": "fixture", "speed": 1},
        },
    )
    assert response.status_code == 202, response.text
    return path, cid, response.json()


def test_create_idempotency_default_seed_and_schema_preservation(story):
    client, _, ids, _ = story
    body = {"creature_ids": ids, "request_key": uuid.uuid4().hex}
    a = client.post("/api/story/tournaments", headers=HEADERS, json=body)
    b = client.post("/api/story/tournaments", headers=HEADERS, json=body)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert a.json()["seed"] == b.json()["seed"]
    with store.connection(main.DB) as conn:
        assert conn.execute("SELECT COUNT(*) FROM story_tournaments").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM creatures").fetchone()[0] >= 8
        assert conn.execute("SELECT COUNT(*) FROM story_battles").fetchone()[0] == 7
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM story_battles WHERE simulation IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
    assert "winner" not in json.dumps(a.json()["outline"]).lower().replace(
        "no future winners", ""
    )


def test_prediction_does_not_change_simulation_or_replay(story):
    first = new(story)
    second = new(story)
    a = first["chapter"]["participants"]
    b = second["chapter"]["participants"]
    p1, bid1, _ = begin(story, first, a[0]["id"], False)
    p2, bid2, _ = begin(story, second, b[1]["id"], False)
    with store.connection(main.DB) as conn:
        s1 = json.loads(
            conn.execute(
                "SELECT simulation FROM story_battles WHERE id=?", (bid1,)
            ).fetchone()[0]
        )
        s2 = json.loads(
            conn.execute(
                "SELECT simulation FROM story_battles WHERE id=?", (bid2,)
            ).fetchone()[0]
        )
        assert s1["winner_id"] == s2["winner_id"] and s1["draw"] == s2["draw"]
    story[1].once()
    story[1].once()
    result = story[0].post(p1 + "/complete", headers=HEADERS)
    assert result.status_code == 200, result.text
    saved = story[0].get(p1).json()
    assert saved["prediction"]["correct"] == (
        saved["simulation"]["winner_id"] == a[0]["id"]
    )
    late = story[0].post(
        p1 + "/begin",
        headers=HEADERS,
        json={"predicted_winner_id": a[1]["id"], "skipped": False},
    )
    assert late.status_code == 409
    assert story[0].get(p1).json()["prediction"] == saved["prediction"]
    assert story[0].post(p1 + "/complete", headers=HEADERS).json()["completed"] == 1


def test_duration_measurement_archiving_and_cache_clear(story):
    state = new(story)
    path, bid, _ = begin(story, state)
    assert story[1].once()
    result = story[0].get(path).json()
    assert result["status"] == "ready" and result["audio"]["timing_met"]
    assert 18 <= result["audio"]["actual_seconds"] <= 22
    assert "winner_id" not in result["narrative"] and result["simulation"] is None
    with wave.open(result["audio"]["path"], "rb") as wav:
        assert wav.getnframes() / wav.getframerate() == pytest.approx(
            result["audio"]["actual_seconds"]
        )
    url = result["audio"]["url"]
    assert story[0].get(url).status_code == 200
    story[3].clear()
    assert story[0].get(url).status_code == 200
    calls = Voice.calls
    again = story[0].post(
        path + "/begin",
        headers=HEADERS,
        json={
            "skipped": True,
            "audio": {"provider": "kokoro", "voice": "fixture", "speed": 1},
        },
    )
    assert again.status_code == 202 and Voice.calls == calls
    with store.connection(main.DB) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM story_jobs WHERE status='pending'"
            ).fetchone()[0]
            == 0
        )


def test_all_seven_chapters_continuity_champion_and_history(story):
    client, worker, _, _ = story
    state = new(story)
    for number in range(1, 8):
        assert state["chapter"]["chapter_number"] == number
        path, bid, _ = begin(story, state)
        worker.once()
        result = client.get(path).json()
        assert result["status"] == "ready", result
        assert all(ref < number for ref in result["narrative"]["references"])
        if number == 7:
            assert "Six completed battles" in result["narrative"]["paragraphs"][0]
        state = client.post(path + "/complete", headers=HEADERS).json()
        assert state["completed"] == number
    assert state["champion"] and state["chapter"] is None
    assert len(state["history"]) == 7 and all(
        h["prediction"]["skipped"] for h in state["history"]
    )
    assert client.get("/api/story/tournaments").json()[0]["completed"] == 7
    restored = store.state(main.DB, state["id"])
    assert restored["champion"]["id"] == state["champion"]["id"]


def test_settings_snapshot_and_adult_protection(story):
    client, worker, _, _ = story
    assert client.get("/api/story/settings").json() == store.DEFAULTS
    prefs = {**store.DEFAULTS, "duration_seconds": 20, "predictions_enabled": False}
    assert client.put("/api/admin/story/settings", json=prefs).status_code == 401
    headers = login(client)
    assert (
        client.put("/api/admin/story/settings", headers=headers, json=prefs).status_code
        == 200
    )
    state = new(story)
    path, bid, _ = begin(story, state)
    prefs["duration_seconds"] = 60
    client.put("/api/admin/story/settings", headers=headers, json=prefs)
    worker.once()
    data = client.get(path).json()
    assert data["audio"]["requested_seconds"] == 20
    with store.connection(main.DB) as conn:
        assert store.settings(conn)["duration_seconds"] == 60
    assert store.state(main.DB, state["id"])["chapter"]["requested_duration"] == 20


def test_retry_missing_audio_keeps_simulation_and_valid_text(story, monkeypatch):
    state = new(story)
    path, bid, _ = begin(story, state)
    monkeypatch.setattr(
        story[1],
        "synthesize",
        lambda req: (_ for _ in ()).throw(RuntimeError("fixture failure")),
    )
    story[1].once()
    data = story[0].get(path).json()
    assert data["status"] == "failed" and data["narrative"]
    with store.connection(main.DB) as conn:
        before = conn.execute(
            "SELECT simulation FROM story_battles WHERE id=?", (bid,)
        ).fetchone()[0]
    begin(story, state)
    with store.connection(main.DB) as conn:
        assert (
            conn.execute(
                "SELECT simulation FROM story_battles WHERE id=?", (bid,)
            ).fetchone()[0]
            == before
        )
    assert (
        story[0].post(path + "/complete", headers=HEADERS).status_code == 409
    )  # still preparing


def test_simulation_probabilities_environment_and_fact_boundaries():
    left = {"id": 1, "name": "Strong", "gameplay_rating": 5, "habitat": "land"}
    right = {"id": 2, "name": "Quick", "gameplay_rating": 2, "habitat": "land"}
    a = simulation.simulate(left, right, 12, "land")
    b = simulation.simulate(left, right, 12, "land")
    assert a == b and a["left_win_probability"] > 0.5
    winners = {
        simulation.simulate(left, right, n, "land")["winner_id"] for n in range(100)
    }
    assert winners == {1, 2}
    assert a["inputs"][0]["documented"].get("weight") is None
    assert all(
        simulation.simulate(left, right, n, "water")["environment"]["arena"] == "water"
        for n in range(5)
    )
    weights = copy.deepcopy(left)
    weights["profile"] = {
        "verification_status": "unverified",
        "weight": {"minimum": 10000, "maximum": 12000},
    }
    assert "weight" not in simulation.inputs(weights)["documented"]


def test_bad_ids_late_rounds_and_prediction_shape(story):
    client, _, ids, _ = story
    assert (
        client.post(
            "/api/story/tournaments",
            headers=HEADERS,
            json={"creature_ids": [ids[0]] * 8, "request_key": uuid.uuid4().hex},
        ).status_code
        == 409
    )
    assert client.get("/api/story/tournaments/missing").status_code == 404
    state = new(story)
    final = state["rounds"][-1]["matches"][0]["battle_id"]
    assert (
        client.post(
            f"/api/story/tournaments/{state['id']}/battles/{final}/begin",
            headers=HEADERS,
            json={"skipped": True},
        ).status_code
        == 409
    )
    path = (
        f"/api/story/tournaments/{state['id']}/battles/{state['chapter']['battle_id']}"
    )
    assert (
        client.post(
            path + "/begin",
            headers=HEADERS,
            json={"predicted_winner_id": 99999, "skipped": False},
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + "/begin",
            headers=HEADERS,
            json={"predicted_winner_id": None, "skipped": False},
        ).status_code
        == 409
    )


def test_regeneration_requires_explicit_adult_confirmation(story):
    state = new(story)
    path, bid, _ = begin(story, state)
    story[1].once()
    client = story[0]
    headers = login(client)
    url = f"/api/admin/story/tournaments/{state['id']}/battles/{bid}/regenerate"
    assert client.post(url, json={"confirm": True}).status_code == 403
    assert client.post(url, headers=headers, json={"confirm": 1}).status_code == 422
    with store.connection(main.DB) as conn:
        before = conn.execute(
            "SELECT simulation FROM story_battles WHERE id=?", (bid,)
        ).fetchone()[0]
    assert client.post(url, headers=headers, json={"confirm": True}).status_code == 202
    story[1].once()
    with store.connection(main.DB) as conn:
        assert (
            conn.execute(
                "SELECT simulation FROM story_battles WHERE id=?", (bid,)
            ).fetchone()[0]
            == before
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM story_chapter_versions WHERE battle_id=?", (bid,)
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize("duration", [20, 30, 40, 50, 60])
def test_all_duration_targets_use_measured_audio(story, duration):
    client, worker, _, _ = story
    client.put(
        "/api/admin/story/settings",
        headers=login(client),
        json={**store.DEFAULTS, "duration_seconds": duration},
    )
    state = new(story)
    path, bid, _ = begin(story, state)
    worker.once()
    result = client.get(path).json()
    assert result["status"] == "ready"
    assert abs(result["audio"]["actual_seconds"] - duration) <= max(2, duration * 0.05)
    assert len(result["audio"]["attempts"]) <= 3
    with store.connection(main.DB) as conn:
        assert (
            conn.execute("SELECT samples FROM story_tts_calibration").fetchone()[0] == 1
        )


def test_restart_recovers_pending_job_without_resimulating(story):
    import time

    client, worker, _, audio = story
    state = new(story)
    path, bid, _ = begin(story, state)
    with store.connection(main.DB) as conn:
        previous = conn.execute(
            "SELECT simulation FROM story_battles WHERE id=?", (bid,)
        ).fetchone()[0]
        conn.execute("UPDATE story_jobs SET status='generating'")
        conn.execute("UPDATE story_chapters SET status='generating'")
    recovered = Coordinator(main.DB, audio)
    try:
        deadline = time.monotonic() + 5
        while (
            time.monotonic() < deadline and client.get(path).json()["status"] != "ready"
        ):
            time.sleep(0.05)
        assert client.get(path).json()["status"] == "ready"
        with store.connection(main.DB) as conn:
            assert (
                conn.execute(
                    "SELECT simulation FROM story_battles WHERE id=?", (bid,)
                ).fetchone()[0]
                == previous
            )
    finally:
        recovered.close()


def test_bounded_timing_preserves_best_valid_audio(story, monkeypatch):
    def fixed(self, text, voice, speed, path):
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * 160000)

    monkeypatch.setattr(Voice, "generate_audio", fixed)
    story[0].put(
        "/api/admin/story/settings",
        headers=login(story[0]),
        json={**store.DEFAULTS, "duration_seconds": 40},
    )
    state = new(story)
    path, bid, _ = begin(story, state)
    story[1].once()
    data = story[0].get(path).json()
    assert data["status"] == "ready" and data["audio"]["actual_seconds"] == 20
    assert not data["audio"]["timing_met"] and len(data["audio"]["attempts"]) == 3
    assert data["audio"]["speaking_rate"] == 1
    assert story[0].get(data["audio"]["url"]).status_code == 200


def test_failed_explicit_regeneration_keeps_last_good_version(story, monkeypatch):
    state = new(story)
    path, bid, _ = begin(story, state)
    story[1].once()
    original = story[0].get(path).json()
    url = f"/api/admin/story/tournaments/{state['id']}/battles/{bid}/regenerate"
    story[0].post(url, headers=login(story[0]), json={"confirm": True})
    monkeypatch.setattr(
        story[1],
        "synthesize",
        lambda req: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )
    story[1].once()
    latest = story[0].get(path).json()
    assert latest["status"] == "ready" and latest["audio"] == original["audio"]
    assert latest["narrative"] == original["narrative"]


def test_simulation_persists_even_if_submission_interrupted(story, monkeypatch):
    state = new(story)
    original = store.enqueue
    monkeypatch.setattr(
        store,
        "enqueue",
        lambda *args: (_ for _ in ()).throw(ValueError("temporary queue failure")),
    )
    client, _, _, _ = story
    bid = state["chapter"]["battle_id"]
    response = client.post(
        f"/api/story/tournaments/{state['id']}/battles/{bid}/begin",
        headers=HEADERS,
        json={"skipped": True},
    )
    assert response.status_code == 409
    with store.connection(main.DB) as conn:
        simulation_before = conn.execute(
            "SELECT simulation FROM story_battles WHERE id=?", (bid,)
        ).fetchone()[0]
    assert simulation_before
    monkeypatch.setattr(store, "enqueue", original)
    begin(story, state)
    with store.connection(main.DB) as conn:
        assert (
            conn.execute(
                "SELECT simulation FROM story_battles WHERE id=?", (bid,)
            ).fetchone()[0]
            == simulation_before
        )


def test_additive_migration_keeps_legacy_tables_and_backups(tmp_path):
    import sqlite3

    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE old_tournaments(id INTEGER PRIMARY KEY, winner TEXT)"
        )
        conn.execute("INSERT INTO old_tournaments VALUES(1,'original winner')")
    store.migrate(db)
    with store.connection(db) as conn:
        assert (
            conn.execute("SELECT winner FROM old_tournaments").fetchone()[0]
            == "original winner"
        )
        assert not conn.execute("SELECT * FROM story_tournaments").fetchall()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    store.migrate(db)
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_known_incompatible_habitats_use_explicit_fiction_not_dry_aquatic_arena(story):
    client, worker, ids, audio = story
    all_rows = client.get("/api/creatures").json()
    marine = next(c for c in all_rows if c["habitat"] == "marine")
    chosen = ids[:7] + [marine["id"]]
    response = client.post(
        "/api/story/tournaments",
        headers=HEADERS,
        json={"creature_ids": chosen, "seed": 42, "request_key": uuid.uuid4().hex},
    )
    assert response.status_code == 201, response.text
    assert response.json()["arena"] == "neutral"
    a = all_rows[0]
    b = marine
    result = simulation.simulate(a, b, 42, "neutral")
    assert not result["environment"]["scientifically_realistic"]
    assert "own habitat" in result["environment"]["habitat_note"]


def test_narrative_validation_rejects_winner_changes_and_future_references():
    a = {"id": 1, "name": "Alpha", "gameplay_rating": 4, "habitat": "land"}
    b = {"id": 2, "name": "Beta", "gameplay_rating": 3, "habitat": "land"}
    result = simulation.simulate(a, b, 43, "land")
    data = narrative.generate(
        a, b, result, 1, narrative.outline("land"), [], store.DEFAULTS
    )
    parsed = narrative.Narrative.model_validate(data)
    parsed.winner_id = 999
    with pytest.raises(ValueError, match="simulation"):
        narrative.validate(parsed, result, 1, [])
    parsed.winner_id = result["winner_id"]
    parsed.paragraphs.append("Chapter 9 has already happened.")
    with pytest.raises(ValueError, match="future"):
        narrative.validate(parsed, result, 1, [])


def test_worker_capacity_rejects_overflow_without_duplicate_jobs(story):
    with store.connection(main.DB) as conn:
        for n in range(8):
            store.enqueue(conn, "test", str(n), {})
        assert store.enqueue(conn, "test", "0", {})
        with pytest.raises(ValueError, match="queue is full"):
            store.enqueue(conn, "test", "overflow", {})
        assert conn.execute("SELECT COUNT(*) FROM story_jobs").fetchone()[0] == 8


def test_history_pagination_keeps_older_adventures_accessible(story):
    first = new(story)
    for _ in range(20):
        new(story)
    client = story[0]
    assert len(client.get("/api/story/tournaments").json()) == 20
    older = client.get("/api/story/tournaments?offset=20&limit=20").json()
    assert len(older) == 1 and older[0]["id"] == first["id"]
    assert client.get("/api/story/tournaments?offset=-1").status_code == 422
    assert client.get("/api/story/tournaments/" + first["id"]).status_code == 200


def test_cache_deletion_waits_for_chapter_publication(story):
    client, worker, _, _ = story
    state = new(story)
    path, bid, _ = begin(story, state)
    assert (
        client.delete(
            "/api/audio/cache", headers={"X-Bedtime-Confirm": "clear"}
        ).status_code
        == 409
    )
    worker.once()
    url = client.get(path).json()["audio"]["url"]
    assert (
        client.delete(
            "/api/audio/cache", headers={"X-Bedtime-Confirm": "clear"}
        ).status_code
        == 200
    )
    assert client.get(url).status_code == 200


def test_actual_local_fallback_voice_is_remembered_for_tournament(story):
    class MissingPiper(Voice):
        name = "piper"

        def is_available(self):
            return False

    client, worker, _, audio = story
    audio.providers["piper"] = MissingPiper()
    state = new(story)
    bid = state["chapter"]["battle_id"]
    path = f"/api/story/tournaments/{state['id']}/battles/{bid}"
    response = client.post(
        path + "/begin",
        headers=HEADERS,
        json={
            "skipped": True,
            "audio": {"provider": "piper", "voice": "missing", "speed": 1},
        },
    )
    assert response.status_code == 202
    worker.once()
    data = client.get(path).json()
    assert data["status"] == "ready" and data["audio"]["provider"] == "kokoro"
    remembered = client.get("/api/story/tournaments/" + state["id"]).json()[
        "audio_preferences"
    ]
    assert remembered["provider"] == "kokoro" and remembered["voice"] == "fixture"
