#!/usr/bin/env python3
"""Generate cached original illustrations on CPU, independently of FastAPI."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.images import core
from app.images.hardware import hardware


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pilot", type=int)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--creature")
    mode.add_argument("--pending", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="Persist the selected batch for a managed worker without starting inference",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(
            os.environ.get("BBS_DB_PATH", core.ROOT / "data/creatures.sqlite3")
        ),
    )
    parser.add_argument("--steps", type=int)
    parser.add_argument("--resolution", type=int)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--guidance", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(hardware(), indent=2))
        return 0
    if not (args.pending or args.pilot or args.all or args.creature or args.resume):
        parser.error("Choose --pilot, --all, --creature or --resume")
    if args.pilot is not None and not 1 <= args.pilot <= 50:
        parser.error("--pilot must be between 1 and 50")
    if not args.db.is_file():
        parser.error("Start the application once to initialize the creature database")
    if not args.pending:
        settings = core.defaults()
        for arg, key in [
            ("steps", "steps"),
            ("resolution", "resolution"),
            ("threads", "threads"),
            ("guidance", "guidance"),
            ("seed", "base_seed"),
        ]:
            if getattr(args, arg) is not None:
                settings[key] = getattr(args, arg)
        if args.output_dir:
            settings["output_dir"] = str(args.output_dir.resolve())
        chosen = core.records(args.db)
        if args.creature:
            chosen = [
                r
                for r in chosen
                if args.creature.casefold()
                in {r["display_name"].casefold(), r["scientific_name"].casefold()}
            ]
            if len(chosen) != 1:
                parser.error(
                    "--creature must match exactly one display/scientific name"
                )
        elif args.pilot:
            chosen = sorted(
                (r for r in chosen if r["category"] == "dinosaur"),
                key=lambda r: (
                    core.PILOT.index(r["display_name"])
                    if r["display_name"] in core.PILOT
                    else 1000,
                    r["id"],
                ),
            )[: args.pilot]
        elif args.resume and not args.all:
            chosen = []
        if chosen:
            print(json.dumps(core.enqueue(args.db, chosen, settings, args.force)))
        if args.resume:
            core.retry_failed(args.db)
        print(
            f"CREATURE IMAGE GENERATION\nModel: {settings['model']} at {settings['revision']}\nDevice: CPU\nResolution: {settings['resolution']}x{settings['resolution']}"
        )
    if args.enqueue_only:
        print("Batch queued persistently; start the managed worker or use --resume.")
        return 0
    report = core.worker(args.db)
    print(json.dumps(report, indent=2))
    return (
        130
        if report.get("interrupted")
        else 3
        if report.get("halted")
        else 2
        if report["failed"]
        else 0
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
