#!/usr/bin/env python3
"""Offline import/validate/audit operations. No research or media downloads."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, library


def assert_document(data):
    if set(data) != {"schema_version", "creatures"} or data["schema_version"] != 1:
        raise ValueError(
            "Use the exported schema_version=1 document with a creatures array"
        )


def main_cli():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action", choices=["validate", "import", "audit", "export", "schema"]
    )
    p.add_argument("file", nargs="?", type=Path)
    p.add_argument("--db", type=Path, default=main.DB)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    main.DB = args.db
    if args.action == "schema":
        result = library.CreatureRecord.model_json_schema()
    elif args.action == "validate":
        if not args.file:
            p.error("validate requires a JSON file")
        data = json.loads(args.file.read_text())
        assert_document(data)
        records = library.validate_records(data["creatures"])
        result = {"valid": len(records)}
    else:
        main.initialize_database()
        with sqlite3.connect(main.DB) as conn:
            if args.action == "import":
                if not args.file:
                    p.error("import requires a JSON file")
                data = json.loads(args.file.read_text())
                assert_document(data)
                result = library.import_records(conn, data["creatures"])
            elif args.action == "export":
                result = {
                    "schema_version": 1,
                    "creatures": [
                        json.loads(r[0])
                        for r in conn.execute(
                            "SELECT record_json FROM creature_profiles ORDER BY creature_id"
                        )
                    ],
                }
            else:
                result = library.audit(
                    conn,
                    os.environ.get(
                        "BBS_AUDIO_CACHE", library.ROOT / "data/audio_cache"
                    ),
                )
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
