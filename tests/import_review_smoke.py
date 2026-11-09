"""Real-browser parent gate with a synthetic local proposal and disposable server."""

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import httpx
from playwright.sync_api import sync_playwright
from app.importer.auth import password_record
from app.importer.store import Store


def run():
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bedtime-parent-browser-") as tmp:
        folder = Path(tmp)
        state = folder / "importer"
        state.mkdir()
        (state / "parent-auth.json").write_text(
            json.dumps(password_record("fixture-parent-passphrase"))
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "BBS_DB_PATH": str(folder / "app.sqlite3"),
            "BBS_IMPORT_DIR": str(state),
            "BBS_AUDIO_CACHE": str(folder / "cache"),
            "BBS_MODEL_DIR": str(folder / "no-models"),
        }
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=project,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(base + "/api/config", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Disposable test server did not start")
            with sqlite3.connect(folder / "app.sqlite3") as conn:
                record = json.loads(
                    conn.execute(
                        "SELECT record_json FROM creature_profiles ORDER BY creature_id LIMIT 1"
                    ).fetchone()[0]
                )
            store = Store(state)
            pid = store.stage(
                record["stable_key"],
                "fixture",
                {
                    "stable_key": record["stable_key"],
                    "display_name": "Synthetic parent-review fixture",
                    "scientific_name": record["scientific_name"],
                    "record": record,
                    "science": {"time_period": "Synthetic fixture period"},
                    "evidence": [
                        {
                            "id": "fixture",
                            "title": "Synthetic fixture, not an actual citation",
                            "url": "https://example.test/source",
                            "supports": ["time_period"],
                        }
                    ],
                    "images": [
                        {
                            "title": "Synthetic unresolved image",
                            "description": "Synthetic caption, not real research",
                            "identity_evidence": "Fixture identity evidence",
                            "acquisition": "supplied_image",
                            "source_kind": "licensed_reference",
                            "supported": False,
                            "issues": ["Awaiting exact identity research"],
                        }
                    ],
                    "pronunciation": {
                        "phonetic": "fixture-GUIDE",
                        "stress": "GUIDE",
                        "tts_text": "fixture guide",
                        "source_url": "https://example.test/reference",
                        "acquisition": "supplied_reference",
                        "publisher": "Synthetic educational fixture",
                        "retrieved_on": "2026-11-01",
                        "source_verification": {"status": "unverified"},
                        "alternatives": ["Fixture alternate"],
                    },
                    "issues": [],
                    "stage": "imported_candidates",
                },
            )
            store.close()
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.environ.get(
                        "CHROMIUM_PATH", "/usr/bin/chromium"
                    ),
                    args=["--no-sandbox"],
                )
                page = browser.new_page(
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                    has_touch=True,
                )
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(base)
                page.locator("#settings-open").click()
                page.locator("#open-parent-review").click()
                page.locator("#parent-locked").wait_for(state="visible")
                assert page.locator("#parent-unlocked").is_hidden()
                page.locator("#parent-password").fill("fixture-parent-passphrase")
                page.locator("#parent-login button").click()
                page.locator(".parent-proposal").wait_for()
                card = page.locator(".parent-proposal").first
                assert "Synthetic educational fixture" in card.inner_text()
                assert "Fixture alternate" in card.inner_text()
                assert "Fixture identity evidence" in card.inner_text()
                card.locator("input[data-scope=science]").check()
                card.locator("input[type=checkbox]").last.check()
                card.get_by_role("button", name="Approve inspected updates").click()
                page.wait_for_function(
                    "document.getElementById('parent-review-message').textContent.includes('Run IMPORT_CREATURE_LIBRARY')"
                )
                page.locator(".parent-proposal").wait_for(state="detached")
                page.locator("#parent-logout").click()
                page.locator("#parent-locked").wait_for(state="visible")
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert not errors, errors
                browser.close()
            with sqlite3.connect(folder / "app.sqlite3") as conn:
                reviewed = json.loads(
                    conn.execute(
                        "SELECT record_json FROM creature_profiles WHERE creature_id=?",
                        (record["id"],),
                    ).fetchone()[0]
                )
                assert (
                    reviewed["time_period"] == "Synthetic fixture period"
                    and reviewed["verification_status"] == "unverified"
                )
            print(
                "Parent mobile review passed: password gate, same-origin session/CSRF, deliberate approval, partial-review status and logout"
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    run()
