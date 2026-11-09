"""Full-catalog mobile visibility on a disposable database; no external requests."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from playwright.sync_api import sync_playwright


def run(full_regression=False):
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bedtime-all-creatures-") as temporary:
        folder = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "BBS_DB_PATH": str(folder / "app.sqlite3"),
            "BBS_SAMPLE_DATA": "0",
            "BBS_CATALOG": "1",
            "BBS_IMPORT_DIR": str(folder / "importer"),
            "BBS_MODEL_DIR": str(folder / "no-models"),
            "BBS_AUDIO_CACHE": str(folder / "cache"),
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
                    response = httpx.get(base + "/api/creatures", timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Disposable server failed to start")
            creatures = response.json()
            dinosaurs = [c for c in creatures if c["category"] == "dinosaur"]
            assert len(dinosaurs) > 10
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
                requests = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url))
                page.goto(base)
                page.locator("#start-adventure").click()
                page.locator("[data-category=dinosaur]").click()
                page.wait_for_function(
                    "document.querySelectorAll('#creatures .creature').length === "
                    + str(len(dinosaurs))
                )
                assert page.locator("#browse-group").input_value() == "all"
                assert page.locator("#library-heading").inner_text() == "All Creatures"
                page.locator("#creatures .creature").last.scroll_into_view_if_needed()
                assert page.locator("#creatures .creature-pick").last.is_visible()
                assert page.locator(
                    '#creatures .creature-pick img[loading="lazy"]'
                ).count() == len(dinosaurs)
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                page.locator("details.browse-tools").evaluate(
                    "element=>element.open=true"
                )
                term = dinosaurs[-1]["scientific_name"].lower()
                page.locator("#search").fill(term)
                expected = sum(
                    term in (c["name"] + " " + c["scientific_name"]).lower()
                    for c in dinosaurs
                )
                assert page.locator("#creatures .creature").count() == expected
                page.locator("#search").fill("no-creature-has-this-name")
                assert page.locator("#creatures .creature").count() == 0
                page.locator("#search").fill("")
                page.locator("#browse-group").select_option("popular")
                assert 0 < page.locator("#creatures .creature").count() < len(dinosaurs)
                page.locator("#browse-group").select_option("all")
                assert page.locator("#creatures .creature").count() == len(dinosaurs)
                labels = page.locator(
                    "#creatures .creature-select:enabled"
                ).evaluate_all(
                    "buttons=>buttons.slice(0,8).map(button=>button.getAttribute('aria-label'))"
                )
                assert len(labels) == 8
                for label in labels:
                    page.locator("#creatures").get_by_role(
                        "button", name=label, exact=True
                    ).click()
                assert page.locator("#count").inner_text() == "8 of 8 Selected"
                assert page.locator("#next").is_enabled()
                assert (
                    page.locator(
                        '#creatures .creature-select[aria-pressed="false"]:enabled'
                    ).count()
                    == 0
                )
                for category in ["shark", "marine_reptile", "ocean"]:
                    page.locator("#home").click()
                    page.locator("#start-adventure").click()
                    page.locator(f"[data-category={category}]").click()
                    total = sum(
                        c["category"] in {"shark", "marine_reptile"}
                        if category == "ocean"
                        else c["category"] == category
                        for c in creatures
                    )
                    page.wait_for_function(
                        "document.querySelectorAll('#creatures .creature').length === "
                        + str(total)
                    )
                    assert page.locator("#browse-group").input_value() == "all"
                page.locator("#home").click()
                page.locator("#browse-encyclopedia").click()
                page.wait_for_function(
                    "document.querySelectorAll('#encyclopedia-cards .creature').length === "
                    + str(len(creatures))
                )
                assert page.locator("#discovery-filter").input_value() == "all"
                page.locator("#discovery-filter").select_option("dinosaur")
                assert page.locator("#encyclopedia-cards .creature").count() == len(
                    dinosaurs
                )
                page.locator("#encyclopedia-search").fill(term)
                assert page.locator("#encyclopedia-cards .creature").count() == expected
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert all(url.startswith(base) for url in requests)
                assert not errors, errors
                browser.close()
            if full_regression:
                from redesign_smoke import run as tournament_regression
                from library_smoke import run as library_regression

                tournament_regression(base)
                library_regression(base)
            print(
                f"Full-catalog mobile passed: {len(creatures)} book entries; {len(dinosaurs)} dinosaur cards by default; category/search filters, lazy images, scrolling and eight-selection cap"
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    run("--full-regression" in sys.argv)
