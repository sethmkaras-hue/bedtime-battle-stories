#!/usr/bin/env python3
"""Run a resumable scientific-source import on the home server."""

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import library, main
from app.importer.internet_images import coverage, execute
from app.importer.network import SourceUnavailable, atomic
from app.importer.store import backup, root


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int)
    mode.add_argument("--all", action="store_true")
    mode.add_argument(
        "--coverage",
        action="store_true",
        help="Report actual local image coverage without network requests",
    )
    mode.add_argument(
        "--diagnose-commons",
        action="store_true",
        help="Report endpoint, method, robots rule/status and actual HTTP attempts without app changes",
    )
    p.add_argument(
        "--scientific-name",
        default="Tyrannosaurus",
        help="Scientific name for the diagnostic Commons query",
    )
    p.add_argument(
        "--image-references",
        type=Path,
        help="Local image manifest with saved Commons or licensed-source metadata and original files",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Use supplied references only; make no network requests",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument(
        "--allow-museum-pages",
        action="store_true",
        help="Enable HTML adapters only after reviewing publisher terms and robots policy",
    )
    p.add_argument(
        "--skip-audio",
        action="store_true",
        help="Skip the default verified-only local audio generation step",
    )
    p.add_argument(
        "--generate-audio",
        action="store_true",
        help="Generate only already source-verified pronunciation records after import",
    )
    p.add_argument("--db", type=Path, default=main.DB)
    p.add_argument("--work-dir", type=Path, default=root())
    p.add_argument("--report", type=Path)
    p.add_argument("--pronunciation-index", type=Path)
    p.add_argument(
        "--pronunciation-references",
        type=Path,
        help="Local CSV/JSON sourced guidance or saved-HTML manifest; no source requests",
    )
    p.add_argument(
        "--use-wikidata",
        action="store_true",
        help="Optionally corroborate Commons descriptions with Wikidata/structured depicts",
    )
    p.add_argument(
        "--verbose", action="store_true", help="Print the complete JSON report"
    )
    args = p.parse_args()
    if args.skip_audio and args.generate_audio:
        p.error("Choose --skip-audio or --generate-audio, not both")
    import logging

    args.work_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("app.importer")
    handler = logging.FileHandler(args.work_dir / "import.log")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if args.pilot is not None and not 1 <= args.pilot <= 50:
        p.error("--pilot must be between 1 and 50")
    references = None
    if args.pronunciation_references:
        from app.importer.pronunciation_files import load_references

        try:
            references = load_references(args.pronunciation_references)
        except (ValueError, OSError, SourceUnavailable) as error:
            p.error(str(error))
    images = None
    if args.image_references:
        from app.importer.image_files import load_images

        try:
            images = load_images(args.image_references, private=True)
        except (ValueError, OSError) as error:
            p.error(str(error))
    if args.offline and args.diagnose_commons:
        p.error("--diagnose-commons requires an online policy check; omit --offline")
    if args.diagnose_commons:
        from app.importer.internet_images import discover as search_images
        from app.importer.network import PoliteClient
        from app.importer.sources import COMMONS

        with tempfile.TemporaryDirectory(
            prefix="bedtime-access-diagnostic-"
        ) as temporary:
            client = PoliteClient(temporary, refresh=True)
            errors = []
            try:
                found, errors = search_images(
                    client,
                    {"scientific_name": args.scientific_name, "category": "dinosaur"},
                )
            except (SourceUnavailable, ValueError) as error:
                errors.append(str(error))
                found = []
            finally:
                client.close()
            result = {
                "endpoint": COMMONS,
                "method": "GET",
                "errors": errors,
                "candidate_count": len(found),
                "proposals": [],
                "access_log": list(client.events),
                "http_requests": client.requests,
                "user_agent": client.user_agent,
                "respect_robots": client.respect_robots,
            }
    elif args.coverage:
        if not args.db.is_file():
            p.error("Start the application once to initialize the database")
        result = coverage(args.db)
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
            pilot=args.pilot,
            dry_run=args.dry_run,
            refresh=args.refresh,
            pronunciation_index=index,
            museum_pages=args.allow_museum_pages,
            pronunciation_references=references,
            use_wikidata=args.use_wikidata,
            image_references=images,
            offline=args.offline,
        )
        result["backup_created"] = saved is not None
        if not args.skip_audio and not args.dry_run:
            from app.audio.routes import create_service
            from scripts.generate_pronunciations import generate

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
    if args.verbose or args.coverage or args.diagnose_commons:
        print(json.dumps(result, indent=2))
    else:
        print(
            "Detailed report: "
            + str(args.report or args.work_dir / "latest-report.json")
        )
        print("Detailed diagnostics: " + str(args.work_dir / "import.log"))
    return (
        2
        if not args.dry_run
        and (
            any(
                not row.get("image_available", False)
                for row in result.get("results", [])
            )
            or result.get("pronunciation_generation", {}).get("failed")
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(cli())
