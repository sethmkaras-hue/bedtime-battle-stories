#!/usr/bin/env python3
"""Build original audio from verified guidance. Never download museum recordings."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, library
from app.audio.routes import create_service


def generate(conn, service, provider="kokoro", voice=None, speed=0.8, allow_paid=False):
    if provider == "openai" and not allow_paid:
        raise ValueError(
            "Paid generation needs --allow-paid and explicit server configuration"
        )
    if provider not in {"kokoro", "piper", "openai"}:
        raise ValueError("Choose a local audio-file provider")
    info = service.providers[provider]
    if not info.is_available() and provider in {"kokoro", "piper"}:
        alternate = "piper" if provider == "kokoro" else "kokoro"
        if service.providers[alternate].is_available():
            provider = alternate
            info = service.providers[provider]
            voice = None
    report = {
        "generated": 0,
        "reused": 0,
        "unverified": [],
        "failed": [],
        "provider": provider,
    }
    records = [
        json.loads(r[0])
        for r in conn.execute(
            "SELECT record_json FROM creature_profiles ORDER BY creature_id"
        )
    ]
    for record in records:
        try:
            pron = library.Pronunciation.model_validate(
                record["pronunciation"]
            ).model_dump(mode="json")
        except ValueError as error:
            report["failed"].append(
                {
                    "id": record["id"],
                    "error": "Pronunciation verification metadata is invalid",
                }
            )
            continue
        if pron["status"] != "verified":
            report["unverified"].append(record["id"])
            continue
        try:
            if not info.is_available():
                raise ValueError(info.get_provider_info()["reason"])
            chosen = voice or info.list_voices()[0]["id"]
            # Synthesis identity depends on the verified TTS text, not a display-name rename.
            request = {
                "kind": "pronunciation",
                "provider": provider,
                "voice": chosen,
                "speed": speed,
                "text": pron["tts_text"],
                "overrides": {},
            }
            job = service.submit(request)
            if job.get("fallback"):
                raise ValueError("No configured local engine is ready")
            while job["state"] in {"queued", "generating"}:
                time.sleep(0.1)
                job = service.status(job["key"])
            if job["state"] != "ready":
                raise ValueError(job.get("error", "Generation failed"))
            signature = library.pronunciation_signature(pron)
            metadata = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model_version": info.version(),
                "audio_path": "pronunciation/" + job["key"] + ".wav",
                "text": pron["tts_text"],
                "pronunciation_source": pron["source_url"],
                "metrics": job["metrics"],
            }
            conn.execute(
                "INSERT OR REPLACE INTO pronunciation_assets VALUES (?,?,?,?,?,?,?)",
                (
                    record["id"],
                    signature,
                    job["key"],
                    provider,
                    chosen,
                    speed,
                    json.dumps(metadata),
                ),
            )
            conn.execute(
                "DELETE FROM library_asset_issues WHERE creature_id=? AND kind='pronunciation_audio'",
                (record["id"],),
            )
            conn.commit()
            report["reused" if job["cached"] else "generated"] += 1
        except Exception as error:
            report["failed"].append(
                {
                    "id": record["id"],
                    "error": str(error)
                    if provider != "openai"
                    else type(error).__name__,
                }
            )
    return report


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=main.DB)
    p.add_argument(
        "--provider",
        choices=["kokoro", "piper", "openai"],
        default=os.environ.get("BBS_PRONUNCIATION_PROVIDER", "kokoro"),
    )
    p.add_argument("--voice", default=os.environ.get("BBS_PRONUNCIATION_VOICE"))
    p.add_argument("--speed", type=float, default=0.8)
    p.add_argument("--allow-paid", action="store_true")
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    if not 0.5 <= args.speed <= 2:
        p.error("speed must be between .5 and 2")
    if args.provider == "openai" and not args.allow_paid:
        p.error("OpenAI requires --allow-paid; local audio is the default")
    main.DB = args.db
    main.initialize_database()
    service = create_service()
    try:
        with sqlite3.connect(main.DB) as conn:
            result = generate(
                conn, service, args.provider, args.voice, args.speed, args.allow_paid
            )
    finally:
        service.close()
    text = json.dumps(result, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n")
    print(text)
    return int(bool(result["failed"]))


if __name__ == "__main__":
    raise SystemExit(cli())
