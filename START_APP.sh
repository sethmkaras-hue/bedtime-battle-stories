#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
if [ "${BBS_SAMPLE_DATA:-0}" = 1 ]; then
  export BBS_DB_PATH="${BBS_DB_PATH:-$PWD/data/sample.sqlite3}"
fi
exec .venv/bin/python -m uvicorn app.main:app --host "${BBS_HOST:-0.0.0.0}" --port "${BBS_PORT:-8502}"
