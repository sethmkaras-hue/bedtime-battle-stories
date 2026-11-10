"""Test-only server: synthetic local TTS and mocked image HTTP, never production data."""

import io
import os
import sys
import wave
from pathlib import Path

import httpx
import uvicorn
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main
from app.audio.service import AudioService
from app.chapters import images
from app.importer.network import PoliteClient


class Voice:
    name = "kokoro"
    last_error = ""

    def is_available(self):
        return True

    def version(self):
        return "browser-synthetic-voice-v1"

    def list_voices(self):
        return [
            {"id": "af_heart", "name": "Synthetic Heart"},
            {"id": "af_sarah", "name": "Synthetic Sarah"},
        ]

    def get_provider_info(self):
        return {"available": True, "voices": self.list_voices(), "reason": ""}

    def generate_audio(self, text, voice, speed, path):
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(
                b"\0\0" * round(len(text.split()) / (2.15 * speed) * 8000)
            )


class MissingPiper(Voice):
    name = "piper"

    def is_available(self):
        return False


def source(request):
    if request.url.host == "commons.wikimedia.org":
        name = request.url.params.get("gsrsearch", "").replace(
            '"', ""
        ) or request.url.params.get("gcmtitle", "").removeprefix("Category:")
        # Browser test selects Diplodocus and explicitly searches its scientific name.
        name = "Diplodocus"
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        str(i): {
                            "title": f"File:{name} restoration {i}",
                            "pageid": i,
                            "imageinfo": [
                                {
                                    "url": f"https://upload.wikimedia.org/test-{i}.png",
                                    "thumburl": f"https://upload.wikimedia.org/thumb-{i}.png",
                                    "descriptionurl": f"https://commons.wikimedia.org/wiki/File:Fixture-{i}",
                                    "width": 800,
                                    "height": 600,
                                    "extmetadata": {
                                        "ImageDescription": {
                                            "value": name + " life restoration"
                                        },
                                        "Artist": {"value": "Synthetic test artist"},
                                    },
                                }
                            ],
                        }
                        for i in range(25)
                    }
                }
            },
        )
    assert request.url.host == "upload.wikimedia.org"
    output = io.BytesIO()
    Image.new("RGB", (800, 600), "purple").save(output, format="PNG")
    return httpx.Response(
        200, content=output.getvalue(), headers={"Content-Type": "image/png"}
    )


def client(root, **kwargs):
    return PoliteClient(
        root, transport=httpx.MockTransport(source), sleep=lambda _: None, **kwargs
    )


if __name__ == "__main__":
    main.create_service = lambda: AudioService(
        os.environ["BBS_AUDIO_CACHE"],
        os.environ["BBS_MODEL_DIR"],
        providers={"kokoro": Voice(), "piper": MissingPiper()},
    )
    images.PoliteClient = client
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
