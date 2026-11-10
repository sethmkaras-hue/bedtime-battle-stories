"""Explicit CLI-only local image/metadata acquisition. No remote downloads."""

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.library import normalize
from .sources import image_candidate


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scientific_name: str = Field(min_length=1, max_length=120)
    image_file: str
    metadata_file: str
    source_kind: Literal["commons", "licensed_reference"] = "commons"
    title: str | None = None
    retrieved_on: date


class Credit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    identified_taxon: str = Field(min_length=1, max_length=120)
    source_url: str
    creator: str = Field(min_length=1, max_length=1000)
    license: Literal[
        "CC0-1.0",
        "Public-Domain",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "CC-BY-3.0",
        "CC-BY-SA-3.0",
    ]
    license_url: str
    description: str = Field(min_length=1, max_length=10000)
    identity_evidence: str = Field(min_length=1, max_length=2000)
    identity_status: Literal["supported", "uncertain"] = "uncertain"


class PrivateCredit(Credit):
    # Local/private import retains declarations verbatim; missing rights are not
    # evidence of public-domain status and are not a selection rejection.
    creator: str | None = None
    license: str | None = None
    license_url: str | None = None


def local_file(folder, relative, limit):
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise ValueError("Reference files must be within the image manifest directory")
    if path.stat().st_size > limit:
        raise ValueError("Image/reference exceeds the size limit")
    return path


def load_images(path, private=False):
    path = Path(path).resolve()
    if path.stat().st_size > 2_000_000:
        raise ValueError("Image manifest exceeds 2 MB")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "entries"}
        or manifest["schema_version"] != 1
        or not isinstance(manifest["entries"], list)
    ):
        raise ValueError("Expected image schema_version: 1 and entries list")
    result = {}
    for raw in manifest["entries"]:
        entry = Entry.model_validate(raw)
        original = local_file(path.parent, entry.image_file, 20_000_000)
        metadata = local_file(path.parent, entry.metadata_file, 2_000_000)
        data = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Image metadata must be an object")
        credit = None
        if entry.source_kind == "commons":
            # Accept a saved Action API query/imageinfo response or one page object.
            if "query" in data and not isinstance(data["query"], dict):
                raise ValueError("Commons query metadata must be an object")
            pages = (
                data.get("query", {}).get("pages", {}) if "query" in data else [data]
            )
            pages = list(pages.values()) if isinstance(pages, dict) else pages
            if not isinstance(pages, list) or not all(
                isinstance(page, dict) for page in pages
            ):
                raise ValueError("Commons metadata requires page objects")
            if entry.title:
                pages = [p for p in pages if p.get("title") == entry.title]
            if (
                len(pages) != 1
                or not isinstance(pages[0].get("imageinfo"), list)
                or not pages[0]["imageinfo"]
            ):
                raise ValueError(
                    "Select one exact Commons file using title and saved imageinfo metadata"
                )
            page = pages[0]
            info = page["imageinfo"][0]
            if (
                not isinstance(info, dict)
                or not isinstance(info.get("extmetadata", {}), dict)
                or not all(
                    isinstance(value, dict) and isinstance(value.get("value", ""), str)
                    for value in info.get("extmetadata", {}).values()
                )
            ):
                raise ValueError(
                    "Commons imageinfo/extmetadata values must be objects with textual values"
                )
        else:
            credit = (
                (PrivateCredit if private else Credit)
                .model_validate(data)
                .model_dump(mode="json")
            )
            labels = {
                "CC0-1.0": "CC0",
                "Public-Domain": "Public domain",
                "CC-BY-4.0": "CC BY 4.0",
                "CC-BY-SA-4.0": "CC BY-SA 4.0",
                "CC-BY-3.0": "CC BY 3.0",
                "CC-BY-SA-3.0": "CC BY-SA 3.0",
            }
            page = {"title": credit["title"]}
            info = {
                "descriptionurl": credit["source_url"],
                "extmetadata": {
                    k: {"value": v or ""}
                    for k, v in {
                        "Artist": credit["creator"],
                        "LicenseShortName": labels.get(
                            credit["license"], credit["license"]
                        ),
                        "LicenseUrl": credit["license_url"],
                        "ImageDescription": credit["description"],
                    }.items()
                },
            }
        with original.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        item = {
            "image_path": str(original),
            "image_sha256": sha,
            "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
            "info": info,
            "page": page,
            "credit": credit,
            "source_kind": entry.source_kind,
            "retrieved_on": entry.retrieved_on.isoformat(),
        }
        key = normalize(entry.scientific_name)
        entries = result.setdefault(key, [])
        if not any(
            i["image_sha256"] == sha and i["metadata_sha256"] == item["metadata_sha256"]
            for i in entries
        ):
            entries.append(item)
    return result


def candidates(record, entries, folder, dry_run=False):
    from .runner import preview_bytes

    result = []
    for item in entries:
        candidate = image_candidate(
            item["info"],
            item["page"],
            set(),
            None,
            record["scientific_name"],
            record["category"] == "shark" and record.get("modern_status") != "extinct",
            source_kind=item["source_kind"],
        )
        credit = item["credit"]
        if credit:
            candidate["identity_evidence"] = credit["identity_evidence"]
            if (
                normalize(credit["identified_taxon"])
                != normalize(record["scientific_name"])
                or credit["identity_status"] != "supported"
            ):
                candidate["issues"].append(
                    "Supplied taxon identity is mismatched or uncertain; research before approval"
                )
                candidate["supported"] = False
        candidate.update(
            acquisition="supplied_image",
            source_kind=item["source_kind"],
            retrieved_on=item["retrieved_on"],
            reference_sha256=item["metadata_sha256"],
            supplied_image_sha256=item["image_sha256"],
        )
        if candidate["supported"] and not dry_run:
            try:
                original = Path(item["image_path"])
                if original.stat().st_size > 20_000_000:
                    raise ValueError("Image exceeds size limit")
                content = original.read_bytes()
                if hashlib.sha256(content).hexdigest() != item["image_sha256"]:
                    raise ValueError("Supplied image changed during import; rerun")
                candidate = preview_bytes(content, candidate, folder)
            except (ValueError, OSError, ImportError) as error:
                candidate["supported"] = False
                candidate["issues"].append(
                    "Local image preparation failed: " + str(error)
                )
        result.append(candidate)
    return result
