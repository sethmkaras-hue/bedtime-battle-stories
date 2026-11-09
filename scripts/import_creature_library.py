#!/usr/bin/env python3
"""Run a resumable scientific-source import on the home server."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, library
from app.importer.runner import execute
from app.importer.store import Store, root, backup
from app.importer.network import atomic, SourceUnavailable


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--review", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument(
        "--allow-museum-pages",
        action="store_true",
        help="Enable HTML adapters only after reviewing publisher terms and robots policy",
    )
    p.add_argument(
        "--propose-only",
        action="store_true",
        help="Do not apply even exact source-supported facts",
    )
    p.add_argument(
        "--skip-audio",
        action="store_true",
        help="Skip the default verified-only local audio generation step",
    )
    p.add_argument(
        "--generate-audio",
        action="store_true",
        help="Generate only already parent-verified pronunciation records after import",
    )
    p.add_argument("--db", type=Path, default=main.DB)
    p.add_argument("--work-dir", type=Path, default=root())
    p.add_argument("--report", type=Path)
    p.add_argument("--pronunciation-index", type=Path)
    p.add_argument(
        "--pronunciation-references",
        type=Path,
        help="Local JSON manifest containing sourced guidance or saved HTML references; no source requests",
    )
    p.add_argument(
        "--use-wikidata",
        action="store_true",
        help="Optionally corroborate Commons descriptions with Wikidata/structured depicts",
    )
    args = p.parse_args()
    if args.pilot is not None and not 1 <= args.pilot <= 50:
        p.error("--pilot must be between 1 and 50")
    references = None
    if args.pronunciation_references:
        from app.importer.pronunciation_files import load_references

        try:
            references = load_references(args.pronunciation_references)
        except (ValueError, OSError, SourceUnavailable) as error:
            p.error(str(error))
    if args.review:
        store = Store(args.work_dir)
        try:
            result = {"pending": store.proposals()}
        finally:
            store.close()
    else:
        if args.dry_run and not args.db.exists():
            p.error(
                "Dry run requires an existing initialized database; start the app first"
            )
        saved = None
        if not args.dry_run:
            saved = backup(args.db)
            main.DB = args.db
            main.initialize_database()
        index = (
            json.loads(args.pronunciation_index.read_text())
            if args.pronunciation_index
            else None
        )
        result = execute(
            args.db,
            args.work_dir,
            args.pilot,
            args.all,
            args.dry_run,
            args.refresh,
            not args.propose_only,
            pronunciation_index=index,
            museum_pages=args.allow_museum_pages,
            pronunciation_references=references,
            use_wikidata=args.use_wikidata,
        )
        result["backup_created"] = saved is not None
        if not args.skip_audio and not args.dry_run:
            from scripts.generate_pronunciations import generate
            from app.audio.routes import create_service

            service = create_service()
            try:
                with sqlite3.connect(args.db) as conn:
                    result["pronunciation_generation"] = generate(conn, service)
                    result["audit"] = library.audit(conn, service.root)
            finally:
                service.close()
        if not args.dry_run:
            atomic(
                args.work_dir / "latest-report.json",
                json.dumps(result, indent=2).encode(),
            )
    if args.report:
        atomic(args.report, json.dumps(result, indent=2).encode())
    print(json.dumps(result, indent=2))
    # Missing sources are a usable review result, but never a successful full import.
    if not args.review and (
        result["errors"]
        or result.get("pending_review", 0)
        or any(r["issues"] for r in result["proposals"])
        or result.get("pronunciation_generation", {}).get("failed")
    ):
        print(
            "Import completed with unresolved source/review issues; inspect the report and parent queue.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
