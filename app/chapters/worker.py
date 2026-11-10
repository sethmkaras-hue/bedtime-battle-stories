"""One durable coordinator reuses the bounded AudioService; no models in HTTP handlers."""

import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
import time
import wave
from . import store, narrative

LOG = logging.getLogger(__name__)


def audio_root():
    from app.library import ROOT

    return Path(
        os.environ.get("BBS_CHAPTER_AUDIO", ROOT / "data/chapter_audio")
    ).resolve()


class Coordinator:
    def __init__(self, db, audio, start=True):
        self.db = Path(db)
        self.audio = audio
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=self.run, daemon=True, name="bedtime-chapters"
        )
        if start:
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5)

    def run(self):
        with self.db.with_suffix(".chapter-worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with store.connection(self.db) as conn:
                conn.execute(
                    "UPDATE story_jobs SET status='pending',worker=NULL WHERE status='generating'"
                )
                conn.execute(
                    "UPDATE story_chapters SET status='pending' WHERE status='generating'"
                )
            while not self.stop.is_set():
                try:
                    if not self.once():
                        self.stop.wait(0.3)
                except Exception:
                    LOG.exception("Durable chapter coordinator failed; will retry")
                    self.stop.wait(1)

    def once(self):
        with store.connection(self.db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT * FROM story_jobs WHERE status='pending' ORDER BY created,id LIMIT 1"
            ).fetchone()
            if not job:
                return False
            conn.execute(
                "UPDATE story_jobs SET status='generating',worker=? WHERE id=?",
                (str(os.getpid()), job["id"]),
            )
        try:
            if job["kind"] == "chapter":
                self.chapter(job["target"])
            else:
                from .images import work

                work(self.db, job)
            with store.connection(self.db) as conn:
                conn.execute(
                    "UPDATE story_jobs SET status='ready' WHERE id=?", (job["id"],)
                )
        except InterruptedError:
            with store.connection(self.db) as conn:
                conn.execute(
                    "UPDATE story_jobs SET status='pending',worker=NULL WHERE id=?",
                    (job["id"],),
                )
                if job["kind"] == "chapter":
                    conn.execute(
                        "UPDATE story_chapters SET status='pending' WHERE battle_id=?",
                        (job["target"],),
                    )
        except Exception as error:
            LOG.exception("Job failed kind=%s target=%s", job["kind"], job["target"])
            with store.connection(self.db) as conn:
                conn.execute(
                    "UPDATE story_jobs SET status='failed',error=? WHERE id=?",
                    (str(error)[:1000], job["id"]),
                )
                if job["kind"] == "chapter":
                    conn.execute(
                        "UPDATE story_chapters SET status='failed',error=?,updated=? WHERE battle_id=?",
                        (str(error)[:1000], store.now(), job["target"]),
                    )
                    previous = conn.execute(
                        "SELECT narrative,audio FROM story_chapter_versions WHERE battle_id=? AND audio IS NOT NULL ORDER BY revision DESC LIMIT 1",
                        (job["target"],),
                    ).fetchone()
                    if previous:
                        conn.execute(
                            "UPDATE story_chapters SET narrative=?,audio=?,status='ready' WHERE battle_id=?",
                            (previous["narrative"], previous["audio"], job["target"]),
                        )
        return True

    def synthesize(self, request):
        from app.audio.service import QueueFull

        deadline = time.monotonic() + 1800
        while True:
            if self.stop.is_set():
                raise InterruptedError()
            try:
                result = self.audio.submit(request)
                break
            except QueueFull:
                if time.monotonic() > deadline:
                    raise RuntimeError("Local audio queue remained busy")
                self.stop.wait(0.3)
        if result.get("fallback"):
            raise RuntimeError(
                "Local narration is unavailable: "
                + result.get("reason", "model not ready")
            )
        while result["state"] in ("queued", "generating"):
            if self.stop.wait(0.2):
                raise InterruptedError()
            if time.monotonic() > deadline:
                raise RuntimeError("Local narration timed out")
            result = self.audio.status(result["key"])
            if not result:
                raise RuntimeError("Narration job disappeared; retry safely")
        if result["state"] != "ready":
            raise RuntimeError(
                "Local narration failed; retry after checking audio setup"
            )
        return result

    def chapter(self, bid):
        with store.connection(self.db) as conn:
            row = conn.execute(
                "SELECT * FROM story_battles WHERE id=?", (bid,)
            ).fetchone()
            chapter = conn.execute(
                "SELECT * FROM story_chapters WHERE battle_id=?", (bid,)
            ).fetchone()
            if chapter and chapter["status"] == "ready":
                return  # Crash after publication: never regenerate a completed version.
            if not row or not row["simulation"]:
                raise ValueError("Simulation must be persisted before narration")
            tournament = json.loads(
                conn.execute(
                    "SELECT data FROM story_tournaments WHERE id=?",
                    (row["tournament_id"],),
                ).fetchone()[0]
            )
            previous = []
            for p in conn.execute(
                "SELECT b.number,b.simulation,c.narrative FROM story_battles b JOIN story_chapters c ON c.battle_id=b.id WHERE b.tournament_id=? AND b.number<? AND b.completed IS NOT NULL ORDER BY b.number",
                (row["tournament_id"], row["number"]),
            ):
                content = json.loads(p["narrative"]) if p["narrative"] else {}
                winner = json.loads(p["simulation"])["winner_id"]
                previous.append(
                    {
                        "chapter_number": p["number"],
                        "winner_name": tournament["snapshots"][str(winner)]["name"],
                        "summary": content.get("summary", ""),
                        "key_events": content.get("key_events", []),
                    }
                )
            prefs = json.loads(chapter["settings"])
            sim = json.loads(row["simulation"])
            left = tournament["snapshots"][str(row["left_id"])]
            right = tournament["snapshots"][str(row["right_id"])]
            calibration_key = json.dumps(prefs["audio"], sort_keys=True)
            calibration = conn.execute(
                "SELECT words_per_second FROM story_tts_calibration WHERE identity=?",
                (calibration_key,),
            ).fetchone()
            initial_words = (
                round(calibration[0] * prefs["duration_seconds"])
                if calibration
                else None
            )
            content = (
                json.loads(chapter["narrative"])
                if chapter["narrative"]
                else narrative.generate(
                    left,
                    right,
                    sim,
                    row["number"],
                    tournament["outline"],
                    previous,
                    prefs,
                    words=initial_words,
                    variant=chapter["revision"] - 1,
                )
            )
            conn.execute(
                "UPDATE story_chapters SET status='generating',narrative=?,updated=? WHERE battle_id=?",
                (json.dumps(content), store.now(), bid),
            )
        configured = prefs["audio"]
        provider = configured["provider"]
        voice = configured["voice"]
        speed = configured["speed"]
        # No automatic paid synthesis. Device speech is a disclosed, unmeasured
        # playback fallback, never reported as calibrated local audio.
        if provider not in ("kokoro", "piper"):
            raise RuntimeError(
                "Select a local Kokoro or Piper voice for timed narration"
            )
        best = None
        attempts = []
        target = prefs["duration_seconds"]
        tolerance = max(2, target * 0.05)
        overrides = {
            c["name"]: c["profile"]["pronunciation"]["tts_text"]
            for c in (left, right)
            if (c.get("profile") or {}).get("pronunciation", {}).get("status")
            == "verified"
        }
        for attempt in range(3):
            text = "\n\n".join([*content["paragraphs"], content["ending"]])
            try:
                result = self.synthesize(
                    {
                        "kind": "narration",
                        "provider": provider,
                        "voice": voice,
                        "speed": speed,
                        "text": text,
                        "overrides": overrides,
                    }
                )
                path, _ = self.audio._paths("narration", result["key"])
                with wave.open(str(path), "rb") as wav:
                    actual = wav.getnframes() / wav.getframerate()
                if actual <= 0:
                    raise ValueError("Empty narration audio")
                actual_provider = result.get("metrics", {}).get("provider", provider)
                actual_voice = voice
                if actual_provider != provider:
                    actual_voice = self.audio.providers[actual_provider].list_voices()[
                        0
                    ]["id"]
                metadata = {
                    "requested_seconds": target,
                    "actual_seconds": actual,
                    "provider": actual_provider,
                    "voice": actual_voice,
                    "speaking_rate": speed,
                    "source_key": result["key"],
                    "generated_at": store.now(),
                    "timing_met": abs(actual - target) <= tolerance,
                    "generation_status": "ready",
                }
                attempts.append(
                    {
                        "attempt": attempt + 1,
                        "words": len(text.split()),
                        "actual_seconds": actual,
                    }
                )
                if best is None or abs(actual - target) < abs(
                    best[1]["actual_seconds"] - target
                ):
                    best = (content, metadata, path)
                if metadata["timing_met"]:
                    break
                words = max(30, min(220, round(len(text.split()) * target / actual)))
                content = narrative.generate(
                    left,
                    right,
                    sim,
                    row["number"],
                    tournament["outline"],
                    previous,
                    prefs,
                    words=words,
                    variant=chapter["revision"] - 1,
                )
            except InterruptedError:
                raise
            except Exception as error:
                attempts.append({"attempt": attempt + 1, "error": str(error)[:400]})
                if best:
                    break
                if attempt == 2:
                    raise
        if best is None:
            raise RuntimeError("No valid local narration")
        content, metadata, source = best
        # Historical narration is archived independently of the clearable cache.
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        folder = audio_root()
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / (digest + ".wav")
        from app.importer.network import atomic

        if (
            not destination.is_file()
            or hashlib.sha256(destination.read_bytes()).hexdigest() != digest
        ):
            atomic(destination, data)
        metadata.update(
            path=str(destination),
            root=str(folder),
            sha256=digest,
            attempts=attempts,
            url=f"/api/story/audio/{bid}/{digest}",
        )
        with store.connection(self.db) as conn:
            conn.execute(
                "UPDATE story_chapters SET narrative=?,audio=?,status='ready',error=NULL,updated=? WHERE battle_id=?",
                (json.dumps(content), json.dumps(metadata), store.now(), bid),
            )
            latest_tournament = json.loads(
                conn.execute(
                    "SELECT data FROM story_tournaments WHERE id=?",
                    (row["tournament_id"],),
                ).fetchone()[0]
            )
            if latest_tournament.get("audio_preferences") == configured:
                latest_tournament["audio_preferences"] = {
                    "provider": metadata["provider"],
                    "voice": metadata["voice"],
                    "speed": metadata["speaking_rate"],
                }
                conn.execute(
                    "UPDATE story_tournaments SET data=? WHERE id=?",
                    (json.dumps(latest_tournament), row["tournament_id"]),
                )
            spoken = " ".join([*content["paragraphs"], content["ending"]])
            observed = len(spoken.split()) / metadata["actual_seconds"]
            conn.execute(
                "INSERT INTO story_tts_calibration VALUES(?,?,1) ON CONFLICT(identity) DO UPDATE SET words_per_second=(words_per_second*3+excluded.words_per_second)/4,samples=samples+1",
                (
                    json.dumps(
                        {
                            "provider": metadata["provider"],
                            "voice": metadata["voice"],
                            "speed": metadata["speaking_rate"],
                        },
                        sort_keys=True,
                    ),
                    observed,
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO story_chapter_versions VALUES(?,?,?,?,?)",
                (
                    bid,
                    chapter["revision"],
                    json.dumps(content),
                    json.dumps(metadata),
                    store.now(),
                ),
            )
