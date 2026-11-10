"""Additive namespaced history; never rewrites legacy tournament data."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from . import narrative, simulation

DEFAULTS = {
    "duration_seconds": 40,
    "tone": "dramatic",
    "predictions_enabled": True,
    "winner_mode": "simulation",
    "connected_chapters": True,
}


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection(db):
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate(db, backup_existing=True):
    from app.importer.store import backup

    with connection(db) as conn:
        needed = not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='story_settings'"
        ).fetchone()
    if needed and backup_existing:
        backup(db)
    with connection(db) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS story_tts_calibration(identity TEXT PRIMARY KEY,words_per_second REAL NOT NULL,samples INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS story_settings(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS story_tournaments(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,
          data TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS story_battles(id TEXT PRIMARY KEY,tournament_id TEXT NOT NULL REFERENCES story_tournaments(id),
          number INTEGER NOT NULL,left_id INTEGER,right_id INTEGER,simulation TEXT,prediction TEXT,
          completed TEXT,UNIQUE(tournament_id,number));
        CREATE TABLE IF NOT EXISTS story_chapters(battle_id TEXT PRIMARY KEY REFERENCES story_battles(id),
          revision INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL,settings TEXT NOT NULL,
          narrative TEXT,audio TEXT,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS story_chapter_versions(battle_id TEXT NOT NULL,revision INTEGER NOT NULL,
          narrative TEXT,audio TEXT,created TEXT NOT NULL,PRIMARY KEY(battle_id,revision));
        CREATE TABLE IF NOT EXISTS story_jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,target TEXT NOT NULL,
          payload TEXT NOT NULL,status TEXT NOT NULL,worker TEXT,error TEXT,created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS story_job_queue ON story_jobs(status,created,id);
        CREATE INDEX IF NOT EXISTS story_history_page ON story_tournaments(created,id);
        CREATE UNIQUE INDEX IF NOT EXISTS story_active_jobs ON story_jobs(kind,target) WHERE status IN ('pending','generating');
        CREATE TABLE IF NOT EXISTS story_image_candidates(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,
          creature_id INTEGER NOT NULL,metadata TEXT NOT NULL,preview_path TEXT);
        CREATE TABLE IF NOT EXISTS story_image_choice(creature_id INTEGER PRIMARY KEY,history_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS story_candidate_pages ON story_image_candidates(job_id,creature_id);
        CREATE TABLE IF NOT EXISTS story_image_history(id TEXT PRIMARY KEY,creature_id INTEGER NOT NULL,
          kind TEXT NOT NULL,asset_key TEXT,metadata TEXT NOT NULL,created TEXT NOT NULL);
        """)
        conn.execute(
            "INSERT OR IGNORE INTO story_settings VALUES(1,?)", (json.dumps(DEFAULTS),)
        )


def settings(conn):
    return json.loads(
        conn.execute("SELECT data FROM story_settings WHERE id=1").fetchone()[0]
    )


def enqueue(conn, kind, target, payload):
    old = conn.execute(
        "SELECT id,payload FROM story_jobs WHERE kind=? AND target=? AND status IN ('pending','generating')",
        (kind, target),
    ).fetchone()
    if old:
        if kind.startswith("image_") and any(
            json.loads(old["payload"]).get(k) != v for k, v in payload.items()
        ):
            raise ValueError(
                "Another image task is already active for this creature; wait before changing the request"
            )
        return old["id"]
    if (
        conn.execute(
            "SELECT COUNT(*) FROM story_jobs WHERE status IN ('pending','generating')"
        ).fetchone()[0]
        >= 8
    ):
        raise ValueError("The local preparation queue is full; try again shortly")
    key = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO story_jobs VALUES(?,?,?,?,'pending',NULL,NULL,?)",
        (key, kind, target, json.dumps(payload), now()),
    )
    return key


def create(db, creatures, ids, seed, shuffle, request_key):
    import random
    from app.main import arenas_for, HABITAT_ARENAS

    if len(set(ids)) != 8 or any(i not in creatures for i in ids):
        raise ValueError("Choose eight distinct available creatures")
    selected = [creatures[i] for i in ids]
    arenas = arenas_for(selected)
    if any(not HABITAT_ARENAS.get(c.get("habitat")) for c in selected):
        raise ValueError("Choose creatures with known safe habitats")
    if shuffle:
        random.Random(seed).shuffle(selected)
    arena = sorted(arenas)[0] if arenas else "neutral"
    with connection(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT id,data FROM story_tournaments WHERE request_key=?", (request_key,)
        ).fetchone()
        if old:
            data = json.loads(old["data"])
            if (
                data["entrant_ids"] != ids
                or data["seed"] != seed
                or data["shuffle"] != shuffle
            ):
                raise ValueError(
                    "Creation key is already used for different entrants/settings"
                )
            return old["id"]
        tid = uuid.uuid4().hex
        data = {
            "entrant_ids": ids,
            "snapshots": {str(c["id"]): c for c in selected},
            "seed": seed,
            "shuffle": shuffle,
            "arena": arena,
            "outline": narrative.outline(arena),
            "version": 1,
        }
        conn.execute(
            "INSERT INTO story_tournaments VALUES(?,?,?,?)",
            (tid, request_key, json.dumps(data), now()),
        )
        for n in range(1, 8):
            left, right = (
                (selected[(n - 1) * 2]["id"], selected[(n - 1) * 2 + 1]["id"])
                if n <= 4
                else (None, None)
            )
            conn.execute(
                "INSERT INTO story_battles VALUES(?,?,?,?,?,NULL,NULL,NULL)",
                (uuid.uuid4().hex, tid, n, left, right),
            )
    return tid


def battle(conn, tid, bid):
    row = conn.execute(
        "SELECT * FROM story_battles WHERE tournament_id=? AND id=?", (tid, bid)
    ).fetchone()
    if not row:
        raise LookupError("Battle not found")
    return row


def competitors(conn, tid, row):
    if row["number"] <= 4:
        return row["left_id"], row["right_id"]
    feeds = {5: (1, 2), 6: (3, 4), 7: (5, 6)}[row["number"]]
    previous = [
        conn.execute(
            "SELECT * FROM story_battles WHERE tournament_id=? AND number=?", (tid, n)
        ).fetchone()
        for n in feeds
    ]
    if any(not p["completed"] or not p["simulation"] for p in previous):
        raise ValueError("Complete the earlier chapters first")
    return tuple(json.loads(p["simulation"])["winner_id"] for p in previous)


def begin(db, tid, bid, predicted, skipped, audio_settings):
    with connection(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = battle(conn, tid, bid)
        prior = conn.execute(
            "SELECT COUNT(*) FROM story_battles WHERE tournament_id=? AND number<? AND completed IS NULL",
            (tid, row["number"]),
        ).fetchone()[0]
        if prior:
            raise ValueError("Complete the earlier chapters first")
        if row["completed"]:
            previous = json.loads(row["prediction"]) if row["prediction"] else None
            if previous and (
                previous["predicted_winner_id"] != predicted
                or previous["skipped"] != skipped
            ):
                raise ValueError("A completed battle cannot accept a new prediction")
            return bid  # idempotent retries preserve the original prediction/result
        tournament = json.loads(
            conn.execute(
                "SELECT data FROM story_tournaments WHERE id=?", (tid,)
            ).fetchone()[0]
        )
        left, right = competitors(conn, tid, row)
        if predicted is not None and predicted not in (left, right):
            raise ValueError("Predict one of these two creatures")
        prefs = settings(conn)
        if not prefs["predictions_enabled"]:
            predicted, skipped = None, True
        if (predicted is None) != skipped:
            raise ValueError("Choose a creature or explicitly skip")
        if row["prediction"]:
            old = json.loads(row["prediction"])
            if old["predicted_winner_id"] != predicted or old["skipped"] != skipped:
                raise ValueError("Prediction is already saved")
        else:
            prediction = {
                "predicted_winner_id": predicted,
                "skipped": skipped,
                "timestamp": now(),
                "actual_winner_id": None,
                "correct": None,
            }
            conn.execute(
                "UPDATE story_battles SET prediction=? WHERE id=?",
                (json.dumps(prediction), bid),
            )
        tournament["audio_preferences"] = audio_settings
        conn.execute(
            "UPDATE story_tournaments SET data=? WHERE id=?",
            (json.dumps(tournament), tid),
        )
        if not row["simulation"]:
            sim = simulation.simulate(
                tournament["snapshots"][str(left)],
                tournament["snapshots"][str(right)],
                simulation.battle_seed(tournament["seed"], row["number"]),
                tournament["arena"],
            )
            sim["completed_at"] = now()
            conn.execute(
                "UPDATE story_battles SET left_id=?,right_id=?,simulation=? WHERE id=?",
                (left, right, json.dumps(sim), bid),
            )
    # Commit simulation BEFORE story generation or worker submission.
    with connection(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        chapter = conn.execute(
            "SELECT * FROM story_chapters WHERE battle_id=?", (bid,)
        ).fetchone()
        if not chapter:
            prefs = {
                **settings(conn),
                "audio": audio_settings,
                "speech_rate": audio_settings.get("speed", 1),
            }
            conn.execute(
                "INSERT INTO story_chapters(battle_id,status,settings,created,updated) VALUES(?,'pending',?,?,?)",
                (bid, json.dumps(prefs), now(), now()),
            )
        if chapter and chapter["status"] == "failed":
            previous_settings = json.loads(chapter["settings"])
            previous_settings.update(
                audio=audio_settings, speech_rate=audio_settings.get("speed", 1)
            )
            conn.execute(
                "UPDATE story_chapters SET settings=? WHERE battle_id=?",
                (json.dumps(previous_settings), bid),
            )
        if not chapter or chapter["status"] in ("pending", "failed"):
            conn.execute(
                "UPDATE story_chapters SET status='pending',error=NULL WHERE battle_id=?",
                (bid,),
            )
            enqueue(conn, "chapter", bid, {})
    return bid


def complete(db, tid, bid):
    with connection(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = battle(conn, tid, bid)
        if row["completed"]:
            return
        chapter = conn.execute(
            "SELECT * FROM story_chapters WHERE battle_id=?", (bid,)
        ).fetchone()
        if not chapter or not chapter["narrative"]:
            raise ValueError("The chapter is not prepared yet")
        if chapter["status"] in ("pending", "generating"):
            raise ValueError("The chapter is still preparing")
        prediction = json.loads(row["prediction"])
        prediction["actual_winner_id"] = json.loads(row["simulation"])["winner_id"]
        prediction["correct"] = (
            None
            if prediction["skipped"]
            else prediction["predicted_winner_id"] == prediction["actual_winner_id"]
        )
        conn.execute(
            "UPDATE story_battles SET completed=?,prediction=? WHERE id=?",
            (now(), json.dumps(prediction), bid),
        )


def state(db, tid, current_creatures=None):
    with connection(db) as conn:
        tournament = conn.execute(
            "SELECT * FROM story_tournaments WHERE id=?", (tid,)
        ).fetchone()
        if not tournament:
            raise LookupError("Tournament not found")
        data = json.loads(tournament["data"])
        rows = conn.execute(
            "SELECT * FROM story_battles WHERE tournament_id=? ORDER BY number", (tid,)
        ).fetchall()
        prefs = settings(conn)

        def creature(cid):
            if cid is None:
                return None
            item = dict(data["snapshots"][str(cid)])
            if current_creatures and cid in current_creatures:
                latest = current_creatures[cid]
                for key in (
                    "image_reference",
                    "image_variants",
                    "image_kind",
                    "artwork_placeholder",
                    "internet_image",
                    "generated_image",
                ):
                    if key in latest:
                        item[key] = latest[key]
            return item

        rounds = [
            {"name": name, "matches": []}
            for name in ("Quarterfinals", "Semifinals", "Championship")
        ]
        next_chapter = None
        history = []
        for row in rows:
            n = row["number"]
            ri = 0 if n <= 4 else 1 if n <= 6 else 2
            index = n - 1 if n <= 4 else n - 5 if n <= 6 else 0
            match_id = f"r{ri}m{index}"
            try:
                left, right = competitors(conn, tid, row)
            except ValueError:
                left, right = None, None
            win = (
                json.loads(row["simulation"])["winner_id"] if row["completed"] else None
            )
            match = {
                "id": match_id,
                "battle_id": row["id"],
                "left": creature(left),
                "right": creature(right),
                "winner": creature(win),
                "status": "complete" if row["completed"] else "pending",
                "sources": []
                if n <= 4
                else ["r0m0", "r0m1"]
                if n == 5
                else ["r0m2", "r0m3"]
                if n == 6
                else ["r1m0", "r1m1"],
            }
            rounds[ri]["matches"].append(match)
            chapter = conn.execute(
                "SELECT * FROM story_chapters WHERE battle_id=?", (row["id"],)
            ).fetchone()
            if row["completed"]:
                history.append(
                    {
                        "battle_id": row["id"],
                        "number": n,
                        "title": json.loads(chapter["narrative"])["title"]
                        if chapter and chapter["narrative"]
                        else f"Chapter {n}",
                        "prediction": json.loads(row["prediction"])
                        if row["prediction"]
                        else None,
                    }
                )
            if next_chapter is None and not row["completed"] and left and right:
                content = (
                    json.loads(chapter["narrative"])
                    if chapter and chapter["narrative"]
                    else {}
                )
                audio = (
                    json.loads(chapter["audio"])
                    if chapter and chapter["audio"]
                    else None
                )
                prediction = (
                    json.loads(row["prediction"]) if row["prediction"] else None
                )
                if prediction:
                    prediction = {
                        k: v
                        for k, v in prediction.items()
                        if k not in {"actual_winner_id", "correct"}
                    }
                next_chapter = {
                    "battle_id": row["id"],
                    "match_id": match_id,
                    "chapter_number": n,
                    "title": content.get("title", f"Chapter {n}: The challenge awaits"),
                    "paragraphs": content.get("paragraphs", []),
                    "ending": content.get("ending", ""),
                    "participants": [creature(left), creature(right)],
                    "status": chapter["status"] if chapter else "not_started",
                    "audio": audio,
                    "prediction": prediction,
                    "predictions_enabled": prefs["predictions_enabled"],
                    "requested_duration": audio["requested_seconds"]
                    if audio
                    else json.loads(chapter["settings"])["duration_seconds"]
                    if chapter
                    else prefs["duration_seconds"],
                }
        return {
            "id": tid,
            "rounds": rounds,
            "completed": sum(bool(r["completed"]) for r in rows),
            "chapter": next_chapter,
            "champion": rounds[-1]["matches"][0]["winner"],
            "entrant_ids": data["entrant_ids"],
            "seed": data["seed"],
            "shuffle": data["shuffle"],
            "arena": data["arena"],
            "outline": data["outline"],
            "audio_preferences": data.get("audio_preferences"),
            "history": history,
            "created": tournament["created"],
            "version": 1,
        }
