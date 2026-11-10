"""Mobile persistent seven-chapter flow and image history, with mocked costly services."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from playwright.sync_api import sync_playwright
from app.importer.auth import password_record


def run():
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bedtime-chapters-browser-") as temp:
        root = Path(temp)
        (root / "importer").mkdir()
        (root / "importer/parent-auth.json").write_text(
            json.dumps(password_record("fixture-parent-passphrase"))
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "BBS_DB_PATH": str(root / "app.sqlite3"),
            "BBS_IMPORT_DIR": str(root / "importer"),
            "BBS_AUDIO_CACHE": str(root / "audio"),
            "BBS_MODEL_DIR": str(root / "models"),
            "BBS_CHAPTER_AUDIO": str(root / "chapters"),
            "BBS_CREATURE_IMAGE_DIR": str(root / "images"),
            "BBS_SAMPLE_DATA": "0",
            "BBS_CATALOG": "1",
        }
        server = subprocess.Popen(
            [sys.executable, "tests/chapter_browser_server.py", str(port)],
            cwd=project,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=(root / "server.log").open("w"),
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    if httpx.get(base + "/api/config").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError((root / "server.log").read_text())
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path="/usr/bin/chromium", args=["--no-sandbox"]
                )
                page = browser.new_page(
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                    has_touch=True,
                )
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.add_init_script(
                    "Object.defineProperty(crypto, 'randomUUID', {value: undefined})"
                )
                page.goto(base)
                page.locator("#start-adventure").click()
                page.locator("[data-category=dinosaur]").click()
                page.locator("#random").click()
                page.wait_for_function("selected.length===8")
                page.locator("#next").click()
                page.locator("#bracket").wait_for(state="visible")
                tid = page.evaluate("current.id")
                assert tid
                for number in range(1, 8):
                    page.locator("#story").click()
                    page.locator("#prediction").wait_for(state="visible")
                    assert page.locator("#prediction-choices button").count() == 2
                    if number == 1:
                        page.locator("#prediction-choices button").first.click()
                    else:
                        page.locator("#prediction-skip").click()
                    page.locator("#player").wait_for(state="visible")
                    page.wait_for_function(
                        "!audio.generating && !document.getElementById('finish').disabled"
                    )
                    assert (
                        "winner"
                        not in page.locator("#chapter-text").inner_text().lower()
                    )
                    assert (
                        page.locator("#story-audio")
                        .get_attribute("src")
                        .startswith("/api/story/audio/")
                    )
                    assert page.evaluate("current.completed") == number - 1
                    if number == 1:
                        page.locator("#play").click()
                        page.wait_for_function("!audio.audio.paused")
                        page.locator("#pause").click()
                        assert page.evaluate("audio.audio.paused")
                        page.locator("#replay").click()
                        page.wait_for_function("!audio.audio.paused")
                        page.locator("#story-audio").dispatch_event("ended")
                    else:
                        page.locator("#finish").click()
                    page.locator("#chapter-reveal").wait_for(state="visible")
                    assert page.evaluate("current.completed") == number
                    if number == 1:
                        assert page.locator("#prediction-response").inner_text() in (
                            "You guessed it!",
                            "What an amazing battle!",
                        )
                    page.locator("#next-chapter").click()
                page.locator("#celebration").wait_for(state="visible")
                page.reload()
                page.locator("#continue-adventure").wait_for(state="visible")
                page.locator("#continue-adventure").click()
                assert (
                    page.evaluate("current.id") == tid
                    and page.evaluate("current.completed") == 7
                )
                page.locator("#view-bracket").click()
                page.locator("#rounds button").filter(
                    has_text="Replay chapter"
                ).first.click()
                page.locator("#player").wait_for(state="visible")
                page.wait_for_function("!audio.generating")
                assert page.locator("#prediction").is_hidden()
                prior_prediction = page.evaluate("current.history[0].prediction")
                page.locator("#story-audio").dispatch_event("ended")
                page.locator("#chapter-reveal").wait_for(state="visible")
                assert page.locator("#prediction-response").inner_text() == (
                    "You guessed it!"
                    if prior_prediction["correct"]
                    else "What an amazing battle!"
                )
                page.locator("#next-chapter").click()
                page.locator("#bracket").wait_for(state="visible")
                assert page.evaluate("current.completed") == 7
                page.locator("#settings-open").click()
                page.locator("#adult-password").fill("fixture-parent-passphrase")
                page.locator("#adult-unlock").click()
                page.locator("#adult-tools").wait_for(state="visible")
                page.locator("#battle-duration").select_option("20")
                page.locator("#save-battle-settings").click()
                page.wait_for_function(
                    "document.getElementById('adult-status').textContent.includes('Saved.')"
                )
                assert (
                    httpx.get(base + "/api/story/settings").json()["duration_seconds"]
                    == 20
                )
                page.locator("#creature-image-manager summary").click()
                page.locator("#manage-creature-search").fill("Diplodocus")
                page.wait_for_function(
                    "document.getElementById('manage-creature').options.length===1"
                )
                page.locator("#manage-scientific-search").click()
                page.wait_for_function(
                    "document.querySelectorAll('#manage-image-candidates article').length===20",
                    timeout=30000,
                )
                page.locator("#manage-image-candidates button").first.click()
                page.wait_for_function(
                    "document.getElementById('manage-image-status').textContent.includes('Image installed')",
                    timeout=30000,
                )
                page.locator("#manage-current-image img").evaluate(
                    "image=>image.decode()"
                )
                installed = page.locator("#manage-current-image img").get_attribute(
                    "src"
                )
                assert "/api/library/images/" in installed
                assert page.locator("#manage-image-history button").count() == 2
                page.locator("#manage-image-history button").filter(
                    has_text="Restore"
                ).click()
                page.wait_for_function(
                    "!document.querySelector('#manage-current-image img').getAttribute('src').includes('/api/library/images/')"
                )
                assert httpx.get(base + installed).status_code == 200
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert not errors, errors
                browser.close()
            # Restart the real app process against the same temporary database.
            server.terminate()
            server.wait(timeout=15)
            server = subprocess.Popen(
                [sys.executable, "tests/chapter_browser_server.py", str(port)],
                cwd=project,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(100):
                try:
                    result = httpx.get(base + "/api/story/tournaments/" + tid)
                    if result.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            assert result.json()["completed"] == 7
            assert (
                httpx.get(base + "/api/story/settings").json()["duration_seconds"] == 20
            )
            print(
                "Mobile persistent chapters passed: predictions, seven reveals, replay/restart, measured WAV playback, adult settings and targeted image replace/restore"
            )
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    run()
