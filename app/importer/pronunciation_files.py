"""Read explicitly supplied reference files without requesting source websites.

A file is evidence for adult review, never permission to scrape or automatic
pronunciation certification. Paths are only accepted by the local CLI.
"""

from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.library import Pronunciation, normalize
from .sources import parse_pronunciation


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scientific_name: str = Field(min_length=1, max_length=120)
    source_url: str
    publisher: str = Field(min_length=1, max_length=200)
    retrieved_on: date
    phonetic: str | None = Field(default=None, max_length=100)
    stress: str | None = Field(default=None, max_length=100)
    tts_text: str | None = Field(default=None, max_length=200)
    alternatives: list[str] = Field(default_factory=list, max_length=10)
    reference_file: str | None = None
    status: str = Field(default="unverified", pattern="^(unverified|verified)$")
    checked_on: date | None = None
    verified_by: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def evidence(self):
        url = urlsplit(self.source_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Reference source_url must be a public HTTPS citation")
        if self.reference_file and any((self.phonetic, self.stress, self.tts_text)):
            raise ValueError("Supply reference_file or structured guidance, not both")
        if self.status == "verified" and not (self.checked_on and self.verified_by):
            raise ValueError("Supplied verification requires reviewer and date")
        return self


def load_references(path):
    path = Path(path).resolve()
    if path.stat().st_size > 2_000_000:
        raise ValueError("Pronunciation manifest exceeds 2 MB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) != {"schema_version", "entries"}
        or data["schema_version"] != 1
        or not isinstance(data["entries"], list)
    ):
        raise ValueError("Expected schema_version: 1 and entries list")
    result = {}
    for raw in data["entries"]:
        ref = Reference.model_validate(raw)
        key = normalize(ref.scientific_name)
        if key in result:
            raise ValueError("Duplicate scientific identity in pronunciation manifest")
        if ref.reference_file:
            local = (path.parent / ref.reference_file).resolve()
            if not local.is_relative_to(path.parent) or local.suffix.lower() not in {
                ".html",
                ".htm",
            }:
                raise ValueError(
                    "Saved reference must be an HTML file within the manifest directory"
                )
            if local.stat().st_size > 2_000_000:
                raise ValueError("Saved pronunciation reference exceeds 2 MB")
            content = local.read_bytes()
            guide = parse_pronunciation(content.decode("utf-8"), ref.scientific_name)
            guide["alternatives"] = list(
                dict.fromkeys(guide["alternatives"] + ref.alternatives)
            )
            checksum = hashlib.sha256(content).hexdigest()
        else:
            guide = {
                "phonetic": ref.phonetic,
                "stress": ref.stress,
                "tts_text": ref.tts_text,
                "alternatives": ref.alternatives,
            }
            checksum = None
        if not all(guide.get(field) for field in ("phonetic", "stress", "tts_text")):
            raise ValueError(
                "Reference requires literal phonetic guidance, stress and TTS text"
            )
        pron = Pronunciation.model_validate(
            {**guide, "source_url": ref.source_url, "status": "unverified"}
        ).model_dump(mode="json")
        result[key] = {
            **pron,
            "scientific_name": ref.scientific_name,
            "publisher": ref.publisher,
            "retrieved_on": ref.retrieved_on.isoformat(),
            "reference_sha256": checksum,
            "acquisition": "supplied_reference",
            "source_verification": {
                "status": ref.status,
                "checked_on": ref.checked_on.isoformat() if ref.checked_on else None,
                "verified_by": ref.verified_by,
            },
        }
    return result
