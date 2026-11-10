#!/usr/bin/env python3
"""Back up/migrate/check persistent chapters without synthesis or network access."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import library
from app.chapters import store
from app.importer.store import backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "migrate", "status", "verify"])
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(
            os.environ.get("BBS_DB_PATH", library.ROOT / "data/creatures.sqlite3")
        ),
    )
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(
            "Database does not exist; confirm --db or initialize a new app first"
        )
    if args.operation == "backup":
        print(backup(args.db))
        return 0
    if args.operation == "migrate":
        saved = backup(args.db)
        store.migrate(args.db, backup_existing=False)
        print(json.dumps({"backup": str(saved), "migration": "complete"}))
        return 0
    with sqlite3.connect(args.db) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='story_settings'"
        ).fetchone():
            print("Legacy database: persistent chapter migration is not installed")
            return 2
        result = {
            "settings": store.settings(conn),
            "tournaments": conn.execute(
                "SELECT COUNT(*) FROM story_tournaments"
            ).fetchone()[0],
            "battles": conn.execute("SELECT COUNT(*) FROM story_battles").fetchone()[0],
            "chapters_by_status": dict(
                conn.execute(
                    "SELECT status,COUNT(*) FROM story_chapters GROUP BY status"
                )
            ),
            "jobs_by_status": dict(
                conn.execute("SELECT status,COUNT(*) FROM story_jobs GROUP BY status")
            ),
        }
        if args.operation == "verify":
            result["audio"] = []
            for bid, revision, raw in conn.execute(
                "SELECT battle_id,revision,audio FROM story_chapter_versions WHERE audio IS NOT NULL"
            ):
                meta = json.loads(raw)
                path = Path(meta["path"]).resolve()
                root = Path(meta["root"]).resolve()
                try:
                    if not path.is_relative_to(root) or path.suffix != ".wav":
                        raise ValueError("Unsafe archive path")
                    if hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
                        raise ValueError("Checksum mismatch")
                    with wave.open(str(path), "rb") as sound:
                        actual = sound.getnframes() / sound.getframerate()
                    result["audio"].append(
                        {
                            "battle_id": bid,
                            "revision": revision,
                            "requested": meta["requested_seconds"],
                            "actual": actual,
                            "provider": meta["provider"],
                            "voice": meta["voice"],
                            "timing_met": abs(actual - meta["requested_seconds"])
                            <= max(2, meta["requested_seconds"] * 0.05),
                        }
                    )
                except (OSError, ValueError, wave.Error) as error:
                    result["audio"].append({"battle_id": bid, "error": str(error)})
    print(json.dumps(result, indent=2))
    return 2 if any("error" in item for item in result.get("audio", [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
