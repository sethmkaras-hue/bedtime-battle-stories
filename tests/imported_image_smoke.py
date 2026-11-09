"""Actual CLI installation, authenticated approval and child WebP rendering.

Synthetic originals/credits, disposable DB/cache. Only uniquely named generated
static derivatives are temporarily served from the real installation and removed.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import httpx
from PIL import Image, PngImagePlugin
from playwright.sync_api import sync_playwright
from app.importer.auth import password_record


def run():
    project = Path(__file__).resolve().parents[1]
    generated_hashes = []
    server = None
    with tempfile.TemporaryDirectory(prefix="bedtime-installed-images-") as temporary:
        folder = Path(temporary)
        state = folder / "importer"
        state.mkdir()
        (state / "parent-auth.json").write_text(
            json.dumps(password_record("synthetic-parent-passphrase"))
        )
        env = {
            **os.environ,
            "BBS_DB_PATH": str(folder / "app.sqlite3"),
            "BBS_IMPORT_DIR": str(state),
            "BBS_AUDIO_CACHE": str(folder / "audio"),
            "BBS_MODEL_DIR": str(folder / "no-models"),
            "BBS_SAMPLE_DATA": "1",
            "BBS_CATALOG": "0",
        }
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
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
                    response = httpx.get(base + "/api/creatures", timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Server startup failed")
            records = response.json()
            target = next(r for r in records if r["name"] == "Tyrannosaurus")
            alternate = next(
                r
                for r in records
                if r["category"] == "dinosaur" and r["id"] != target["id"]
            )

            def manifest(record, label):
                original = folder / (label + ".png")
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("synthetic-fixture", str(uuid.uuid4()))
                Image.new("RGB", (800, 500), "purple").save(original, pnginfo=metadata)
                sha = hashlib.sha256(original.read_bytes()).hexdigest()[:16]
                assert not list((project / "static/creatures").glob("import-*-" + sha))
                generated_hashes.append(sha)
                credit = folder / (label + "-credit.json")
                credit.write_text(
                    json.dumps(
                        {
                            "title": "Synthetic browser fixture",
                            "identified_taxon": record["scientific_name"],
                            "source_url": "https://example.test/art",
                            "creator": "Synthetic browser fixture creator",
                            "license": "CC0-1.0",
                            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                            "description": "Life reconstruction of "
                            + record["scientific_name"],
                            "identity_evidence": "Synthetic named-caption assertion; not real research",
                            "identity_status": "supported",
                        }
                    )
                )
                path = folder / (label + "-images.json")
                path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "entries": [
                                {
                                    "scientific_name": record["scientific_name"],
                                    "image_file": original.name,
                                    "metadata_file": credit.name,
                                    "source_kind": "licensed_reference",
                                    "retrieved_on": "2026-11-01",
                                }
                            ],
                        }
                    )
                )
                return path

            def install(path, propose=False):
                report = folder / "report.json"
                command = [
                    sys.executable,
                    "scripts/import_creature_library.py",
                    "--pilot",
                    "10",
                    "--offline",
                    "--image-references",
                    str(path),
                    "--skip-audio",
                    "--report",
                    str(report),
                ]
                if propose:
                    command.append("--propose-only")
                result = subprocess.run(
                    command,
                    cwd=project,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=45,
                )
                assert result.returncode in (0, 2), result.stderr
                return json.loads(report.read_text())

            def actual_picture(page, record):
                card = page.locator("#creatures .creature").filter(
                    has=page.get_by_role(
                        "button", name="Meet " + record["name"], exact=True
                    )
                )
                picture = card.locator(".creature-pick img")
                picture.scroll_into_view_if_needed()
                picture.wait_for(state="visible")
                page.wait_for_function(
                    "name => [...document.querySelectorAll('#creatures .creature')].some(card=>card.querySelector('strong').textContent===name && card.querySelector('.creature-pick img').currentSrc.endsWith('.webp') && card.querySelector('.creature-pick img').complete && card.querySelector('.creature-pick img').naturalWidth>0)",
                    arg=record["name"],
                )
                assert picture.get_attribute("data-real-image") == "true"
                url = picture.evaluate("image=>image.currentSrc")
                response = httpx.get(url)
                assert response.status_code == 200 and response.headers[
                    "content-type"
                ].startswith("image/webp")
                assert (
                    response.content[:4] == b"RIFF"
                    and response.content[8:12] == b"WEBP"
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
                page.locator("#creatures .creature-select").nth(0).click()
                page.locator("#creatures .creature-select").nth(1).click()
                before = page.evaluate("JSON.stringify(selected)")
                proposed = install(manifest(target, "manual"), True)
                assert proposed["images_published"] == 0
                page.locator("#settings-open").click()
                page.locator("#open-parent-review").click()
                page.locator("#parent-password").fill("synthetic-parent-passphrase")
                page.locator("#parent-login button").click()
                image_choice = page.locator("input[data-scope=image]")
                image_choice.wait_for()
                image_choice.check()
                card = page.locator(".parent-proposal").filter(has=image_choice)
                card.locator("input[type=checkbox]").last.check()
                card.get_by_role("button", name="Approve inspected updates").click()
                image_choice.wait_for(state="detached")
                page.locator("#back").click()
                page.locator("#back").click()
                assert (
                    page.locator("#selection").is_visible()
                    and page.evaluate("JSON.stringify(selected)") == before
                )
                actual_picture(page, target)
                automatic = install(manifest(alternate, "automatic"))
                assert automatic["images_published"] == 1
                row = next(
                    r
                    for r in httpx.get(base + "/api/creatures").json()
                    if r["id"] == alternate["id"]
                )
                assert (
                    row["profile"]["image"]["approval_method"] == "automated"
                    and row["profile"]["verification_status"] == "unverified"
                )
                fresh = browser.new_page(
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                    has_touch=True,
                )
                fresh.goto(base)
                fresh.locator("#start-adventure").click()
                fresh.locator("[data-category=dinosaur]").click()
                actual_picture(fresh, alternate)
                assert fresh.evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                )
                assert not errors, errors
                browser.close()
            print(
                "Installed-image mobile regression passed: manual image decodes without reload and preserves selections; automatic CLI image serves real WebP on fresh child selection"
            )
        finally:
            if server:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            for sha in generated_hashes:
                for path in (project / "static/creatures").glob("import-*-" + sha):
                    shutil.rmtree(path)


if __name__ == "__main__":
    run()
