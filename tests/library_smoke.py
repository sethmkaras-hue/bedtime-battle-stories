"""Encyclopedia and instant file playback, with a clearly synthetic media fixture."""

import io
from pathlib import Path
import sys
from urllib.parse import urlsplit
import wave
from playwright.sync_api import sync_playwright


def run(base, screenshots=None):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\0\0" * 64000)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        page = browser.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        requests = []
        errors = []
        page.on("request", lambda r: requests.append((r.method, urlsplit(r.url).path)))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.locator("#browse-encyclopedia").click()
        page.locator("#encyclopedia-cards .creature").nth(7).wait_for()
        page.locator("#discovery-filter").select_option("shark")
        page.locator("#encyclopedia-search").fill("Great white")
        assert page.locator("#encyclopedia-cards .creature").count() == 1
        page.locator("#encyclopedia-cards .creature-notes").click()
        assert page.locator("#profile").is_visible()
        assert "Great white" in page.locator("#profile-name").inner_text()
        assert "Unknown" in page.locator("#profile-facts").inner_text()
        assert "Unknown details" in page.locator("#profile-review").inner_text()
        page.locator("#profile-speaker .speaker").click()
        page.wait_for_function("!audio.pronouncing")
        assert not any(
            method == "POST" and path == "/api/audio" for method, path in requests
        )
        if screenshots:
            Path(screenshots).mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(Path(screenshots) / "profile-mobile.png"), full_page=True
            )
        page.locator("#back").click()
        assert page.locator("#encyclopedia").is_visible()
        page.locator("#encyclopedia-search").fill("")
        page.locator("#discovery-filter").select_option("fast_swimmers")
        assert "No reviewed" in page.locator("#encyclopedia-status").inner_text()

        # Inject only an audio transport fixture; never change production verification records.
        def creatures(route):
            response = route.fetch()
            rows = response.json()
            for c in rows:
                c["pronunciation_audio"] = {
                    "url": f"/api/library/pronunciations/{c['id']}/" + "a" * 64,
                    "provider": "kokoro",
                    "voice": "af_heart",
                    "speed": 0.8,
                }
                c["pronunciation_audio_options"] = [c["pronunciation_audio"]]
            route.fulfill(response=response, json=rows)

        page.route("**/api/creatures*", creatures)
        page.route(
            "**/api/library/pronunciations/*/*",
            lambda r: r.fulfill(
                status=200, content_type="audio/wav", body=buffer.getvalue()
            ),
        )
        page.locator("#home").click()
        page.locator("#browse-encyclopedia").click()
        page.locator("#discovery-filter").select_option("featured")
        page.locator("#encyclopedia-cards .speaker").first.click()
        page.wait_for_function("!audio.nameAudio.paused && audio.nameAudio.duration>0")
        page.wait_for_function(
            "document.querySelector('#encyclopedia-cards .speaker').getAttribute('aria-pressed')==='true'"
        )
        page.locator("#encyclopedia-cards .speaker").nth(1).click()
        page.wait_for_function("!audio.nameAudio.paused")
        assert (
            page.locator("#encyclopedia-cards .speaker").first.get_attribute(
                "aria-pressed"
            )
            == "false"
        )
        assert not any(
            method == "POST" and path == "/api/audio" for method, path in requests
        )
        page.locator("#encyclopedia-cards .creature-notes").first.click()
        page.locator("#profile-add").click()
        page.locator("#selection").wait_for(state="visible")
        assert (
            page.locator("#selection").is_visible()
            and page.locator("#count").inner_text() == "1 of 8 Selected"
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors, errors
        browser.close()
    print(
        "Library mobile regression passed: encyclopedia/search/profile, missing audio, local prepared playback, prepared playback avoids regeneration, selection integration"
    )


if __name__ == "__main__":
    run(
        sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8502",
        sys.argv[2] if len(sys.argv) > 2 else None,
    )
