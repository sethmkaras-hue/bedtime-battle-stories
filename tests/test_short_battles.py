"""New choices, restored spoken names, and non-destructive short-battle updates."""

import json

# Imported pytest fixtures intentionally share their injection parameter names.
# ruff: noqa: F811
import wave

import pytest
from test_chapters import HEADERS, new, story  # noqa: F401
from test_parent_review import login, parent  # noqa: F401

from app import main
from app.chapters import combat, narrative, pronunciation, simulation, store


def path(state, index=0):
    bid = state["rounds"][0]["matches"][index]["battle_id"]
    return f"/api/story/tournaments/{state['id']}/battles/{bid}", bid


def test_want_saved_before_think_guarantees_winner_and_advancement(story, monkeypatch):
    client, worker, _, _ = story
    state = new(story)
    url, _bid = path(state)
    a, b = state["chapter"]["participants"]
    wanted = {"desired_winner_id": b["id"]}
    assert client.post(url + "/desire", headers=HEADERS, json=wanted).status_code == 200
    resumed = client.get(url).json()
    assert resumed["desired_choice"]["desired_winner_id"] == b["id"]
    assert resumed["status"] == "not_started" and resumed["prediction"] is None
    with store.connection(main.DB) as conn:
        assert not conn.execute("SELECT * FROM story_jobs").fetchall()
    monkeypatch.setattr(
        simulation,
        "simulate",
        lambda *args: pytest.fail("simulation must not override WANT"),
    )
    request = {
        **wanted,
        "predicted_winner_id": a["id"],
        "skipped": False,
        "audio": {"provider": "kokoro", "voice": "fixture", "speed": 1},
    }
    assert client.post(url + "/begin", headers=HEADERS, json=request).status_code == 202
    worker.once()
    assert client.get(url).json()["simulation"] is None  # reveal gated
    completed = client.post(url + "/complete", headers=HEADERS).json()
    choice = completed["history"][0]["choices"]
    assert choice["desired_winner_id"] == choice["actual_winner_id"] == b["id"]
    assert (
        choice["predicted_winner_id"] == a["id"]
        and choice["prediction_correct"] is False
    )
    assert choice["winner_method"] == "child_choice" and choice["timestamp"]
    assert completed["rounds"][1]["matches"][0]["left"]["id"] == b["id"]
    before = client.get(url).json()
    assert before["narrative"]["winner_id"] == b["id"]
    assert client.post(url + "/begin", headers=HEADERS, json=request).status_code == 202
    assert client.post(url + "/complete", headers=HEADERS).json()["completed"] == 1
    assert client.get(url).json() == before
    assert (
        client.post(
            url + "/desire", headers=HEADERS, json={"desired_winner_id": a["id"]}
        ).status_code
        == 409
    )
    request["predicted_winner_id"] = b["id"]
    assert client.post(url + "/begin", headers=HEADERS, json=request).status_code == 409


def test_skips_simulate_and_any_known_match_can_start(story):
    client, worker, _, _ = story
    state = new(story)
    url, _bid = path(state, 3)
    assert (
        client.post(
            url + "/desire", headers=HEADERS, json={"desired_winner_id": None}
        ).status_code
        == 200
    )
    body = {
        "skipped": True,
        "audio": {"provider": "kokoro", "voice": "fixture", "speed": 1},
    }
    assert client.post(url + "/begin", headers=HEADERS, json=body).status_code == 202
    worker.once()
    result = client.post(url + "/complete", headers=HEADERS).json()
    choice = result["history"][0]["choices"]
    assert choice["winner_method"] == "simulation"
    assert (
        choice["desired_winner_id"]
        is choice["predicted_winner_id"]
        is choice["prediction_correct"]
        is None
    )
    final = result["rounds"][-1]["matches"][0]["battle_id"]
    assert (
        client.post(
            f"/api/story/tournaments/{state['id']}/battles/{final}/begin",
            headers=HEADERS,
            json=body,
        ).status_code
        == 409
    )
    assert result["rounds"][0]["matches"][0]["eligible"]
    assert not result["rounds"][1]["matches"][0]["eligible"]


def test_default_migration_once_preserves_history_and_custom_duration(story):
    state = new(story)
    with store.connection(main.DB) as conn:
        conn.execute(
            "UPDATE story_settings SET data=?",
            (json.dumps({**store.DEFAULTS, "duration_seconds": 40}),),
        )
        conn.execute(
            "DELETE FROM story_update_migrations WHERE name='short_battles_choices_v2'"
        )
        old = conn.execute("SELECT data FROM story_tournaments").fetchone()[0]
    store.migrate(main.DB)
    with store.connection(main.DB) as conn:
        assert store.settings(conn)["duration_seconds"] == 20
        assert conn.execute("SELECT data FROM story_tournaments").fetchone()[0] == old
        assert (
            store.choices(
                conn.execute("SELECT * FROM story_battles LIMIT 1").fetchone()
            )
            is None
        )
        conn.execute(
            "UPDATE story_settings SET data=?",
            (json.dumps({**store.DEFAULTS, "duration_seconds": 50}),),
        )
    store.migrate(main.DB)
    with store.connection(main.DB) as conn:
        assert store.settings(conn)["duration_seconds"] == 50
    assert store.state(main.DB, state["id"])["completed"] == 0


def test_unverified_names_generate_serve_cache_and_repair(story, monkeypatch):
    client, worker, ids, audio = story
    monkeypatch.setattr(main.app.state, "audio", audio)
    cid = ids[0]
    url = f"/api/library/creatures/{cid}/pronunciation"
    body = {"provider": "kokoro", "voice": "fixture", "speed": 0.8}
    with store.connection(main.DB) as conn:
        original = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE creature_id=?", (cid,)
        ).fetchone()[0]
    response = client.post(url, headers=HEADERS, json=body)
    assert response.status_code == 202, response.text
    job = response.json()["job_id"]
    assert client.post(url, headers=HEADERS, json=body).json()["job_id"] == job
    worker.once()
    result = client.get("/api/library/pronunciation-jobs/" + job).json()
    assert result["status"] == "ready", result
    asset = result["asset"]
    assert asset["metadata"]["basis"] == "synthesized_display_name"
    assert not asset["metadata"]["verified_pronunciation"]
    response = client.get(asset["url"])
    assert (
        response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    )
    assert response.content[:4] == b"RIFF"
    assert client.post(url, headers=HEADERS, json=body).json()["status"] == "ready"
    with store.connection(main.DB) as conn:
        assert (
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=?", (cid,)
            ).fetchone()[0]
            == original
        )
    key = asset["url"].split("/")[-1]
    wav = audio.root / "pronunciation" / f"{key}.wav"
    wav.write_bytes(wav.read_bytes()[:44])  # header survives, PCM is gone
    assert client.get(asset["url"]).status_code == 404
    retry = client.post(url, headers=HEADERS, json=body).json()
    assert retry["status"] == "pending"
    worker.once()
    assert (
        client.get("/api/library/pronunciation-jobs/" + retry["job_id"]).json()[
            "status"
        ]
        == "ready"
    )
    with wave.open(str(wav), "rb") as sound:
        assert len(sound.readframes(sound.getnframes())) > 0
    audio.clear()
    assert client.get(asset["url"]).status_code == 404
    assert client.post(url, headers=HEADERS, json=body).json()["status"] == "pending"
    assert (
        client.post(
            url, headers=HEADERS, json={**body, "provider": "openai"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/library/creatures/999999/pronunciation", headers=HEADERS, json=body
        ).status_code
        == 404
    )


def test_all_catalog_names_have_local_recipe(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(main, "SAMPLE", False)
    monkeypatch.setattr(main, "CATALOG", True)
    main.initialize_database()
    with store.connection(main.DB) as conn:
        records = [
            json.loads(row[0])
            for row in conn.execute("SELECT record_json FROM creature_profiles")
        ]
    assert len(records) == 164
    for record in records:
        text, basis, signature = pronunciation.recipe(record)
        assert text and len(text) <= 200 and len(signature) == 64
        assert basis in {"verified_guidance", "synthesized_display_name"}


@pytest.mark.parametrize(
    "genus,weapon",
    [
        ("Tyrannosaurus", "bite"),
        ("Triceratops", "horns"),
        ("Stegosaurus", "spiked_tail"),
        ("Ankylosaurus", "club"),
        ("Velociraptor", "claws"),
    ],
)
def test_physical_attacks_match_anatomy(genus, weapon):
    actor = {
        "id": 1,
        "name": genus,
        "category": "dinosaur",
        "habitat": "land",
        "gameplay_rating": 2,
    }
    rival = {
        "id": 2,
        "name": "Tyrannosaurus",
        "category": "dinosaur",
        "habitat": "land",
        "gameplay_rating": 5,
    }
    assert combat.ability(actor) == weapon
    sim = simulation.chosen(actor, rival, 23, "land", 1)
    before = json.dumps(sim, sort_keys=True)
    data = narrative.generate(
        actor, rival, sim, 1, narrative.outline("land"), [], store.DEFAULTS
    )
    text = " ".join(data["paragraphs"]) + " " + data["ending"]
    assert data["winner_id"] == 1 and f"{genus} " in data["ending"]
    assert any(term in text for term in ("bruise", "cut", "stagger", "limps"))
    assert "sidesteps" in data["ending"] or "turns" in data["ending"]
    assert json.dumps(sim, sort_keys=True) == before
    assert not any(term in text for term in ("gore", "entrails", "severed"))


def test_sharks_do_not_grow_legs_horns_or_claws():
    a = {
        "id": 1,
        "name": "Great white shark",
        "category": "shark",
        "habitat": "marine",
        "gameplay_rating": 3,
    }
    b = {**a, "id": 2, "name": "Tiger shark"}
    sim = simulation.chosen(a, b, 42, "water", 2)
    data = narrative.generate(
        a, b, sim, 1, narrative.outline("water"), [], store.DEFAULTS
    )
    text = " ".join(data["paragraphs"]) + " " + data["ending"]
    assert "bites" in text and "swims" in text
    assert not any(term in text for term in ("legs", "horn", "claw", "limps", "feet"))


def test_actual_v1_schema_migration_keeps_original_result(tmp_path):
    db = tmp_path / "old.sqlite3"
    with store.connection(db) as conn:
        conn.execute(
            "CREATE TABLE story_settings(id INTEGER PRIMARY KEY,data TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO story_settings VALUES(1,?)",
            (json.dumps({**store.DEFAULTS, "duration_seconds": 40}),),
        )
        conn.execute(
            "CREATE TABLE story_battles(id TEXT PRIMARY KEY,tournament_id TEXT,number INTEGER,left_id INTEGER,right_id INTEGER,simulation TEXT,prediction TEXT,completed TEXT)"
        )
        original = (
            "battle",
            "tournament",
            1,
            1,
            2,
            json.dumps({"winner_id": 2}),
            json.dumps(
                {
                    "predicted_winner_id": 1,
                    "actual_winner_id": 2,
                    "correct": False,
                    "skipped": False,
                    "timestamp": "2025-01-01",
                }
            ),
            "2025-01-02",
        )
        conn.execute("INSERT INTO story_battles VALUES(?,?,?,?,?,?,?,?)", original)
    store.migrate(db)
    with store.connection(db) as conn:
        row = conn.execute("SELECT * FROM story_battles").fetchone()
        assert tuple(row)[:8] == original
        assert tuple(row)[8:] == (None, None, None, None)
        assert store.choices(row) is None and store.desire(row) is None
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_spoken_name_local_fallback_and_failure_are_explicit(story, monkeypatch):
    from test_chapters import Voice

    client, worker, ids, audio = story

    class Missing(Voice):
        name = "piper"

        def is_available(self):
            return False

    audio.providers["piper"] = Missing()
    monkeypatch.setattr(main.app.state, "audio", audio)
    endpoint = f"/api/library/creatures/{ids[0]}/pronunciation"
    body = {"provider": "piper", "voice": "missing", "speed": 0.8}
    job = client.post(endpoint, headers=HEADERS, json=body).json()["job_id"]
    worker.once()
    result = client.get("/api/library/pronunciation-jobs/" + job).json()
    assert result["status"] == "ready"
    assert (
        result["asset"]["provider"] == "kokoro"
        and result["asset"]["voice"] == "fixture"
    )
    assert client.post(endpoint, headers=HEADERS, json=body).json()["status"] == "ready"
    audio.clear()
    monkeypatch.setattr(audio.providers["kokoro"], "is_available", lambda: False)
    job = client.post(endpoint, headers=HEADERS, json=body).json()["job_id"]
    worker.once()
    failed = client.get("/api/library/pronunciation-jobs/" + job).json()
    assert failed["status"] == "failed" and failed["message"]
    assert not failed["asset"]


def test_desired_winner_rejects_invalid_and_coerced_ids(story):
    client, _, _, _ = story
    state = new(story)
    url, _bid = path(state)
    for value in ["1", True, 1.1]:
        assert (
            client.post(
                url + "/desire", headers=HEADERS, json={"desired_winner_id": value}
            ).status_code
            == 422
        )
    assert (
        client.post(
            url + "/desire", headers=HEADERS, json={"desired_winner_id": 999999}
        ).status_code
        == 409
    )
    assert client.get(url).json()["desired_choice"] is None
