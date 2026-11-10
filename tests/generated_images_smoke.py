"""Actual FastAPI/UI transport for a mock-generated image; no model inference."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from app.images import core
from app.importer.auth import password_record


class Fixture:
    def __init__(self, settings):
        pass

    def generate(self, settings, destination, *args):
        image = Image.new("RGB", (512, 512), "navy")
        ImageDraw.Draw(image).ellipse((90, 90, 420, 420), fill="purple")
        image.save(destination, format="PNG")

    def close(self):
        pass


def run():
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bedtime-generated-browser-") as temporary:
        folder = Path(temporary)
        db = folder / "app.sqlite3"
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
            "BBS_DB_PATH": str(db),
            "BBS_IMPORT_DIR": str(state),
            "BBS_AUDIO_CACHE": str(folder / "audio"),
            "BBS_MODEL_DIR": str(folder / "no-audio-models"),
            "BBS_IMAGE_MODEL_DIR": str(folder / "no-image-model"),
            "BBS_IMAGE_DIR": str(folder / "images"),
            "BBS_SAMPLE_DATA": "1",
            "BBS_CATALOG": "0",
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
                    if httpx.get(base + "/api/creatures", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Server startup failed")
            record = next(
                r for r in core.records(db) if r["display_name"] == "Tyrannosaurus"
            )
            settings = {
                "model": "synthetic-test-backend",
                "revision": "a" * 40,
                "model_path": str(folder / "fixture"),
                "model_license": "Test fixture, no real inference",
                "resolution": 512,
                "steps": 2,
                "guidance": 7.5,
                "threads": 2,
                "base_seed": 42,
                "output_dir": str(folder / "images"),
                "device": "cpu",
                "dtype": "float32",
                "batch_size": 1,
            }
            core.enqueue(db, [record], settings)
            assert (
                core.worker(
                    db, Fixture, progress=lambda *a, **k: None, install_signals=False
                )["completed"]
                == 1
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
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
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.locator("#start-adventure").click()
                page.locator("[data-category=dinosaur]").click()
                card = page.locator("#creatures .creature").filter(
                    has=page.get_by_role(
                        "button", name="Meet Tyrannosaurus", exact=True
                    )
                )
                assert "AI-generated illustration" in card.inner_text()
                picture = card.locator(".creature-pick img")
                picture.scroll_into_view_if_needed()
                page.wait_for_function(
                    "() => [...document.querySelectorAll('#creatures img')].some(image=>image.currentSrc.includes('/api/creature-images/files/') && image.complete && image.naturalWidth>0)"
                )
                url = picture.evaluate("image=>image.currentSrc")
                response = httpx.get(url)
                assert (
                    response.status_code == 200
                    and response.headers["content-type"] == "image/webp"
                )
                card.locator(".creature-pick").click()
                assert (
                    "anatomical accuracy has not been verified"
                    in page.locator("#profile-review").inner_text()
                )
                page.locator("#settings-open").click()
                page.locator("#image-management summary").click()
                page.wait_for_function(
                    "document.getElementById('image-generation-status').textContent.includes('1 /')"
                )
                page.locator("#generated-image-creature").select_option(
                    str(record["id"])
                )
                page.locator("#view-image-metadata").click()
                page.wait_for_function(
                    "document.getElementById('image-generation-metadata').textContent.includes('negative_prompt')"
                )
                page.locator("#regenerate-creature-image").click()
                page.wait_for_function(
                    "document.getElementById('image-generation-message').textContent.includes('Unlock parent controls')"
                )
                assert (
                    page.locator("#parent-proposals input[data-scope=image]").count()
                    == 0
                )
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert not errors, errors
                browser.close()
            print(
                "Generated-image mobile regression passed: real local WebP transport from a mocked backend, selection/profile AI labels, status/prompt metadata and protected regeneration"
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
