#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
venv_dir="${BBS_VENV:-.venv}"
if [ ! -x "$venv_dir/bin/python" ]; then
  echo "Create the supported Python environment and install core/media dependencies first." >&2
  exit 1
fi
exec "$venv_dir/bin/python" scripts/import_creature_library.py "$@"
