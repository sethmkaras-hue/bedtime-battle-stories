"""On-demand local spoken names, kept distinct from verified source guidance."""

import hashlib
import json
import wave
from pathlib import Path

from app import library

from . import store


def recipe(record):
    pron = record["pronunciation"]
    verified = pron.get("status") == "verified" and pron.get("tts_text")
    text = pron["tts_text"] if verified else record["display_name"]
    basis = "verified_guidance" if verified else "synthesized_display_name"
    signature = hashlib.sha256(
        json.dumps(
            {"text": text, "basis": basis, "source": pron if verified else None},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return text, basis, signature


def valid(path, metadata):
    try:
        with wave.open(str(path), "rb") as sound:
            if sound.getnframes() <= 0:
                return False
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() == metadata["sha256"]
    except (OSError, ValueError, EOFError, wave.Error, KeyError):
        return False


def options(conn, cid, record, root):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='spoken_name_assets'"
    ).fetchone():
        return []
    _, _, signature = recipe(record)
    result = []
    for row in conn.execute(
        "SELECT cache_key,provider,voice,speed,metadata FROM spoken_name_assets WHERE creature_id=? AND signature=? ORDER BY created DESC",
        (cid, signature),
    ):
        key, provider, voice, speed, raw = row
        metadata = json.loads(raw)
        path = Path(root) / "pronunciation" / (key + ".wav")
        if valid(path, metadata):
            result.append(
                {
                    "url": f"/api/library/pronunciations/{cid}/{key}",
                    "provider": provider,
                    "voice": voice,
                    "speed": speed,
                    "metadata": metadata,
                }
            )
    return result


def prepare(db, cid, prefs, service):
    from .images import current_record

    record = current_record(db, cid)
    text, _basis, signature = recipe(record)
    if not text.strip() or len(text) > 200:
        raise ValueError("Creature name is empty or too long for local playback")
    with store.connection(db) as conn:
        old = library.audio_options(conn, cid, record, service.root) + options(
            conn, cid, record, service.root
        )
        for asset in old:
            if (
                asset["provider"] == prefs["provider"]
                and asset["voice"] == prefs["voice"]
                and asset["speed"] == prefs["speed"]
            ) or asset["metadata"].get("requested_preferences") == prefs:
                return {"status": "ready", "asset": asset}
        identity = hashlib.sha256(
            json.dumps({"signature": signature, **prefs}, sort_keys=True).encode()
        ).hexdigest()
        jid = store.enqueue(
            conn,
            "spoken_name",
            str(cid) + ":" + identity,
            {"creature_id": cid, "signature": signature, "preferences": prefs},
        )
    return {"status": "pending", "job_id": jid}


def work(db, job, coordinator):
    from .images import current_record

    payload = json.loads(job["payload"])
    cid = payload["creature_id"]
    prefs = payload["preferences"]
    record = current_record(db, cid)
    text, basis, signature = recipe(record)
    if signature != payload["signature"]:
        raise ValueError("The creature name changed; tap again for its current name")
    result = coordinator.synthesize(
        {"kind": "pronunciation", "text": text, **prefs, "overrides": {}}
    )
    path, _ = coordinator.audio._paths("pronunciation", result["key"])
    actual = result["metrics"].get("provider", prefs["provider"])
    voice = (
        prefs["voice"]
        if actual == prefs["provider"]
        else coordinator.audio.providers[actual].list_voices()[0]["id"]
    )
    metadata = {
        "text": text,
        "basis": basis,
        "verified_pronunciation": basis == "verified_guidance",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "requested_preferences": prefs,
        "metrics": result["metrics"],
        "generated_at": store.now(),
    }
    if not valid(path, metadata):
        raise ValueError("Generated spoken-name audio is invalid")
    with store.connection(db) as conn:
        current = json.loads(
            conn.execute(
                "SELECT record_json FROM creature_profiles WHERE creature_id=?", (cid,)
            ).fetchone()[0]
        )
        if recipe(current)[2] != signature:
            raise ValueError("Creature name changed during synthesis")
        conn.execute(
            "INSERT OR REPLACE INTO spoken_name_assets VALUES(?,?,?,?,?,?,?,?)",
            (
                cid,
                signature,
                result["key"],
                actual,
                voice,
                prefs["speed"],
                json.dumps(metadata),
                store.now(),
            ),
        )
        conn.execute(
            "DELETE FROM library_asset_issues WHERE creature_id=? AND kind='pronunciation_audio'",
            (cid,),
        )
        conn.execute(
            "UPDATE story_jobs SET payload=? WHERE id=?",
            (
                json.dumps(
                    {
                        **payload,
                        "asset": {
                            "url": f"/api/library/pronunciations/{cid}/{result['key']}",
                            "provider": actual,
                            "voice": voice,
                            "speed": prefs["speed"],
                            "metadata": metadata,
                        },
                    }
                ),
                job["id"],
            ),
        )
