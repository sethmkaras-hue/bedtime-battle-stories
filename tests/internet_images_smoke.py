"""Mobile FastAPI transport for synthetic imported Diplodocus/Allosaurus artwork."""

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from app.images import core
from app.importer import internet_images as imports
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
            "BBS_SAMPLE_DATA": "0",
            "BBS_CATALOG": "1",
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
            selected = [
                r
                for r in core.records(db)
                if r["display_name"] in {"Diplodocus", "Allosaurus"}
            ]
            assert len(selected) == 2
            for record in selected:
                image = Image.new("RGB", (800, 600), "navy")
                ImageDraw.Draw(image).ellipse((90, 90, 420, 420), fill="purple")
                content = io.BytesIO()
                image.save(content, format="PNG")
                candidate = imports.candidate(
                    {
                        "url": "https://upload.wikimedia.org/synthetic-"
                        + record["display_name"]
                        + ".png",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Synthetic",
                        "width": 800,
                        "height": 600,
                        "extmetadata": {
                            key: {"value": value}
                            for key, value in {
                                "ImageDescription": record["scientific_name"]
                                + " life restoration",
                                "Artist": "Synthetic fixture creator",
                                "LicenseShortName": "CC BY 4.0",
                                "LicenseUrl": "https://creativecommons.org/licenses/by/4.0/",
                            }.items()
                        },
                    },
                    {"title": "File:" + record["scientific_name"]},
                    record,
                )
                assert imports.install(
                    db, record, candidate, content.getvalue(), folder / "images"
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
                page.wait_for_function(
                    "document.querySelectorAll('#creatures .creature').length === 110"
                )
                for name in ("Diplodocus", "Allosaurus"):
                    card = page.locator("#creatures .creature").filter(
                        has=page.get_by_role("button", name="Meet " + name, exact=True)
                    )
                    picture = card.locator(".creature-notes img")
                    picture.scroll_into_view_if_needed()
                    picture.evaluate("image => image.decode()")
                    url = picture.evaluate("image => image.currentSrc")
                    assert "/api/library/images/" in url
                    response = httpx.get(url)
                    assert (
                        response.status_code == 200
                        and response.headers["content-type"] == "image/webp"
                    )
                    card.locator(".creature-notes").click()
                    page.locator("#profile-image img").evaluate(
                        "image => image.decode()"
                    )
                    assert (
                        "Synthetic fixture creator"
                        in page.locator("#profile-image-attribution").inner_text()
                    )
                    page.locator("#back").click()
                page.locator("#settings-open").click()
                assert page.locator("#open-parent-review").count() == 0
                assert page.locator("#regenerate-creature-image").count() == 0
                page.locator("#image-management summary").click()
                page.locator("#refresh-import-coverage").click()
                page.wait_for_function(
                    "document.getElementById('image-import-coverage').textContent.includes('2 Internet images')"
                )
                page.locator("#open-attributions").click()
                page.wait_for_function(
                    "document.querySelectorAll('#attribution-list article').length === 164"
                )
                assert (
                    "Synthetic fixture creator"
                    in page.locator("#attribution-list").inner_text()
                )
                assert "CC BY 4.0" in page.locator("#attribution-list").inner_text()
                assert not errors, errors
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                browser.close()
            print(
                "Mobile imported Diplodocus/Allosaurus images, credits and retired controls passed"
            )
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    run()
