"""Private, local-only Internet artwork: deterministic evidence screening, no approvals.

License strings are provenance, never permission assertions or selection gates.
No network or Pillow work runs in FastAPI request handlers.
"""

import fcntl
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app import library
from app.images.core import valid_asset

from . import sources
from .network import PoliteClient, SourceUnavailable, atomic
from .store import backup

VERSION = 1
LOG = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def root():
    return Path(
        os.environ.get("BBS_CREATURE_IMAGE_DIR", library.ROOT / "data/creature_images")
    ).resolve()


def connect(db):
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS internet_creature_images (
        creature_id INTEGER PRIMARY KEY, key TEXT NOT NULL, path TEXT NOT NULL,
        root TEXT NOT NULL, sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS internet_image_versions (
        key TEXT PRIMARY KEY, creature_id INTEGER NOT NULL, path TEXT NOT NULL,
        root TEXT NOT NULL, sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS automatic_import_state (
        creature_id INTEGER PRIMARY KEY, scientific_name TEXT NOT NULL,
        science_complete INTEGER NOT NULL DEFAULT 0, result_json TEXT NOT NULL, updated TEXT NOT NULL);
    """)
    return conn


def registered(conn):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='internet_creature_images'"
    ).fetchone():
        return {}
    columns = ("creature_id", "key", "path", "root", "sha256", "metadata_json")
    return {
        row[0]: dict(zip(columns, row))
        for row in conn.execute("SELECT * FROM internet_creature_images")
    }


def render(asset):
    return {
        **json.loads(asset["metadata_json"]),
        "url": f"/api/library/images/{asset['creature_id']}/{asset['key']}",
    }


def coverage(db):
    with sqlite3.connect(db) as conn:
        assets = registered(conn)
        profiles = [
            json.loads(r[0])
            for r in conn.execute("SELECT record_json FROM creature_profiles")
        ]
        imported = sum(
            bool(
                a
                and valid_asset(a)
                and json.loads(a["metadata_json"]).get("scientific_name")
                == r["scientific_name"]
            )
            for r in profiles
            if (a := assets.get(r["id"]))
        )
        # Include preserved licensed and generated images via the same renderer as the app.
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM creatures ORDER BY id").fetchall()
        visible = library.enrich(
            conn,
            rows,
            Path(os.environ.get("BBS_AUDIO_CACHE", library.ROOT / "data/audio_cache")),
        )
        return {
            "total": len(profiles),
            "internet_images": imported,
            "images_retained": sum(
                c.get("artwork_placeholder") is False
                and c.get("image_kind") != "internet"
                for c in visible
            ),
            "placeholders_remaining": sum(
                c.get("artwork_placeholder") is not False for c in visible
            ),
        }


def contains(text, name):
    return bool(
        re.search(
            r"(?<!\w)" + re.escape(library.normalize(name)) + r"(?!\w)",
            library.normalize(text),
        )
    )


def candidate(info, page, record):
    ext = info.get("extmetadata", {})
    if not isinstance(ext, dict):
        raise ValueError("Invalid image metadata object")
    text = lambda field: sources.plain(ext.get(field, {}).get("value", ""))
    name = record["scientific_name"]
    title = page.get("title", "")
    description = text("ImageDescription")
    categories = text("Categories")
    normalized = library.normalize(description)
    # Search results alone never establish identity. Require a caption naming
    # the taxon, corroborated by the file title/category or a subject-led caption.
    leading = re.match(
        r"^(?:(?:life |scientific )?(?:reconstruction|restoration|paleoart|photograph|photo|illustration)(?: of)?[ :–-]+)?"
        + re.escape(library.normalize(name))
        + r"(?!\w)",
        normalized,
    )
    corroborated = contains(title.replace("_", " "), name) or contains(
        categories.replace("_", " "), name
    )
    reasons = []
    from urllib.parse import urlsplit

    source_url = urlsplit(info.get("descriptionurl") or "")
    if (
        source_url.scheme != "https"
        or not source_url.hostname
        or source_url.username
        or source_url.password
    ):
        reasons.append("Original HTTPS source page is missing or invalid")
    if not contains(description, name) or not (leading or corroborated):
        reasons.append(
            "Exact taxon identity is not established by caption and subject metadata"
        )
    if re.search(
        r"\b(vs|versus|comparison|compared|possibly|probably|unidentified|unknown species|hybrid)\b",
        normalized,
    ):
        reasons.append("Ambiguous or comparative taxon identification")
    for other in record.get("_other_taxa", []):
        if (
            library.normalize(other) != library.normalize(name)
            and contains(title.replace("_", " "), other)
            and not contains(title.replace("_", " "), name)
        ):
            reasons.append("File title identifies another creature")
            break
    combined = " ".join((title, description, text("ObjectName")))
    if re.search(
        r"\b(jurassic park|jurassic world|godzilla|pokemon|cartoon|toy|logo|advertisement|blood|gore|fishing)\b",
        combined,
        re.I,
    ):
        reasons.append("Fictional, commercial, graphic or child-unsuitable subject")
    width, height = info.get("width", 0), info.get("height", 0)
    if width and height and (max(width, height) < 320 or min(width, height) < 160):
        reasons.append("Low-resolution thumbnail")
    living = record["category"] == "shark" and record.get("modern_status") != "extinct"
    reconstruction = bool(
        re.search(
            r"\b(paleoart|reconstruction|restoration|illustration)\b", combined, re.I
        )
    )
    fossil = bool(
        re.search(
            r"\b(fossil|skeleton|skull|tooth|teeth|cast|mounted)\b", combined, re.I
        )
    )
    if living and (
        reconstruction or re.search(r"\b(diagram|drawing|painting)\b", combined, re.I)
    ):
        reasons.append("Living shark requires a photograph")
    photo = bool(
        re.search(r"\b(photo|photograph|photographed|underwater)\b", combined, re.I)
        or info.get("mime") == "image/jpeg"
    )
    if living and not photo:
        reasons.append("Photograph is not established")
    identity = 98 if leading and corroborated else 95 if leading else 92
    quality = 35 if living and photo or not living and reconstruction else 0
    quality -= 25 if fossil else 0
    quality += (
        8
        if re.search(
            r"full[- ]body|entire (?:animal|body)|lateral view", combined, re.I
        )
        else 0
    )
    quality += min(20, int(max(width, height) / 100))
    quality -= (
        15
        if re.search(r"\b(chart|diagram|map|labelled|labeled|text)\b", combined, re.I)
        else 0
    )
    license = text("LicenseShortName") or None
    return {
        "title": title,
        "page_id": page.get("pageid"),
        "description": description,
        "scientific_name": name,
        "identified_taxon": name,
        "identity_confidence": identity,
        "identity_evidence": "Exact caption taxon with subject metadata; automated, not visual verification",
        "quality_score": quality,
        "width": width,
        "height": height,
        "creator": text("Artist") or None,
        "license": license,
        "license_url": text("LicenseUrl") or None,
        "attribution": text("Attribution") or text("Credit") or text("Artist") or None,
        "original_source_url": info.get("descriptionurl"),
        "download_url": info.get("url"),
        "retrieved_on": now(),
        "supported": not reasons,
        "issues": reasons,
        "open_license": bool(
            license
            and re.fullmatch(
                r"CC[ -]BY(?:[ -]SA)?(?:[ -][1-4](?:\.0)?)?|CC0(?: 1\.0)?|public domain",
                license,
                re.I,
            )
        ),
        "selection_version": VERSION,
    }


def discover(client, record, use_wikidata=False):
    """Bounded multiple searches and category pagination, independent of Wikidata."""
    name = record["scientific_name"]
    aliases = [name, record.get("display_name", name), *record.get("synonyms", [])]
    aliases = list(
        dict.fromkeys(a for a in aliases if isinstance(a, str) and a.strip())
    )[:6]
    queries = [f'"{a}"' for a in aliases]
    suffixes = (
        ["wildlife photograph", "underwater"]
        if record["category"] == "shark" and record.get("modern_status") != "extinct"
        else [
            "reconstruction",
            "paleoart",
            "life restoration",
            "illustration",
            "skeleton reconstruction",
        ]
    )
    queries += [f'"{name}" {suffix}' for suffix in suffixes]
    found, diagnostics = {}, []

    def add(result):
        pages = result.get("query", {}).get("pages", {})
        for page in pages.values() if isinstance(pages, dict) else pages:
            info = next(iter(page.get("imageinfo", [])), None)
            if not info or not info.get("url"):
                continue
            key = info["url"]
            if key not in found:
                found[key] = candidate(info, page, record)

    def paged(params):
        continuation = {}
        for _ in range(3):
            data = client.json(
                sources.COMMONS,
                {
                    **params,
                    **continuation,
                    "action": "query",
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata",
                    "format": "json",
                },
            )
            add(data)
            continuation = data.get("continue", {})
            if not continuation or len(found) >= 160:
                break

    for query in queries:
        try:
            paged(
                {
                    "generator": "search",
                    "gsrsearch": query,
                    "gsrnamespace": 6,
                    "gsrlimit": 50,
                }
            )
        except (SourceUnavailable, ValueError, KeyError) as error:
            diagnostics.append(str(error))
            # Access denial is final for this source; never try to disguise it.
            if any(
                word in str(error)
                for word in ("403", "401", "proxy/network", "robots.txt")
            ):
                return list(found.values()), diagnostics
        if len(found) >= 160:
            break
    for title in dict.fromkeys(
        [name, record.get("display_name", name), record.get("subcategory") or name]
    ):
        if len(found) >= 160:
            break
        try:
            paged(
                {
                    "generator": "categorymembers",
                    "gcmtitle": "Category:" + title,
                    "gcmnamespace": 6,
                    "gcmtype": "file",
                    "gcmlimit": 50,
                }
            )
        except (SourceUnavailable, ValueError, KeyError) as error:
            diagnostics.append("Commons category: " + str(error))
    if use_wikidata:
        try:
            qid = sources.taxon_entity(client, name)
            entity = (
                client.json(
                    sources.WIKIDATA,
                    {
                        "action": "wbgetentities",
                        "ids": qid,
                        "props": "claims",
                        "format": "json",
                    },
                )
                .get("entities", {})
                .get(qid, {})
            )
            titles = [
                s.get("mainsnak", {}).get("datavalue", {}).get("value")
                for s in entity.get("claims", {}).get("P18", [])
            ]
            for title in titles[:5]:
                if isinstance(title, str):
                    paged({"titles": "File:" + title})
        except (SourceUnavailable, ValueError, KeyError) as error:
            diagnostics.append("Optional Wikidata: " + str(error))
    return list(found.values())[:160], diagnostics


def gbif_images(client, record):
    """Structured exact-species occurrence photographs from supported media hosts."""
    if record["category"] != "shark" or record.get("modern_status") == "extinct":
        return [], []
    try:
        match = client.json(
            sources.GBIF, {"name": record["scientific_name"], "strict": "true"}
        )
        _, identity = sources.gbif_match(match, record["scientific_name"])
        data = client.json(
            "https://api.gbif.org/v1/occurrence/search",
            {
                "taxon_key": identity["usageKey"],
                "media_type": "StillImage",
                "limit": 50,
            },
        )
        result = []
        from urllib.parse import urlsplit

        from .network import HOSTS

        for occurrence in data.get("results", []):
            actual = occurrence.get("species") or occurrence.get("scientificName", "")
            if library.normalize(actual) != library.normalize(
                record["scientific_name"]
            ):
                continue
            for media in occurrence.get("media", []):
                url = media.get("identifier", "")
                if (
                    media.get("type") != "StillImage"
                    or urlsplit(url).hostname not in HOSTS
                ):
                    continue
                info = {
                    "url": url,
                    "descriptionurl": "https://www.gbif.org/occurrence/"
                    + str(occurrence["key"]),
                    "mime": media.get("format"),
                    "extmetadata": {
                        key: {"value": value or ""}
                        for key, value in {
                            "ImageDescription": record["scientific_name"]
                            + " photograph (structured GBIF occurrence identity)",
                            "Artist": media.get("creator"),
                            "LicenseShortName": media.get("license"),
                            "Credit": media.get("rightsHolder"),
                        }.items()
                    },
                }
                item = candidate(
                    info, {"title": record["scientific_name"] + " photograph"}, record
                )
                item["identity_evidence"] = (
                    "GBIF exact species match and occurrence species field; automated, not visual verification"
                )
                result.append(item)
        return result, []
    except (SourceUnavailable, ValueError, KeyError) as error:
        return [], ["GBIF images: " + str(error)]


def ranked(candidates):
    # Rights are only the last tie-breaker, never an eligibility requirement.
    return sorted(
        (c for c in candidates if c["supported"]),
        key=lambda c: (
            -c["identity_confidence"],
            -c["quality_score"],
            -int(c.get("open_license", False)),
            c.get("download_url") or "",
        ),
    )


def convert(content):
    from PIL import Image, ImageOps

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > 25_000_000:
                    raise ValueError("Image exceeds safe decoded-pixel limits")
                if min(source.size) < 160 or max(source.size) < 320:
                    raise ValueError("Downloaded image is too small")
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((768, 768))
                output = io.BytesIO()
                image.save(output, format="WEBP", quality=85, method=6)
                return output.getvalue(), image.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Image exceeds safe decoded-pixel limits") from error


def install(db, record, selected, content, directory=None):
    """Only validated pixels and identity reach the transaction; no approval DTO."""
    if (
        not selected.get("supported")
        or selected.get("issues")
        or not selected.get("identity_evidence")
        or selected.get("scientific_name") != record["scientific_name"]
        or selected.get("identified_taxon") != record["scientific_name"]
    ):
        raise ValueError("Image identity validation failed")
    webp, dimensions = convert(content)
    digest = hashlib.sha256(webp).hexdigest()
    directory = Path(directory or root()).resolve()
    metadata = {k: v for k, v in selected.items() if not k.startswith("_")}
    metadata.update(
        image_kind="internet",
        installed_on=now(),
        dimensions=dimensions,
        modifications="Converted to mobile WebP; resized to fit 768px",
        private_local_only=True,
    )
    identity = {
        "creature_id": record["id"],
        "sha256": digest,
        "source": selected.get("original_source_url"),
        "download": selected.get("download_url"),
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    path = directory / (digest + ".webp")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        atomic(path, webp)
    asset = (record["id"], key, str(path), str(directory), digest, json.dumps(metadata))
    if not valid_asset(
        dict(
            zip(
                ("creature_id", "key", "path", "root", "sha256", "metadata_json"), asset
            )
        )
    ):
        raise ValueError("Published WebP validation failed")
    with connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT record_json FROM creature_profiles WHERE creature_id=?",
            (record["id"],),
        ).fetchone()
        if (
            not current
            or json.loads(current[0])["scientific_name"] != record["scientific_name"]
        ):
            raise ValueError(
                "Creature identity changed during download; image not installed"
            )
        old = conn.execute(
            "SELECT * FROM internet_creature_images WHERE creature_id=?",
            (record["id"],),
        ).fetchone()
        if (
            old
            and valid_asset(dict(old))
            and json.loads(old["metadata_json"])["identity_confidence"]
            > selected["identity_confidence"]
        ):
            return False
        canonical = json.loads(current[0])["image"]
        if library.canonical_image_available(canonical):
            floor = (
                100 if canonical.get("approval_method", "manual") == "manual" else 95
            )
            if selected["identity_confidence"] < floor:
                return False
        conn.execute(
            "INSERT OR REPLACE INTO internet_image_versions(creature_id,key,path,root,sha256,metadata_json) VALUES (?,?,?,?,?,?)",
            asset,
        )
        conn.execute(
            "INSERT OR REPLACE INTO internet_creature_images VALUES (?,?,?,?,?,?)",
            asset,
        )
        conn.execute(
            "UPDATE creatures SET image_reference=? WHERE id=?",
            (f"/api/library/images/{record['id']}/{key}", record["id"]),
        )
    return True


def automatic_pronunciation(db, record, guidance):
    from .persistence import persist

    if not guidance or record["pronunciation"]["status"] == "verified":
        return False
    value = {
        k: v for k, v in guidance.items() if k in library.Pronunciation.model_fields
    }
    verification = guidance.get("source_verification", {})
    if verification.get("status") == "verified":
        value.update(
            status="verified",
            verified_by=verification["verified_by"],
            checked_on=verification["checked_on"],
        )
    # Supplied unverified guidance stays explicitly unverified; no fabricated stamps.
    updated = json.loads(json.dumps(record))
    updated["pronunciation"] = library.Pronunciation.model_validate(value).model_dump(
        mode="json"
    )
    return persist(db, updated, record, operation="automatic_pronunciation")["changed"]


def execute(
    db,
    folder,
    pilot=None,
    refresh=False,
    dry_run=False,
    client=None,
    offline=False,
    image_references=None,
    pronunciation_references=None,
    pronunciation_index=None,
    museum_pages=False,
    use_wikidata=False,
    progress=print,
):
    from .runner import PILOT, apply_supported, collect, current_record

    folder = Path(folder)
    own = client is None
    client = client or PoliteClient(folder / "http", refresh=refresh)
    report = {
        "processed": 0,
        "images_discovered": 0,
        "images_installed": 0,
        "images_retained": 0,
        "failed_downloads": 0,
        "science_updated": 0,
        "pronunciations_updated": 0,
        "dry_run": dry_run,
        "respect_robots": client.respect_robots,
        "results": [],
        "errors": [],
    }
    folder.mkdir(parents=True, exist_ok=True)
    lock = Path(db).resolve().with_suffix(".creature-import.lock").open("a")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another automatic importer is already running") from error
        if not dry_run:
            backup(db)
            with connect(db):
                pass
        with sqlite3.connect(db) as conn:
            records = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT record_json FROM creature_profiles ORDER BY creature_id"
                )
            ]
        if pilot:
            records = sorted(
                (r for r in records if r["category"] == "dinosaur"),
                key=lambda r: (
                    PILOT.index(r["display_name"])
                    if r["display_name"] in PILOT
                    else 1000,
                    r["id"],
                ),
            )[:pilot]
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            visible = library.enrich(
                conn,
                conn.execute("SELECT * FROM creatures").fetchall(),
                Path(
                    os.environ.get("BBS_AUDIO_CACHE", library.ROOT / "data/audio_cache")
                ),
            )
        science_input_hash = hashlib.sha256(
            json.dumps(
                {
                    "pronunciation_references": pronunciation_references,
                    "pronunciation_index": pronunciation_index,
                    "museum_pages": museum_pages,
                    "offline": offline,
                    "respect_robots": client.respect_robots,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        available = {r["id"] for r in visible if r.get("artwork_placeholder") is False}
        names = [r["scientific_name"] for r in records]
        progress("CREATURE IMAGE IMPORT", flush=True)
        for n, record in enumerate(records, 1):
            row = {
                "id": record["id"],
                "name": record["display_name"],
                "scientific_name": record["scientific_name"],
                "candidates_discovered": 0,
                "candidates_evaluated": 0,
                "image_downloaded": False,
                "image_installed": False,
                "issues": [],
                "science_input_hash": science_input_hash,
            }
            progress(f"[{n}/{len(records)}] {record['display_name']}", flush=True)
            with sqlite3.connect(db) as conn:
                old = registered(conn).get(record["id"])
                state = None
                if not dry_run:
                    state = conn.execute(
                        "SELECT * FROM automatic_import_state WHERE creature_id=?",
                        (record["id"],),
                    ).fetchone()
            science_done = bool(
                state
                and state[1] == record["scientific_name"]
                and state[2]
                and json.loads(state[3]).get("science_input_hash") == science_input_hash
            )
            if not science_done or refresh:
                try:
                    proposal = collect(
                        client,
                        record,
                        folder,
                        True,
                        pronunciation_index,
                        museum_pages,
                        pronunciation_references,
                        source_images=False,
                        offline=offline,
                    )
                    row["science_issues"] = proposal["issues"]
                    if not dry_run:
                        report["science_updated"] += int(
                            apply_supported(db, record, proposal)
                        )
                        record = current_record(db, record["stable_key"])
                        report["pronunciations_updated"] += int(
                            automatic_pronunciation(
                                db, record, proposal.get("pronunciation")
                            )
                        )
                        record = current_record(db, record["stable_key"])
                    science_done = bool(proposal["evidence"])
                except (
                    SourceUnavailable,
                    ValueError,
                    OSError,
                    sqlite3.Error,
                    KeyError,
                ) as error:
                    science_done = False
                    row["science_issues"] = [str(error)]
                    LOG.exception(
                        "Science import failed creature=%s operation=science",
                        record["display_name"],
                    )
            good = bool(
                old
                and valid_asset(old)
                and json.loads(old["metadata_json"]).get("scientific_name")
                == record["scientific_name"]
            )
            if good and not refresh:
                row["retained"] = True
            else:
                try:
                    supplied = (image_references or {}).get(
                        library.normalize(record["scientific_name"])
                    )
                    if supplied:
                        candidates = []
                        for item in supplied:
                            chosen = candidate(item["info"], item["page"], record)
                            chosen.update(
                                local_file=item["image_path"],
                                supplied_sha256=item["image_sha256"],
                                retrieved_on=item["retrieved_on"],
                            )
                            credit = item.get("credit")
                            if credit and (
                                library.normalize(credit["identified_taxon"])
                                != library.normalize(record["scientific_name"])
                                or credit["identity_status"] != "supported"
                            ):
                                chosen["supported"] = False
                                chosen["issues"].append(
                                    "Supplied taxon identity is uncertain or mismatched"
                                )
                            candidates.append(chosen)
                        diagnostics = []
                    elif offline:
                        candidates, diagnostics = (
                            [],
                            ["Offline mode: no supplied image candidates"],
                        )
                    else:
                        candidates, diagnostics = discover(
                            client, {**record, "_other_taxa": names}, use_wikidata
                        )
                        if record["category"] == "shark":
                            alternatives, notes = gbif_images(client, record)
                            diagnostics += notes
                            seen = {c.get("download_url") for c in candidates}
                            candidates += [
                                c
                                for c in alternatives
                                if c.get("download_url") not in seen
                            ]
                    row.update(
                        candidates_discovered=len(candidates),
                        candidates_evaluated=len(candidates),
                    )
                    row["issues"].extend(diagnostics)
                    row["eligible_candidates"] = sum(c["supported"] for c in candidates)
                    row["rejection_reasons"] = dict(
                        Counter(reason for c in candidates for reason in c["issues"])
                    )
                    if not dry_run:
                        diagnostic = (
                            folder / "candidates" / (str(record["id"]) + ".json")
                        )
                        atomic(diagnostic, json.dumps(candidates, indent=2).encode())
                        row["candidate_report"] = str(diagnostic.relative_to(folder))
                    floor = (
                        json.loads(old["metadata_json"])["identity_confidence"]
                        if good
                        else 0
                    )
                    if library.canonical_image_available(record["image"]):
                        floor = max(
                            floor,
                            100
                            if record["image"].get("approval_method", "manual")
                            == "manual"
                            else 95,
                        )
                    for chosen in ranked(candidates):
                        if chosen["identity_confidence"] < floor:
                            continue
                        row["selected"] = chosen["title"]
                        if dry_run:
                            break
                        try:
                            if chosen.get("local_file"):
                                local = Path(chosen["local_file"])
                                if local.stat().st_size > 20_000_000:
                                    raise ValueError(
                                        "Supplied image exceeds size limit"
                                    )
                                content = local.read_bytes()
                                if (
                                    hashlib.sha256(content).hexdigest()
                                    != chosen["supplied_sha256"]
                                ):
                                    raise ValueError(
                                        "Supplied image changed during acquisition"
                                    )
                            else:
                                response = client.get(
                                    chosen["download_url"], limit=20_000_000
                                )
                                mime = (
                                    response.headers.get("content-type", "")
                                    .split(";")[0]
                                    .strip()
                                )
                                if (
                                    mime
                                    and not mime.startswith("image/")
                                    and mime != "application/octet-stream"
                                ):
                                    raise ValueError("HTTP response is not an image")
                                content = response.content
                            row["image_downloaded"] = True
                            row["image_installed"] = install(
                                db, record, chosen, content
                            )
                            if row["image_installed"]:
                                report["images_installed"] += 1
                                break
                        except (
                            SourceUnavailable,
                            ValueError,
                            OSError,
                            sqlite3.Error,
                            ImportError,
                        ) as error:
                            report["failed_downloads"] += 1
                            row["issues"].append(
                                "Image download/conversion/database update failed: "
                                + str(error)
                            )
                            LOG.exception(
                                "Image import failed creature=%s operation=install source=%s",
                                record["display_name"],
                                chosen.get("download_url"),
                            )
                    if not row.get("selected"):
                        row["issues"].append(
                            "Existing higher-confidence artwork retained"
                            if any(c["supported"] for c in candidates) and floor > 0
                            else "No suitable candidates found; existing artwork preserved"
                        )
                except (
                    SourceUnavailable,
                    ValueError,
                    OSError,
                    sqlite3.Error,
                    KeyError,
                ) as error:
                    row["issues"].append(str(error))
                    LOG.exception(
                        "Image discovery failed creature=%s operation=discovery",
                        record["display_name"],
                    )
            row["image_available"] = row["image_installed"] or record["id"] in available
            report["images_retained"] += int(
                not row["image_installed"] and row["image_available"]
            )
            report["processed"] += 1
            report["images_discovered"] += row["candidates_discovered"]
            report["results"].append(row)
            if not dry_run:
                with connect(db) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO automatic_import_state VALUES (?,?,?,?,?)",
                        (
                            record["id"],
                            record["scientific_name"],
                            int(science_done),
                            json.dumps(row),
                            now(),
                        ),
                    )
                atomic(
                    folder / "latest-image-report.json",
                    json.dumps(
                        {
                            **{k: v for k, v in report.items() if k != "results"},
                            "last_result": row,
                        },
                        indent=2,
                    ).encode(),
                )
            progress(
                f"Candidates discovered: {row['candidates_discovered']} · evaluated: {row['candidates_evaluated']}\nSelected: {row.get('selected', 'retained or unavailable')}\nImage downloaded: {'Yes' if row['image_downloaded'] else 'No'} · installed: {'Yes' if row['image_installed'] else 'No'}",
                flush=True,
            )
        report["unavailable_images"] = sum(
            not row["image_available"] for row in report["results"]
        )
        report["coverage"] = coverage(db)
        report["http_requests"] = client.requests
        report["http_cache_hits"] = client.cache_hits
        report["access_log"] = list(client.events)
        progress(
            "IMPORT SUMMARY\n"
            + json.dumps(
                {k: v for k, v in report.items() if k not in {"results", "access_log"}},
                indent=2,
            ),
            flush=True,
        )
        return report
    finally:
        lock.close()
        if own:
            client.close()
