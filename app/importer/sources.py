"""Exact-match source adapters. Imported evidence is never called manual verification."""

from datetime import date
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import quote
from app.library import normalize
from .network import SourceUnavailable

PBDB = "https://paleobiodb.org/data1.2/taxa/list.json"
GBIF = "https://api.gbif.org/v1/species/match"
COMMONS = "https://commons.wikimedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.headings = []
        self.in_heading = False
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self.skip += 1
        if tag in {"h1", "h2", "h3"}:
            self.in_heading = True
            self.headings.append("")
        if tag in {"p", "div", "dt", "dd", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"h1", "h2", "h3"}:
            self.in_heading = False
        if tag in {"p", "div", "dt", "dd", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.in_heading and self.headings:
                self.headings[-1] += data

    @property
    def text(self):
        return "\n".join(
            " ".join(line.split())
            for line in "".join(self.parts).splitlines()
            if line.strip()
        )


def plain(html):
    parser = Text()
    parser.feed(unescape(html or ""))
    return " ".join(parser.text.split())


def pbdb_match(data, name):
    records = data.get("records", [])
    exact = [
        r for r in records if normalize(r.get("taxon_name", "")) == normalize(name)
    ]
    accepted = [
        r
        for r in exact
        if not r.get("difference")
        and normalize(r.get("accepted_name") or r["taxon_name"]) == normalize(name)
    ]
    if len(accepted) != 1:
        raise SourceUnavailable(
            "PBDB exact accepted taxon is absent or ambiguous; manual taxonomy review required"
        )
    r = accepted[0]
    rank = str(r.get("taxon_rank", "")).lower()
    if rank not in {"genus", "species"}:
        raise SourceUnavailable("PBDB rank does not identify a genus/species")
    patch = {"taxon_rank": rank}
    if r.get("parent_name"):
        patch["subcategory"] = r["parent_name"]
    intervals = list(
        dict.fromkeys(x for x in [r.get("early_interval"), r.get("late_interval")] if x)
    )
    if intervals:
        patch["time_period"] = " to ".join(intervals)
    # No masses, sizes, diets, habitats or biological abilities are inferred.
    return patch, {
        "taxon_no": r.get("taxon_no") or r.get("orig_no"),
        "accepted_name": r.get("accepted_name") or r["taxon_name"],
    }


def gbif_match(data, name):
    if (
        data.get("matchType") != "EXACT"
        or data.get("status") != "ACCEPTED"
        or normalize(data.get("canonicalName", "")) != normalize(name)
        or data.get("rank") not in {"GENUS", "SPECIES"}
        or data.get("kingdom") != "Animalia"
        or data.get("confidence", 0) < 99
    ):
        raise SourceUnavailable("GBIF exact accepted animal identity not established")
    return {"taxon_rank": data["rank"].lower()}, {
        "usageKey": data.get("usageKey"),
        "accepted_name": data["canonicalName"],
    }


def science(client, record):
    name = record["scientific_name"]
    errors = []
    evidence = []
    patch = {}
    adapters = [
        (
            "PBDB",
            PBDB,
            {"name": name, "vocab": "pbdb", "show": "attr,app,parent", "limit": 20},
            pbdb_match,
        )
    ]
    if record["category"] == "shark":
        adapters.insert(0, ("GBIF", GBIF, {"name": name, "strict": "true"}, gbif_match))
    for label, url, params, parser in adapters:
        try:
            result = client.get(url, params)
            fields, identity = parser(result.json(), name)
            patch.update(fields)
            evidence.append(
                {
                    "id": label.lower(),
                    "title": label + " accepted taxonomy/recorded fossil interval",
                    "url": str(result.request.url),
                    "publisher": label,
                    "supports": ["taxonomy"]
                    + (["time_period"] if fields.get("time_period") else []),
                    "retrieved_on": date.today().isoformat(),
                    "identity": identity,
                }
            )
            break
        except (SourceUnavailable, ValueError, KeyError) as error:
            errors.append(str(error))
    return patch, evidence, errors


def parse_pronunciation(html, spoken_name):
    page = Text()
    page.feed(html)
    # A dedicated taxon heading is required; never take another taxon's guide
    # from an index just because a search result or filename matches.
    headings = [normalize(h) for h in page.headings]
    if normalize(spoken_name) not in headings:
        raise SourceUnavailable("Pronunciation page has no exact creature heading")
    lines = page.text.splitlines()
    for i, line in enumerate(lines):
        if not re.search(
            r"\b(pronunciation|pronounced|say it|how to say it)\b", line, re.I
        ):
            continue
        candidates = [
            re.sub(
                r"^.*?(?:pronunciation|pronounced|say it|how to say it)\s*[:–-]?\s*",
                "",
                line,
                flags=re.I,
            )
        ] + lines[i + 1 : i + 3]
        for guide in candidates:
            guide = guide.strip().strip('"')
            if not 3 <= len(guide) <= 100 or not re.fullmatch(
                r"[A-Za-zɑɐɒæəɛɪʊɔɜɚθðʃʒŋˈˌ'() –-]+", guide
            ):
                continue
            if "-" not in guide and "ˈ" not in guide:
                continue
            stress = re.findall(r"\b[A-Z]{2,}\b", guide)
            return {
                "phonetic": guide,
                "stress": ", ".join(stress)
                or ("IPA stress mark" if "ˈ" in guide else None),
                "tts_text": guide.lower().replace("-", " ").replace("–", " "),
                "alternatives": [],
            }
    raise SourceUnavailable("No unambiguous textual pronunciation guidance found")


def pronunciation(client, record, index=None):
    urls = list((index or {}).get(record["display_name"], []))
    if record["category"] == "dinosaur":
        urls.insert(
            0,
            "https://www.nhm.ac.uk/discover/dino-directory/"
            + quote(record["display_name"].lower(), safe="")
            + ".html",
        )
    errors = []
    for url in dict.fromkeys(urls):
        try:
            response = client.get(url)
            pron = parse_pronunciation(response.text, record["display_name"])
            return {
                **pron,
                "source_url": str(response.request.url),
                "status": "unverified",
                "retrieved_on": date.today().isoformat(),
            }, errors
        except (SourceUnavailable, ValueError) as error:
            errors.append(str(error))
    return None, errors or [
        "No configured authoritative pronunciation source; manual review needed"
    ]


def taxon_entity(client, name):
    search = client.json(
        WIKIDATA,
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "limit": 5,
            "format": "json",
        },
    )
    ids = [
        r["id"]
        for r in search.get("search", [])
        if re.fullmatch(r"Q\d+", r.get("id", ""))
    ]
    if not ids:
        raise SourceUnavailable("No Wikidata identity candidate")
    entities = client.json(
        WIKIDATA,
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "claims",
            "format": "json",
        },
    ).get("entities", {})
    exact = []
    for qid, data in entities.items():
        names = [
            s.get("mainsnak", {}).get("datavalue", {}).get("value")
            for s in data.get("claims", {}).get("P225", [])
        ]
        ranks = [
            s.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            for s in data.get("claims", {}).get("P105", [])
        ]
        if any(
            isinstance(n, str) and normalize(n) == normalize(name) for n in names
        ) and any(r in {"Q34740", "Q7432"} for r in ranks):
            exact.append(qid)
    if len(exact) != 1:
        raise SourceUnavailable(
            "Wikidata scientific identity is ambiguous or unsupported"
        )
    return exact[0]


def image_candidate(info, page, depicts, qid, name, living):
    ext = info.get("extmetadata", {})
    value = lambda k: plain(ext.get(k, {}).get("value", ""))
    label = value("LicenseShortName")
    licenses = {
        "CC0": "CC0-1.0",
        "CC0 1.0": "CC0-1.0",
        "Public domain": "Public-Domain",
        "CC BY 4.0": "CC-BY-4.0",
        "CC BY-SA 4.0": "CC-BY-SA-4.0",
        "CC BY 3.0": "CC-BY-3.0",
        "CC BY-SA 3.0": "CC-BY-SA-3.0",
    }
    license = licenses.get(label)
    description = value("ImageDescription")
    combined = description + " " + value("ObjectName")
    reason = []
    if qid not in depicts:
        reason.append("Structured depicts does not match the exact taxon entity")
    if not re.search(
        r"(?<!\w)" + re.escape(normalize(name)) + r"(?!\w)", normalize(combined)
    ):
        reason.append("Taxon is not identified in descriptive metadata")
    if re.search(
        r"\b(fossil|skeleton|skull|tooth|teeth|cast|mounted)\b", combined, re.I
    ):
        reason.append("Fossil/anatomical image is not a primary living reconstruction")
    if living and not re.search(
        r"\b(photo|photograph|underwater|photographed)\b", combined, re.I
    ):
        reason.append("Living-animal photograph not established")
    if not living and not re.search(
        r"\b(paleoart|reconstruction|restoration)\b", combined, re.I
    ):
        reason.append("Life reconstruction not established")
    if not license:
        reason.append("Reuse license not supported")
    creator = value("Artist")
    license_url = (
        ext.get("LicenseUrl", {}).get("value", "").replace("http://", "https://", 1)
    )
    if not creator or not license_url.startswith("https://creativecommons.org/"):
        reason.append("Creator/license declaration incomplete")
    return {
        "title": page.get("title"),
        "page_id": page.get("pageid"),
        "description": description,
        "creator": creator,
        "license": license,
        "license_url": license_url,
        "original_source_url": (info.get("descriptionurl") or "").replace(
            "http://", "https://", 1
        ),
        "download_url": info.get("url"),
        "attribution": creator
        + " · "
        + label
        + " · "
        + str(info.get("descriptionurl", "")),
        "identified_taxon": name,
        "taxon_entity": qid,
        "supported": not reason,
        "issues": reason,
        "review_status": "pending",
    }


def images(client, record):
    name = record["scientific_name"]
    qid = taxon_entity(client, name)
    result = client.json(
        COMMONS,
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": f'"{name}"',
            "gsrnamespace": 6,
            "gsrlimit": 5,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "format": "json",
        },
    )
    candidates = []
    for page in result.get("query", {}).get("pages", {}).values():
        info = next(iter(page.get("imageinfo", [])), None)
        if not info:
            continue
        media = client.json(
            COMMONS,
            {
                "action": "wbgetentities",
                "ids": "M" + str(page["pageid"]),
                "props": "claims",
                "format": "json",
            },
        )
        entity = media.get("entities", {}).get("M" + str(page["pageid"]), {})
        statements = entity.get("statements", entity.get("claims", {}))
        depicts = {
            s.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            for s in statements.get("P180", [])
        }
        candidates.append(
            image_candidate(
                info,
                page,
                depicts,
                qid,
                name,
                record["category"] == "shark"
                and record.get("modern_status") != "extinct",
            )
        )
    return candidates


def discover(client, category, limit):
    clades = {
        "dinosaur": ["Dinosauria"],
        "shark": ["Selachimorpha"],
        "marine_reptile": ["Mosasauroidea", "Plesiosauria", "Ichthyopterygia"],
    }
    rank = "species" if category == "shark" else "genus"
    result = []
    for clade in clades[category]:
        data = client.json(
            PBDB,
            {
                "base_name": clade,
                "rank": rank,
                "taxon_status": "accepted",
                "vocab": "pbdb",
                "show": "attr,parent",
                "limit": min(500, limit * 3),
            },
        )
        for r in data.get("records", []):
            name = r.get("taxon_name", "")
            if (
                r.get("difference")
                or r.get("taxon_rank") != rank
                or not name
                or normalize(r.get("accepted_name") or name) != normalize(name)
            ):
                continue
            result.append(
                {
                    "scientific_name": name,
                    "display_name": name,
                    "category": category,
                    "taxon_rank": rank,
                    "taxon_group": category,
                    "source_clade": clade,
                    "source_url": PBDB + "?base_name=" + quote(clade),
                }
            )
    return result[:limit]


def parse_nhm_facts(html, spoken_name):
    page = Text()
    page.feed(html)
    if normalize(spoken_name) not in [normalize(h) for h in page.headings]:
        raise SourceUnavailable("Museum page is not an exact named-creature page")
    lines = page.text.splitlines()
    labels = {}
    for i, line in enumerate(lines):
        match = re.match(
            r"^(Diet|Length|When it lived|Found in|Type of dinosaur)\s*:\s*(.*)$",
            line,
            re.I,
        )
        if match:
            labels[match[1].lower()] = match[2].strip() or (
                lines[i + 1] if i + 1 < len(lines) else ""
            )
        elif line.lower() in {
            "diet",
            "length",
            "when it lived",
            "found in",
            "type of dinosaur",
        } and i + 1 < len(lines):
            labels[line.lower()] = lines[i + 1]
    patch = {}
    diet = labels.get("diet", "").lower()
    if diet in {"herbivorous", "herbivore"}:
        patch["diet"] = "plants"
    elif diet in {"carnivorous", "carnivore"}:
        patch["diet"] = "meat"
    elif diet in {"omnivorous", "omnivore"}:
        patch["diet"] = "mixed"
    if labels.get("when it lived"):
        patch["time_period"] = labels["when it lived"][:200]
    if labels.get("type of dinosaur"):
        patch["subcategory"] = labels["type of dinosaur"][:120]
    if labels.get("found in"):
        patch["geographic_distribution"] = [
            "Fossils reported from " + labels["found in"][:200]
        ]
    length = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*m(?:etres?|eters?)?",
        labels.get("length", ""),
        re.I,
    )
    if length and float(length[1]) > 0:
        patch["length"] = {
            "minimum": float(length[1]),
            "maximum": float(length[2] or length[1]),
            "unit": "m",
            "note": "Museum estimate; not a precise individual measurement",
            "source_ids": ["nhm"],
        }
    return patch


def museum_facts(client, record):
    if record["category"] != "dinosaur":
        return {}, [], []
    url = (
        "https://www.nhm.ac.uk/discover/dino-directory/"
        + quote(record["display_name"].lower(), safe="")
        + ".html"
    )
    try:
        response = client.get(url)
        patch = parse_nhm_facts(response.text, record["display_name"])
        if not patch:
            return (
                {},
                [],
                [
                    "Museum structured fields were not recognized; review layout manually"
                ],
            )
        return (
            patch,
            [
                {
                    "id": "nhm",
                    "title": "Natural History Museum dinosaur directory structured facts",
                    "publisher": "Natural History Museum, London",
                    "url": str(response.request.url),
                    "retrieved_on": date.today().isoformat(),
                    "supports": list(patch),
                }
            ],
            [],
        )
    except (SourceUnavailable, ValueError) as error:
        return {}, [], [str(error)]
