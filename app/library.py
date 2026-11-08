"""Versioned encyclopedia data, provenance and assets; independent of game rules."""

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import wave
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
LICENSES = {
    "CC0-1.0",
    "Public-Domain",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "CC-BY-3.0",
    "CC-BY-SA-3.0",
}
CATEGORIES = (
    "dinosaur",
    "shark",
    "marine_reptile",
)  # Last is the legacy Prehistoric Ocean API key.


def normalize(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def local_asset(path):
    if (
        not path
        or re.fullmatch(r"/static/[A-Za-z0-9_./-]*", path) is None
        or ".." in Path(path).parts
    ):
        raise ValueError("Assets must use safe /static/ paths")
    resolved = (ROOT / path.lstrip("/")).resolve()
    if not resolved.is_relative_to((ROOT / "static").resolve()):
        raise ValueError("Asset path escapes static root")
    return resolved


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Measurement(StrictModel):
    minimum: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    maximum: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    unit: Literal["m", "kg"]
    note: str | None = None
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered(self):
        if (self.minimum is None) != (self.maximum is None):
            raise ValueError("Supply both range endpoints or leave both unknown")
        if self.minimum is not None and self.minimum > self.maximum:
            raise ValueError("Measurement range is reversed")
        if self.minimum is not None and not self.source_ids:
            raise ValueError("Known measurements require source references")
        return self


class Source(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    publisher: str | None = None
    checked_on: date | None = None
    supports: list[str] = Field(default_factory=list)


class Pronunciation(StrictModel):
    status: Literal["unverified", "verified"] = "unverified"
    phonetic: str | None = None
    stress: str | None = None
    tts_text: str | None = None
    source_url: str | None = Field(default=None, pattern=r"^https://")
    verified_by: str | None = None
    checked_on: date | None = None
    alternatives: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence(self):
        if self.status == "verified" and not all(
            [
                self.phonetic,
                self.stress,
                self.tts_text,
                self.source_url,
                self.verified_by,
                self.checked_on,
            ]
        ):
            raise ValueError(
                "Verified pronunciation requires a guide, stress, TTS text, inspected source, reviewer and date"
            )
        return self


class Image(StrictModel):
    placeholder: bool = True
    path: str | None = None
    variants: dict[str, str] = Field(default_factory=dict)
    creator: str | None = None
    original_source_url: str | None = None
    license: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    modifications: str | None = None
    identified_taxon: str | None = None
    verified_by: str | None = None
    checked_on: date | None = None

    @model_validator(mode="after")
    def licensed(self):
        if any(
            not key.isdecimal() or not 1 <= int(key) <= 4096 for key in self.variants
        ):
            raise ValueError(
                "Image variant widths must be positive pixel counts up to 4096"
            )
        for path in ([self.path] if self.path else []) + list(self.variants.values()):
            local_asset(path)
        if not self.placeholder:
            if self.license not in LICENSES:
                raise ValueError("Unsupported or unspecified reusable image license")
            if not all(
                [
                    self.path,
                    self.creator,
                    self.original_source_url,
                    self.license_url,
                    self.attribution,
                    self.modifications,
                    self.identified_taxon,
                    self.verified_by,
                    self.checked_on,
                ]
            ):
                raise ValueError(
                    "Real artwork requires complete attribution and taxon identification"
                )
            if not self.original_source_url.startswith(
                "https://"
            ) or not self.license_url.startswith("https://"):
                raise ValueError("Image source/license URLs must be HTTPS")
            if not self.path.endswith(".webp"):
                raise ValueError("Imported images must be optimized local WebP files")
        return self


class CreatureRecord(StrictModel):
    stable_key: str = Field(pattern=r"^[a-z][a-z0-9_-]*:[a-z0-9-]+$")
    id: int | None = Field(default=None, gt=0, strict=True)
    display_name: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    category: Literal["dinosaur", "shark", "marine_reptile"]
    subcategory: str | None = None
    taxon_group: Literal[
        "dinosaur", "shark", "marine_reptile", "other_marine", "pterosaur", "unknown"
    ] = "unknown"
    taxon_rank: Literal["species", "genus", "unknown"] = "unknown"
    verification_status: Literal["unverified", "verified"] = "unverified"
    verified_by: str | None = None
    checked_on: date | None = None
    time_period: str | None = None
    modern_status: Literal["living", "extinct", "unknown"] = "unknown"
    habitat: Literal["land", "marine", "semi_aquatic", "unknown"] = "unknown"
    geographic_distribution: list[str] = Field(default_factory=list)
    diet: str | None = None
    length: Measurement = Field(default_factory=lambda: Measurement(unit="m"))
    weight: Measurement = Field(default_factory=lambda: Measurement(unit="kg"))
    physical_characteristics: list[str] = Field(default_factory=list)
    offensive_adaptations: list[str] = Field(default_factory=list)
    defensive_adaptations: list[str] = Field(default_factory=list)
    fun_facts: list[str] = Field(default_factory=list, max_length=3)
    description: str | None = None
    discovery_tags: list[Literal["giants", "fast_swimmers", "armored"]] = Field(
        default_factory=list
    )
    image: Image = Field(default_factory=Image)
    pronunciation: Pronunciation = Field(default_factory=Pronunciation)
    sources: list[Source] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def scientific_evidence(self):
        if self.image.placeholder and self.image.path is None:
            category = (
                "shark"
                if self.category == "shark"
                else "marine_reptile"
                if self.category == "marine_reptile"
                else "dinosaur"
            )
            self.image.path = f"/static/assets/{category}.svg"
            self.image.creator = "Bedtime Battle Stories contributors"
            self.image.attribution = (
                "Decorative project placeholder; not identified species artwork"
            )
            self.image.license = "project-placeholder"
        if self.length.unit != "m" or self.weight.unit != "kg":
            raise ValueError("Length is in metres and weight in kilograms")
        if self.category == "dinosaur" and self.taxon_group not in {
            "dinosaur",
            "unknown",
        }:
            raise ValueError("Pterosaurs and marine reptiles are not dinosaurs")
        if self.category == "shark" and self.taxon_group not in {"shark", "unknown"}:
            raise ValueError("Shark category requires shark taxonomy")
        if self.category == "marine_reptile" and self.taxon_group not in {
            "marine_reptile",
            "other_marine",
            "unknown",
        }:
            raise ValueError(
                "Prehistoric Ocean must distinguish reptiles from other aquatic taxa"
            )
        source_ids = {s.id for s in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("Duplicate source IDs")
        if not set(self.length.source_ids + self.weight.source_ids) <= source_ids:
            raise ValueError("Measurement references an unknown source ID")
        if self.verification_status == "verified":
            if (
                not all(
                    [
                        self.verified_by,
                        self.checked_on,
                        self.sources,
                        self.description,
                        self.time_period,
                        self.subcategory,
                        self.geographic_distribution,
                        self.physical_characteristics,
                    ]
                )
                or len(self.fun_facts) != 3
            ):
                raise ValueError(
                    "Verified profiles require reviewed provenance, context and three sourced facts"
                )
            if self.taxon_group == "unknown" or self.taxon_rank == "unknown":
                raise ValueError("Verified profiles require explicit taxonomy")
            supported = {
                field for s in self.sources if s.checked_on for field in s.supports
            }
            required = {
                "taxonomy",
                "description",
                "time_period",
                "habitat",
                "diet",
                "fun_facts",
                "physical_characteristics",
                "geographic_distribution",
            }
            if self.discovery_tags:
                required.add("discovery_tags")
            if self.offensive_adaptations:
                required.add("offensive_adaptations")
            if self.defensive_adaptations:
                required.add("defensive_adaptations")
            if not required <= supported:
                raise ValueError(
                    "Verified claims need inspected field-level source support"
                )
        if self.discovery_tags and self.verification_status != "verified":
            raise ValueError(
                "Discovery trait tags require reviewed scientific evidence"
            )
        if not self.image.placeholder and normalize(
            self.image.identified_taxon
        ) != normalize(self.scientific_name):
            raise ValueError(
                "Image identification must match the recorded taxon, not a related species"
            )
        return self


def migrate(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS library_migrations (version INTEGER PRIMARY KEY)"
    )
    version = conn.execute("SELECT MAX(version) FROM library_migrations").fetchone()[0]
    if version is not None and version > 1:
        raise ValueError(
            "Library schema is newer than this application; do not downgrade the database"
        )
    conn.execute("""CREATE TABLE IF NOT EXISTS creature_profiles (
        creature_id INTEGER PRIMARY KEY REFERENCES creatures(id), stable_key TEXT NOT NULL UNIQUE,
        scientific_identity TEXT NOT NULL, record_json TEXT NOT NULL, protected INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pronunciation_assets (
        creature_id INTEGER NOT NULL REFERENCES creatures(id), signature TEXT NOT NULL, cache_key TEXT NOT NULL,
        provider TEXT NOT NULL, voice TEXT NOT NULL, speed REAL NOT NULL, metadata_json TEXT NOT NULL,
        PRIMARY KEY(creature_id, provider, voice, speed))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS library_asset_issues (
        creature_id INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL,
        PRIMARY KEY(creature_id,kind))""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS profiles_scientific_identity ON creature_profiles(scientific_identity)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS creature_game_rules (creature_id INTEGER PRIMARY KEY REFERENCES creatures(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5))"
    )
    conn.execute("INSERT OR IGNORE INTO library_migrations VALUES (1)")


def legacy_record(row, extra=None):
    extra = extra or {}
    key = extra.get("catalog_key") or row["category"] + ":" + re.sub(
        "[^a-z0-9]+", "-", (row["scientific_name"] or row["name"]).lower()
    ).strip("-")
    return CreatureRecord(
        stable_key=key,
        id=row["id"],
        display_name=row["name"],
        scientific_name=row["scientific_name"] or row["name"],
        category=row["category"],
        taxon_group={
            "dinosaur": "dinosaur",
            "shark": "shark",
            "marine_reptile": "marine_reptile",
        }.get(row["category"], "unknown"),
        taxon_rank=extra.get("taxon_rank", "unknown"),
        habitat=row["habitat"]
        if row["habitat"] in {"land", "marine", "semi_aquatic"}
        else "unknown",
        diet=row["diet"],
        description=row["description"],
        pronunciation=Pronunciation(phonetic=row["pronunciation"]),
        image=Image(
            placeholder=True,
            path="/static/assets/"
            + (
                "shark"
                if row["category"] == "shark"
                else "marine_reptile"
                if row["category"] == "marine_reptile"
                else "dinosaur"
            )
            + ".svg",
            creator="Bedtime Battle Stories contributors",
            license="project-placeholder",
            attribution="Original decorative project illustration; not an identified species image",
            modifications="Project SVG illustration",
        ),
        sources=[
            Source(
                id="legacy-reference",
                title="Suggested reference; not inspected",
                url=extra["source_url"],
            )
        ]
        if extra.get("source_url")
        else [],
        review_notes=[
            "Legacy editorial record; scientific claims, measurements, pronunciation and artwork require review."
        ],
    )


def bootstrap(conn):
    migrate(conn)
    conn.row_factory = sqlite3.Row
    extras = {
        r[0]: json.loads(r[1])
        for r in conn.execute("SELECT creature_id,metadata FROM catalog_metadata")
    }
    from .adventure import rating

    for row in conn.execute("SELECT * FROM creatures"):
        conn.execute(
            "INSERT OR IGNORE INTO creature_game_rules VALUES (?,?)",
            (row["id"], rating(dict(row))),
        )
        if conn.execute(
            "SELECT 1 FROM creature_profiles WHERE creature_id=?", (row["id"],)
        ).fetchone():
            continue
        try:
            record = legacy_record(row, extras.get(row["id"]))
        except ValueError:
            conn.execute(
                "INSERT OR REPLACE INTO library_asset_issues VALUES (?,?,?)",
                (
                    row["id"],
                    "metadata_review",
                    "Legacy record needs manual schema/taxonomy review",
                ),
            )
            continue
        conn.execute(
            "INSERT OR IGNORE INTO creature_profiles VALUES (?,?,?,?,0)",
            (
                row["id"],
                record.stable_key,
                normalize(record.scientific_name),
                record.model_dump_json(),
            ),
        )


def verify_image_file(path):
    try:
        from PIL import Image as PILImage
    except ImportError as error:
        raise ValueError(
            "Install requirements-media.txt to validate real image imports"
        ) from error
    try:
        with PILImage.open(path) as image:
            if image.format != "WEBP":
                raise ValueError("Imported image is not WebP")
            image.verify()
    except (OSError, SyntaxError) as error:
        raise ValueError("Invalid/corrupt image: " + str(path)) from error


def validate_records(records, check_files=True):
    parsed = [CreatureRecord.model_validate(r) for r in records]
    for attr in ["stable_key", "scientific_name", "id"]:
        values = [
            normalize(str(getattr(r, attr)))
            for r in parsed
            if getattr(r, attr) is not None
        ]
        if len(values) != len(set(values)):
            raise ValueError("Duplicate " + attr)
    if check_files:
        for r in parsed:
            if not r.image.placeholder:
                for path in [r.image.path, *r.image.variants.values()]:
                    if not local_asset(path).is_file():
                        raise ValueError("Missing image file: " + path)
                    verify_image_file(local_asset(path))
    return parsed


def import_records(conn, records):
    parsed = validate_records(records)
    result = {"inserted": 0, "updated": 0, "protected": 0}
    # Caller supplies a transaction so any collision rolls the complete import back.
    migrate(conn)
    for r in parsed:
        existing = conn.execute(
            "SELECT creature_id,protected FROM creature_profiles WHERE stable_key=?",
            (r.stable_key,),
        ).fetchone()
        if existing and r.id is not None and r.id != existing[0]:
            raise ValueError("Stable ID conflict for " + r.stable_key)
        if existing and existing[1]:
            result["protected"] += 1
            continue
        if existing:
            creature_id = existing[0]
            if r.id is not None and r.id != creature_id:
                raise ValueError("Stable ID conflict for " + r.stable_key)
        else:
            collision = conn.execute(
                "SELECT creature_id FROM creature_profiles WHERE scientific_identity=?",
                (normalize(r.scientific_name),),
            ).fetchone()
            if collision:
                raise ValueError("Scientific identity already has another stable key")
            if (
                r.id is not None
                and conn.execute(
                    "SELECT 1 FROM creatures WHERE id=?", (r.id,)
                ).fetchone()
            ):
                raise ValueError("ID already belongs to an existing creature")
            columns = [
                "name",
                "scientific_name",
                "category",
                "habitat",
                "diet",
                "description",
                "pronunciation",
            ]
            values = [
                r.display_name,
                r.scientific_name,
                r.category,
                r.habitat,
                r.diet,
                r.description,
                r.pronunciation.phonetic,
            ]
            if r.id is not None:
                columns.insert(0, "id")
                values.insert(0, r.id)
            cursor = conn.execute(
                f"INSERT INTO creatures ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )
            creature_id = cursor.lastrowid
            conn.execute("INSERT INTO creature_game_rules VALUES (?,3)", (creature_id,))
        old = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE creature_id=?",
            (creature_id,),
        ).fetchone()
        old_record = json.loads(old[0]) if old else None
        old_pron = old_record["pronunciation"] if old_record else None
        if old_pron and old_pron["status"] == "verified":
            r.pronunciation = Pronunciation.model_validate(old_pron)
        if old_record and not old_record["image"]["placeholder"]:
            r.image = Image.model_validate(old_record["image"])
        r.id = creature_id
        r = CreatureRecord.model_validate(r.model_dump(mode="json"))
        conn.execute(
            """INSERT INTO creature_profiles VALUES (?,?,?,?,?) ON CONFLICT(creature_id) DO UPDATE SET
            scientific_identity=excluded.scientific_identity, record_json=excluded.record_json, protected=excluded.protected""",
            (
                creature_id,
                r.stable_key,
                normalize(r.scientific_name),
                r.model_dump_json(),
                int(r.verification_status == "verified"),
            ),
        )
        if old_pron != r.pronunciation.model_dump(mode="json"):
            conn.execute(
                "DELETE FROM pronunciation_assets WHERE creature_id=?", (creature_id,)
            )
        result["updated" if existing else "inserted"] += 1
    return result


def pronunciation_signature(pronunciation):
    return hashlib.sha256(
        json.dumps(pronunciation, sort_keys=True).encode()
    ).hexdigest()


def audio_options(conn, creature_id, record, cache_root, rows=None):
    if record["pronunciation"]["status"] != "verified":
        return []
    signature = pronunciation_signature(record["pronunciation"])
    result = []
    if rows is None:
        rows = conn.execute(
            "SELECT cache_key,provider,voice,speed,metadata_json FROM pronunciation_assets WHERE creature_id=? AND signature=?",
            (creature_id, signature),
        )
    for r in rows:
        if not re.fullmatch("[0-9a-f]{64}", r[0]):
            continue
        path = Path(cache_root) / "pronunciation" / (r[0] + ".wav")
        try:
            with wave.open(str(path)) as audio:
                if audio.getnframes() <= 0:
                    continue
        except (OSError, EOFError, wave.Error):
            continue
        result.append(
            {
                "url": f"/api/library/pronunciations/{creature_id}/{r[0]}",
                "provider": r[1],
                "voice": r[2],
                "speed": r[3],
                "metadata": json.loads(r[4]),
            }
        )
    return result


def enrich(conn, rows, cache_root):
    rules = dict(conn.execute("SELECT creature_id,rating FROM creature_game_rules"))
    assets = {}
    for r in conn.execute(
        "SELECT creature_id,signature,cache_key,provider,voice,speed,metadata_json FROM pronunciation_assets"
    ):
        assets.setdefault((r[0], r[1]), []).append(r[2:])
    profiles = {
        r[0]: json.loads(r[1])
        for r in conn.execute("SELECT creature_id,record_json FROM creature_profiles")
    }
    result = []
    for row in rows:
        item = dict(row)
        record = profiles.get(item["id"])
        if item["id"] in rules:
            item["gameplay_rating"] = rules[item["id"]]
        if record:
            item["profile"] = record
            if record["verification_status"] == "verified":
                item.update(
                    name=record["display_name"],
                    scientific_name=record["scientific_name"],
                    habitat=record["habitat"],
                    diet=record["diet"],
                    category=record["category"],
                    description=record["description"],
                    review_status="verified",
                )
            item["catalog_key"] = record["stable_key"]
            item["image_reference"] = (
                record["image"]["path"] if not record["image"]["placeholder"] else None
            )
            item["image_variants"] = (
                record["image"]["variants"]
                if not record["image"]["placeholder"]
                else {}
            )
            item["artwork_placeholder"] = record["image"]["placeholder"]
            item["pronunciation_audio_options"] = audio_options(
                conn,
                item["id"],
                record,
                cache_root,
                assets.get(
                    (item["id"], pronunciation_signature(record["pronunciation"])), []
                ),
            )
            item["pronunciation_audio"] = next(
                iter(item["pronunciation_audio_options"]), None
            )
            item["pronunciation_status"] = record["pronunciation"]["status"]
            if record["pronunciation"]["status"] == "verified":
                item["pronunciation"] = record["pronunciation"]["tts_text"]
        result.append(item)
    return result


def audit(conn, cache_root):
    records = [
        json.loads(r[0])
        for r in conn.execute(
            "SELECT record_json FROM creature_profiles ORDER BY creature_id"
        )
    ]
    counts = Counter(r["category"] for r in records)
    verified = Counter(
        r["category"] for r in records if r["verification_status"] == "verified"
    )
    details = []
    images = pronunciations = audio_count = 0
    for r in records:
        issues = []
        if r["verification_status"] != "verified":
            issues.append("scientific_review_needed")
        if r["taxon_rank"] != "species":
            issues.append("not_verified_species_record")
        if r["image"]["placeholder"]:
            issues.append("artwork_review_needed")
        else:
            if local_asset(r["image"]["path"]).is_file():
                images += 1
            else:
                issues.append("image_file_missing")
            for path in r["image"]["variants"].values():
                if not local_asset(path).is_file():
                    issues.append("image_variant_missing")
        if r["pronunciation"]["status"] != "verified":
            issues.append("pronunciation_review_needed")
        else:
            pronunciations += 1
        if audio_options(conn, r["id"], r, cache_root):
            audio_count += 1
        else:
            issues.append("pronunciation_audio_missing")
        if len(r["fun_facts"]) != 3:
            issues.append("three_sourced_facts_needed")
        if r["length"]["minimum"] is None:
            issues.append("length_unknown")
        if r["weight"]["minimum"] is None:
            issues.append("weight_unknown")
        details.append(
            {
                "id": r["id"],
                "stable_key": r["stable_key"],
                "name": r["display_name"],
                "issues": issues,
                "complete": not [
                    i for i in issues if i not in {"length_unknown", "weight_unknown"}
                ],
            }
        )
    identities = Counter(normalize(r["scientific_name"]) for r in records)
    duplicate_species = [
        r["id"] for r in records if identities[normalize(r["scientific_name"])] > 1
    ]
    unprofiled = [
        {"id": r[0], "name": r[1], "issues": ["metadata_schema_review_needed"]}
        for r in conn.execute(
            "SELECT id,name FROM creatures WHERE id NOT IN (SELECT creature_id FROM creature_profiles)"
        )
    ]
    for d in details:
        if d["id"] in duplicate_species:
            d["issues"].append("duplicate_scientific_identity")
            d["complete"] = False
    return {
        "unprofiled": unprofiled,
        "duplicate_species_ids": duplicate_species,
        "counts": dict(counts),
        "verified_counts": {k: verified[k] for k in CATEGORIES},
        "targets": dict(zip(CATEGORIES, [150, 60, 40])),
        "target_gaps": {
            k: max(0, n - verified[k]) for k, n in zip(CATEGORIES, [150, 60, 40])
        },
        "total": len(records),
        "licensed_images": images,
        "placeholders": sum(r["image"]["placeholder"] for r in records),
        "verified_pronunciations": pronunciations,
        "ready_pronunciations": audio_count,
        "complete": sum(d["complete"] for d in details),
        "records": details,
    }
