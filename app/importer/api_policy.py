"""Classify Commons JSON metadata reads for maxlag and API-error handling.

Access decisions use IMPORT_RESPECT_ROBOTS; this classifier grants no exception.
"""

from urllib.parse import parse_qsl, urlsplit
import re

COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def metadata_request(url):
    """Only the exact HTTPS endpoint and the importer's public JSON reads qualify."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "commons.wikimedia.org"
        or parsed.path != "/w/api.php"
        or parsed.fragment
    ):
        return False
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=30)
    except ValueError:
        return False
    params = dict(pairs)
    if len(params) != len(pairs) or params.get("format") != "json":
        return False
    if "maxlag" in params and params["maxlag"] not in {"0", "1", "2", "3", "4", "5"}:
        return False
    if params.get("action") == "wbgetentities":
        return (
            set(params) <= {"action", "format", "maxlag", "ids", "props"}
            and params.get("props") == "claims"
            and bool(
                re.fullmatch(
                    r"M[1-9][0-9]*(?:\|M[1-9][0-9]*){0,4}", params.get("ids", "")
                )
            )
        )
    allowed = {
        "action",
        "format",
        "maxlag",
        "generator",
        "gsrsearch",
        "gsrnamespace",
        "gsrlimit",
        "prop",
        "iiprop",
        "titles",
        "pageids",
        "meta",
        "list",
        "srsearch",
        "srnamespace",
        "srlimit",
        "continue",
        "gsroffset",
        "gcmtitle",
        "gcmnamespace",
        "gcmtype",
        "gcmlimit",
        "gcmcontinue",
        "iicontinue",
        "iiurlwidth",
    }
    if params.get("action") != "query" or not set(params) <= allowed:
        return False
    if (
        params.get("prop") not in {None, "imageinfo"}
        or params.get("meta") not in {None, "siteinfo"}
        or params.get("generator") not in {None, "search", "categorymembers"}
        or params.get("list") not in {None, "search"}
    ):
        return False
    if not set(params.get("iiprop", "url|extmetadata").split("|")) <= {
        "url",
        "extmetadata",
        "size",
        "mime",
    }:
        return False
    for key in ("gsrnamespace", "srnamespace", "gcmnamespace"):
        if key in params and params[key] != "6":
            return False
    for key in ("gsrlimit", "srlimit", "gcmlimit"):
        if key in params and (
            not params[key].isdigit() or not 1 <= int(params[key]) <= 50
        ):
            return False
    if "gsroffset" in params and (
        not params["gsroffset"].isdigit() or int(params["gsroffset"]) > 10000
    ):
        return False
    if params.get("generator") == "categorymembers" and (
        not params.get("gcmtitle", "").startswith("Category:")
        or params.get("gcmtype") != "file"
    ):
        return False
    if any(
        len(params.get(key, "")) > 500
        for key in ("continue", "gcmcontinue", "iicontinue", "gcmtitle")
    ):
        return False
    if "iiurlwidth" in params and (not params["iiurlwidth"].isdigit() or not 16 <= int(params["iiurlwidth"]) <= 1024):
        return False
    return True
