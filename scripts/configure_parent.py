#!/usr/bin/env python3
"""Set one local parent-review passphrase; never pass it on the command line."""

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.importer.auth import password_record
from app.importer.store import root
from app.importer.network import atomic

if __name__ == "__main__":
    password = getpass.getpass("Parent review passphrase (12+ characters): ")
    if password != getpass.getpass("Repeat passphrase: "):
        raise SystemExit("Passphrases did not match")
    record = password_record(password)
    folder = root()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "parent-auth.json"
    # Restrictive umask also protects the temporary hash file during publication.
    previous = os.umask(0o077)
    try:
        atomic(path, json.dumps(record).encode())
        path.chmod(0o600)
    finally:
        os.umask(previous)
    print(
        "Parent review configured. Restart the app to invalidate existing sessions. No account was created."
    )
