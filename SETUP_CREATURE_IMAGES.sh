#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
image_venv="${BBS_IMAGE_VENV:-.venv-images}"
image_python="${BBS_IMAGE_PYTHON:-python3.12}"
if [ ! -x "$image_venv/bin/python" ]; then
  if ! command -v "$image_python" >/dev/null; then
    echo "Install Python 3.12 plus venv support, or set BBS_IMAGE_PYTHON to a Python 3.12 interpreter. The app stays on 3.14." >&2
    exit 1
  fi
  "$image_python" -m venv "$image_venv"
fi
"$image_venv/bin/python" -c 'import sys; assert sys.version_info[:2] == (3,12), "Use a separate Python 3.12 image environment"'
"$image_venv/bin/python" -m pip install 'torch==2.7.1+cpu' --index-url https://download.pytorch.org/whl/cpu
"$image_venv/bin/python" -m pip install -r requirements-images.txt
exec "$image_venv/bin/python" scripts/setup_creature_images.py "$@"
