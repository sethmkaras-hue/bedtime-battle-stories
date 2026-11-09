"""Scoped read-only Commons API policy, separate from webpage crawler policy.

See docs/COMMONS_API_POLICY.md for the published interface basis and limits.
This does not grant access past authentication, server denials or proxy policy.
"""

from urllib.parse import parse_qsl, urlsplit
import re

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
POLICY_BASIS = "commons-read-only-api-v1"
POLICY_REFERENCE = "https://www.mediawiki.org/wiki/API:Etiquette"


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
    }
    if params.get("action") != "query" or not set(params) <= allowed:
        return False
    if (
        params.get("prop") not in {None, "imageinfo"}
        or params.get("meta") not in {None, "siteinfo"}
        or params.get("generator") not in {None, "search"}
        or params.get("list") not in {None, "search"}
    ):
        return False
    if not set(params.get("iiprop", "url|extmetadata").split("|")) <= {
        "url",
        "extmetadata",
    }:
        return False
    for key in ("gsrnamespace", "srnamespace"):
        if key in params and params[key] != "6":
            return False
    for key in ("gsrlimit", "srlimit"):
        if key in params and params[key] not in {"1", "2", "3", "4", "5"}:
            return False
    return True
