"""Bounded HTTPS retrieval with robots, cache, rate limits and no access bypass."""

from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from collections import deque
import logging
import httpx
from .api_policy import metadata_request

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


def robots_enabled():
    """Only an explicit false value opts out; all other values fail closed."""
    return os.environ.get("IMPORT_RESPECT_ROBOTS", "true").strip().lower() != "false"


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
        self.user_agent = os.environ.get("BBS_IMPORT_USER_AGENT", USER_AGENT)
        if not self.user_agent.startswith("BedtimeBattleStoriesImporter/"):
            raise ValueError(
                "BBS_IMPORT_USER_AGENT must retain BedtimeBattleStoriesImporter/ identification"
            )
        self.respect_robots = robots_enabled()
        self.events = deque(maxlen=2000)
        self.robots_metadata = {}
        self.last = {}
        self.robots = {}
        self.requests = 0
        self.cache_hits = 0
        self.client = httpx.Client(
            transport=transport,
            timeout=25,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent},
        )

    def record(self, **event):
        event = {"method": "GET", "user_agent": self.user_agent, **event}
        self.events.append(event)
        logging.getLogger(__name__).info("Importer access: %s", json.dumps(event))

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
                    self.record(
                        endpoint=url,
                        http_status=response.status_code,
                        request_sent=True,
                        phase="http",
                    )
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
                api_error = None
                if result.status_code == 200 and metadata_request(url):
                    try:
                        data = result.json()
                    except ValueError as error:
                        raise SourceUnavailable(
                            "Commons JSON API returned a non-JSON response; not cached"
                        ) from error
                    if not isinstance(data, dict):
                        raise SourceUnavailable(
                            "Commons API returned an invalid JSON object; not cached"
                        )
                    api_error = data.get("error")
                    if api_error is not None:
                        self.record(
                            phase="api_error",
                            endpoint=url,
                            http_status=200,
                            request_sent=True,
                            error_code=api_error.get("code", "unknown")
                            if isinstance(api_error, dict)
                            else "unknown",
                        )
                    if api_error is not None and (
                        not isinstance(api_error, dict)
                        or api_error.get("code") not in {"maxlag", "ratelimited"}
                    ):
                        code = (
                            api_error.get("code", "unknown")
                            if isinstance(api_error, dict)
                            else "unknown"
                        )
                        raise SourceUnavailable(
                            f"Commons API error {code}; request refused, not cached"
                        )
                if result.status_code in {429, 500, 502, 503, 504} or api_error:
                    if attempt == 2:
                        raise SourceUnavailable(
                            f"{host}: "
                            + (
                                "API " + api_error["code"]
                                if api_error
                                else f"HTTP {result.status_code}"
                            )
                            + "; retry later"
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
                    self.sleep(
                        max(
                            5 * 2**attempt if metadata_request(url) else 2**attempt,
                            seconds,
                        )
                    )
                    continue
                if result.status_code in {401, 403}:
                    raise SourceUnavailable(
                        f"{host}: HTTP {result.status_code}; access denied, not bypassed"
                    )
                return result
            except httpx.ProxyError as error:
                self.record(
                    endpoint=url,
                    http_status=None,
                    request_sent=False,
                    phase="proxy",
                    error=type(error).__name__,
                )
                raise SourceUnavailable(
                    f"{host}: proxy/network policy rejected access ({type(error).__name__})"
                ) from error
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                self.record(
                    endpoint=url,
                    http_status=None,
                    request_sent=True,
                    phase="transport",
                    error=type(error).__name__,
                )
                if attempt == 2:
                    raise SourceUnavailable(
                        f"{host}: {type(error).__name__}; resume later"
                    ) from error
                self.sleep(2**attempt)
        raise SourceUnavailable("Request failed")

    def _robots(self, url):
        from .policy import Protego, decision

        host = self.validate_url(url)
        robots_url = "https://" + host + "/robots.txt"
        if host not in self.robots:
            try:
                result = self._wire(robots_url, limit=512_000)
                self.robots_metadata[host] = {
                    "robots_url": robots_url,
                    "robots_http_status": result.status_code,
                }
                if result.status_code == 404:
                    self.robots[host] = None
                elif result.status_code == 200:
                    self.robots[host] = Protego.parse(result.text)
                    sha = hashlib.sha256(result.content).hexdigest()
                    atomic(self.root / ("robots-" + sha + ".txt"), result.content)
                    self.robots_metadata[host]["robots_sha256"] = sha
                    interval = self.robots[host].crawl_delay(self.user_agent)
                    if interval:
                        self.delay = max(self.delay, interval)
                else:
                    self.robots[host] = "HTTP " + str(result.status_code)
            except SourceUnavailable as error:
                observed = next(
                    (
                        event.get("http_status")
                        for event in reversed(self.events)
                        if event.get("endpoint") == robots_url
                        and event.get("phase") == "http"
                    ),
                    None,
                )
                self.robots_metadata[host] = {
                    "robots_url": robots_url,
                    "robots_http_status": observed,
                }
                self.robots[host] = str(error)
        policy = self.robots[host]
        event = {
            "phase": "robots",
            "endpoint": url,
            "http_status": None,
            "request_sent": False,
            "robots_url": robots_url,
            "robots_http_status": None,
            "robots_rule": None,
            **self.robots_metadata.get(host, {}),
        }
        if isinstance(policy, str):
            self.record(**event, allowed=False, error=policy)
            raise SourceUnavailable("Robots/access policy unavailable: " + policy)
        result = (
            decision(policy, url, self.user_agent)
            if policy
            else {"allowed": True, "robots_rule": None, "robots_group": None}
        )
        self.record(**{**event, **result})
        if not result["allowed"]:
            raise SourceUnavailable(
                f"{host}: robots.txt disallows GET {url}; {result['robots_rule']}; User-Agent: {self.user_agent}; API request not sent (HTTP status: none)"
            )

    def _access_policy(self, url):
        self.validate_url(url)
        if not self.respect_robots:
            self.record(
                phase="robots_disabled",
                endpoint=url,
                http_status=None,
                request_sent=False,
                allowed=True,
                robots_applied=False,
                configuration="IMPORT_RESPECT_ROBOTS=false",
            )
            return
        self._robots(url)

    def _prepare_url(self, url):
        self.validate_url(url)
        if metadata_request(url) and "maxlag" not in httpx.URL(url).params:
            url = str(httpx.URL(url).copy_merge_params({"maxlag": "5"}))
        return url

    def get(self, url, params=None, limit=2_000_000):
        url = str(httpx.URL(url, params=params)) if params else url
        url = self._prepare_url(url)
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
        # All online requests and redirect hops use the explicit robots setting.
        # A previously fetched response can be reused offline without another request.
        if cached and not self.refresh and self.clock() - cached["fetched"] < 86400:
            self.cache_hits += 1
            return httpx.Response(
                cached["status"],
                content=body,
                headers=cached["headers"],
                request=httpx.Request("GET", cached["url"]),
            )
        self._access_policy(url)
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
            url = self._prepare_url(
                str(result.request.url.join(result.headers.get("location", "")))
            )
            self._access_policy(url)
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
