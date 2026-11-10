#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
image_venv="${BBS_IMAGE_VENV:-.venv-images}"
if [ ! -x "$image_venv/bin/python" ]; then
  echo "Run SETUP_CREATURE_IMAGES.sh first; the app's environment is separate." >&2
  exit 1
fi
exec "$image_venv/bin/python" scripts/generate_creature_images.py "$@"
