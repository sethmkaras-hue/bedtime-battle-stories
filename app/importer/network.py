"""Bounded HTTPS retrieval with robots, cache, rate limits and no access bypass."""

from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx

HOSTS = {
    "paleobiodb.org",
    "api.gbif.org",
    "www.nhm.ac.uk",
    "nhm.ac.uk",
    "www.amnh.org",
    "www.si.edu",
    "commons.wikimedia.org",
    "www.wikidata.org",
    "upload.wikimedia.org",
    "www.floridamuseum.ufl.edu",
    "usborne.com",
}
USER_AGENT = "BedtimeBattleStoriesImporter/1.0 (+https://github.com/sethmkaras-hue/bedtime-battle-stories)"


class SourceUnavailable(RuntimeError):
    pass


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PoliteClient:
    def __init__(
        self,
        root,
        refresh=False,
        delay=1.2,
        transport=None,
        sleep=time.sleep,
        clock=time.time,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.refresh = refresh
        self.delay = max(1, delay)
        self.sleep = sleep
        self.clock = clock
        self.last = {}
        self.robots = {}
        self.requests = 0
        self.cache_hits = 0
        self.client = httpx.Client(
            transport=transport,
            timeout=25,
            follow_redirects=False,
            headers={"User-Agent": os.environ.get("BBS_IMPORT_USER_AGENT", USER_AGENT)},
        )

    def close(self):
        self.client.close()

    def validate_url(self, url):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in HOSTS
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
        ):
            raise SourceUnavailable("Unapproved source/redirect URL")
        return parsed.hostname

    def _wire(self, url, headers=None, limit=2_000_000):
        host = self.validate_url(url)
        for attempt in range(3):
            remaining = self.delay - (self.clock() - self.last.get(host, 0))
            if remaining > 0:
                self.sleep(remaining)
            self.last[host] = self.clock()
            self.requests += 1
            try:
                with self.client.stream("GET", url, headers=headers or {}) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > limit:
                            raise SourceUnavailable(
                                "Response exceeds download size limit"
                            )
                    result = httpx.Response(
                        response.status_code,
                        headers={
                            k: v
                            for k, v in response.headers.items()
                            if k.lower() not in {"content-encoding", "content-length"}
                        },
                        content=bytes(body),
                        request=response.request,
                    )
                if result.status_code in {429, 500, 502, 503, 504}:
                    if attempt == 2:
                        raise SourceUnavailable(
                            f"{host}: HTTP {result.status_code}; retry later"
                        )
                    retry = result.headers.get("Retry-After", "")
                    seconds = int(retry) if retry.isdecimal() else 0
                    if retry and not retry.isdecimal():
                        try:
                            seconds = max(
                                0,
                                parsedate_to_datetime(retry).timestamp() - self.clock(),
                            )
                        except (ValueError, TypeError, OverflowError):
                            pass
                    if seconds > 30:
                        raise SourceUnavailable(
                            f"{host}: Retry-After requires a longer delay; resume later"
                        )
                    self.sleep(max(2**attempt, seconds))
                    continue
                if result.status_code in {401, 403}:
                    raise SourceUnavailable(
                        f"{host}: HTTP {result.status_code}; access denied, not bypassed"
                    )
                return result
            except httpx.ProxyError as error:
                raise SourceUnavailable(
                    f"{host}: proxy/network policy rejected access ({type(error).__name__})"
                ) from error
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt == 2:
                    raise SourceUnavailable(
                        f"{host}: {type(error).__name__}; resume later"
                    ) from error
                self.sleep(2**attempt)
        raise SourceUnavailable("Request failed")

    def _robots(self, url):
        host = self.validate_url(url)
        if host not in self.robots:
            try:
                result = self._wire("https://" + host + "/robots.txt", limit=512_000)
                if result.status_code == 404:
                    self.robots[host] = None
                elif result.status_code == 200:
                    parser = RobotFileParser()
                    parser.parse(result.text.splitlines())
                    self.robots[host] = parser
                    interval = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*")
                    if interval:
                        self.delay = max(self.delay, interval)
                else:
                    self.robots[host] = "unavailable"
            except SourceUnavailable as error:
                self.robots[host] = str(error)
        policy = self.robots[host]
        if isinstance(policy, str):
            raise SourceUnavailable("Robots/access policy unavailable: " + policy)
        if policy is not None and not policy.can_fetch(USER_AGENT, url):
            raise SourceUnavailable(f"{host}: robots.txt disallows this URL")

    def get(self, url, params=None, limit=2_000_000):
        url = str(httpx.URL(url, params=params)) if params else url
        self.validate_url(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        meta = self.root / (key + ".json")
        bodyfile = self.root / (key + ".body")
        cached = None
        if meta.is_file() and bodyfile.is_file():
            try:
                cached = json.loads(meta.read_text())
                if not {"url", "status", "headers", "fetched", "sha256"} <= set(cached):
                    raise ValueError("Incomplete HTTP cache metadata")
                self.validate_url(cached["url"])
                body = bodyfile.read_bytes()
                if (
                    len(body) > limit
                    or hashlib.sha256(body).hexdigest() != cached["sha256"]
                ):
                    cached = None
            except (OSError, ValueError, KeyError, SourceUnavailable):
                cached = None
        # robots is always checked for online use, including conditional refreshes.
        # A previously fetched response can be reused offline without another request.
        if cached and not self.refresh and self.clock() - cached["fetched"] < 86400:
            self.cache_hits += 1
            return httpx.Response(
                cached["status"],
                content=body,
                headers=cached["headers"],
                request=httpx.Request("GET", cached["url"]),
            )
        self._robots(url)
        headers = {}
        if cached:
            if cached["headers"].get("etag"):
                headers["If-None-Match"] = cached["headers"]["etag"]
            if cached["headers"].get("last-modified"):
                headers["If-Modified-Since"] = cached["headers"]["last-modified"]
        result = self._wire(url, headers, limit)
        for _ in range(4):
            if result.status_code not in {301, 302, 303, 307, 308}:
                break
            url = str(result.request.url.join(result.headers.get("location", "")))
            self.validate_url(url)
            self._robots(url)
            result = self._wire(url, limit=limit)
        if result.status_code == 304 and cached:
            self.cache_hits += 1
            cached["fetched"] = self.clock()
            atomic(meta, json.dumps(cached).encode())
            return httpx.Response(
                cached["status"],
                content=body,
                headers=cached["headers"],
                request=result.request,
            )
        if result.status_code != 200:
            raise SourceUnavailable(
                f"{result.request.url.host}: HTTP {result.status_code}"
            )
        data = {
            "status": 200,
            "headers": dict(result.headers),
            "url": str(result.request.url),
            "fetched": self.clock(),
            "sha256": hashlib.sha256(result.content).hexdigest(),
        }
        atomic(bodyfile, result.content)
        atomic(meta, json.dumps(data).encode())
        return result

    def json(self, url, params=None):
        try:
            result = self.get(url, params).json()
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            return result
        except (ValueError, KeyError) as error:
            raise SourceUnavailable("Source did not return valid JSON") from error
