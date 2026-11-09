"""Durable proposals/checkpoints, explicit approvals and consistent SQLite backups."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


def root():
    import os
    from app.library import ROOT

    return Path(os.environ.get("BBS_IMPORT_DIR", ROOT / "data/importer"))


def backup(db):
    db = Path(db)
    if not db.exists():
        return None
    folder = db.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        "library-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
        + ".sqlite3"
    )
    with sqlite3.connect(db) as source, sqlite3.connect(path) as destination:
        source.backup(destination)
    return path


class Store:
    def __init__(self, folder=None, memory=False):
        self.root = Path(folder or root())
        if not memory:
            self.root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            ":memory:" if memory else self.root / "state.sqlite3",
            timeout=10,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        if not memory:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY, stable_key TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(stable_key TEXT PRIMARY KEY,input_hash TEXT NOT NULL,proposal_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS review_events(id INTEGER PRIMARY KEY,proposal_id INTEGER NOT NULL,decision TEXT NOT NULL,created TEXT NOT NULL);
        """)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def checkpoint(self, key, digest):
        return self.conn.execute(
            "SELECT proposal_id FROM checkpoints WHERE stable_key=? AND input_hash=?",
            (key, digest),
        ).fetchone()

    def stage(self, key, digest, payload):
        content = json.dumps(payload, sort_keys=True, ensure_ascii=False)

        # Retrieval timestamps do not alter the identity of otherwise unchanged evidence.
        def stable(value):
            if isinstance(value, dict):
                return {
                    k: stable(v)
                    for k, v in value.items()
                    if k not in {"retrieved_on", "record"}
                }
            if isinstance(value, list):
                return [stable(v) for v in value]
            return value

        fingerprint = hashlib.sha256(
            json.dumps(stable(payload), sort_keys=True).encode()
        ).hexdigest()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO proposals(stable_key,fingerprint,payload,created) VALUES (?,?,?,?)",
                (key, fingerprint, content, datetime.now(timezone.utc).isoformat()),
            )
            pid = self.conn.execute(
                "SELECT id FROM proposals WHERE fingerprint=?", (fingerprint,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)", (key, digest, pid)
            )
        return pid

    def proposals(self, status="pending"):
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE status=? ORDER BY id", (status,)
        ).fetchall()
        return [
            {
                "id": r["id"],
                "stable_key": r["stable_key"],
                "status": r["status"],
                "created": r["created"],
                "proposal": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def get(self, pid):
        row = self.conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None

    def decide(self, pid, decision):
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE proposals SET status=? WHERE id=? AND status='pending'",
                (decision, pid),
            )
            if cursor.rowcount != 1:
                raise ValueError("Proposal is no longer pending")
            self.conn.execute(
                "INSERT INTO review_events(proposal_id,decision,created) VALUES (?,?,?)",
                (pid, decision, datetime.now(timezone.utc).isoformat()),
            )
