#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
runtime="${BBS_PYTHON:-python3}"
venv_dir="${BBS_VENV:-.venv}"
if [ ! -d "$venv_dir" ]; then "$runtime" -m venv "$venv_dir"; fi
if [ ! -x "$venv_dir/bin/python" ]; then
  echo "The virtual environment is broken. Preserve/move $venv_dir and recreate it with $runtime -m venv before restarting." >&2
  exit 1
fi
expected="$("$runtime" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}{sys.abiflags}")')"
actual="$("$venv_dir/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}{sys.abiflags}")')"
if [ "$expected" != "$actual" ]; then
  echo "Python mismatch: $runtime is $expected but $venv_dir is $actual. Preserve/move the old virtual environment and recreate it, or select its matching BBS_PYTHON. Creature data, models and audio cache must be kept." >&2
  exit 1
fi
"$venv_dir/bin/python" -m pip install -r requirements.txt
if [ "${BBS_SAMPLE_DATA:-0}" = 1 ]; then
  export BBS_DB_PATH="${BBS_DB_PATH:-$PWD/data/sample.sqlite3}"
fi
exec "$venv_dir/bin/python" -m uvicorn app.main:app --host "${BBS_HOST:-0.0.0.0}" --port "${BBS_PORT:-8502}"
