"""Single parent credential, short-lived sessions and CSRF. No user accounts."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time


def password_record(password):
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a parent passphrase of at least 12 characters")
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=16384,
        r=8,
        p=1,
        maxmem=64 * 1024 * 1024,
    ).hex()
    return {"salt": salt, "digest": value}


class ParentAuth:
    def __init__(self, folder, clock=time.time):
        self.path = Path(folder) / "parent-auth.json"
        self.clock = clock
        self.sessions = {}
        self.attempts = {}
        self.lock = threading.RLock()

    def configured(self):
        return self.path.is_file()

    def login(self, password, ip):
        with self.lock:
            now = self.clock()
            self.attempts = {
                k: v for k, v in self.attempts.items() if now - v["start"] < 600
            }
            state = self.attempts.setdefault(ip, {"start": now, "failures": 0})
            if state["failures"] >= 5:
                raise PermissionError("Too many attempts. Try again in ten minutes.")
            if len(self.attempts) > 1024:
                raise PermissionError("Parent login is temporarily busy")
            try:
                saved = json.loads(self.path.read_text())
                actual = hashlib.scrypt(
                    password.encode(),
                    salt=bytes.fromhex(saved["salt"]),
                    n=16384,
                    r=8,
                    p=1,
                    maxmem=64 * 1024 * 1024,
                ).hex()
                valid = hmac.compare_digest(actual, saved["digest"])
            except (OSError, ValueError, KeyError):
                valid = False
            if not valid:
                state["failures"] += 1
                return None
            state["failures"] = 0
            self.sessions = {
                k: v for k, v in self.sessions.items() if v["expires"] > now
            }
            if len(self.sessions) >= 32:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            self.sessions[token] = {
                "csrf": csrf,
                "expires": now + 900,
                "credential_version": self.path.stat().st_mtime_ns,
            }
            return token, csrf

    def session(self, token):
        with self.lock:
            session = self.sessions.get(token or "")
            try:
                version = self.path.stat().st_mtime_ns
            except OSError:
                version = None
            if (
                session
                and session["expires"] > self.clock()
                and session["credential_version"] == version
            ):
                return session
            self.sessions.pop(token or "", None)
            return None

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token or "", None)
