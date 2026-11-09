# Commons API access policy

The importer treats a small set of documented, read-only Commons API requests as programmatic API use, separately from ordinary webpage crawling. This replaces its earlier blanket application of crawler robots.txt to every URL below `/w/`.

## Basis and evidence

Wikimedia documents the [MediaWiki Action API](https://www.mediawiki.org/wiki/API:Main_page) as a programmatic web service, including [search](https://www.mediawiki.org/wiki/API:Search) and [image information](https://www.mediawiki.org/wiki/API:Imageinfo). Its official [API demonstrations repository](https://github.com/wikimedia/mediawiki-api-demos/tree/f878baee026e658462aea45cc24ccd79972c8759) describes the API as a web service providing authentication, page operations and search. The inspected [imageinfo Python example](https://github.com/wikimedia/mediawiki-api-demos/blob/f878baee026e658462aea45cc24ccd79972c8759/python/get_imageinfo.py) issues an anonymous programmatic GET with `action=query`, `prop=imageinfo` and JSON output. The [generated image search example](https://github.com/wikimedia/mediawiki-api-demos/blob/f878baee026e658462aea45cc24ccd79972c8759/python/geoimagesearch.py) similarly demonstrates query generators. The repository HEAD inspected here is dated October 29, 2026.

The applicable operator guidance is Wikimedia's [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette), [API usage guidelines](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines), [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy), and [maxlag guidance](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter). Commons exposes the same documented Action API at `https://commons.wikimedia.org/w/api.php`; optional [MediaInfo claims](https://commons.wikimedia.org/wiki/Commons:Structured_data/MediaInfo_API) are read there as well.

The policy decision is that the importer's small, anonymous, identified, throttled public metadata queries are the documented programmatic use of this service. A crawler exclusion such as `Disallow: /w/` is not treated as an API authentication/authorization response. This is **not a claim that a policy document contains an explicit blanket robots exemption**. Permission is limited to the documented read operations below, subject to Wikimedia's terms, current API policies, limits and actual server decisions. It does not authorize arbitrary crawling, editing, bulk replication, private-data access or evasion of access controls.

Evidence limits: the official GitHub source above was actually retrieved. This cloud's proxy blocks the live Wikimedia policy pages and Commons endpoint, so their current text and live service acceptance could not be independently revalidated here. Those policy links are provided for operator review, not presented as live-read quotations. If current Wikimedia guidance prohibits the intended use, select the strict mode below and retain local imports. No API policy decision overrides Wikimedia HTTP 401/403, API-level permission denials, a proxy restriction or authentication requirement.

## Exact scope in code

The exception in `app/importer/api_policy.py` requires:

- HTTPS, the exact `commons.wikimedia.org` authority and `/w/api.php` path, with no fragment. Other schemes, ports, hosts, subpaths, aliases and encoded paths do not qualify.
- GET requests (the client's only transport method) with JSON output and unique query parameters.
- `action=query` limited to search, imageinfo and siteinfo metadata parameters. File namespace and small result limits are enforced when provided; imageinfo properties are restricted to `url` and `extmetadata`.
- Or `action=wbgetentities` restricted to claims for up to five Commons MediaInfo `M` identifiers, for optional corroboration.
- No editing/parsing actions, tokens, revisions or arbitrary extra API parameters.

Search returns at most five candidates per creature. The existing adapter retrieves original URLs plus extmetadata license declarations, creator/author and attribution. License and exact-taxon/medium screening still happen **before** original-image download. Unknown, restrictive or mismatched licenses do not qualify. Ambiguous identifications remain pending parent review. Supported candidates enter quarantine and the existing WebP pipeline; API access itself does not approve artwork or verify scientific facts.

The exception does not extend to Commons HTML/file description pages, `/w/index.php`, Wikidata, museums or image download hosts. Those still need their own robots checks. Redirects are validated again at every hop; an API redirect cannot grant its destination API privileges. There is no mobileview trick, browser impersonation, alternate proxy or authentication workaround.

## Courtesy, retry and diagnostics

The actual User-Agent remains `BedtimeBattleStoriesImporter/1.0` with the project/contact URL. Custom contact text must retain that identifying prefix. A single CLI import makes sequential requests, paced at least 1.2 seconds apart by default (never below one second), with persistent HTTP caching. Audio generation and child playback are separate.

Eligible API requests receive `maxlag=5` unless a stricter value is supplied; the same applies after redirects. HTTP 429/transient failures and HTTP-200 MediaWiki `maxlag`/`ratelimited` errors have at most three attempts. API retry backoff starts at five seconds and doubles, honoring numeric or HTTP-date Retry-After values. Delays above 30 seconds defer the import rather than retrying early. HTTP 401/403 and other API errors are not retried. Non-JSON replies and API errors are not cached as successful metadata.

`access_log` records `phase: api_policy`, policy basis `commons-read-only-api-v1`, `robots_applied:false`, and the exact endpoint/method/identity. A later HTTP or proxy event records the actual outcome. The policy event is permission to attempt a request, **not evidence that Wikimedia served it**.

```bash
./IMPORT_CREATURE_LIBRARY.sh --diagnose-commons --report /tmp/commons-api.json
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --refresh --skip-audio
```

Importer version 4 revisits old checkpoints once so the previous robots failure does not suppress this code change. `--refresh` also deliberately retries completed checkpoints. No migration deletes or rewrites scientific records or pronunciation/audio caches. Existing reviewed fields, stable IDs and approved imagery retain their protection.

## Strict mode and supported alternative

Set this on a command to require robots for Commons API requests too:

```bash
BBS_COMMONS_API_POLICY=robots ./IMPORT_CREATURE_LIBRARY.sh --diagnose-commons \
  --report /tmp/commons-strict.json
```

If robots or current API policy disallow access, or the server/proxy rejects it, use the already supported local route:

```bash
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --offline \
  --image-references /path/to/bundle/images.json --skip-audio
```

The [local import formats and licensing workflow](CREATURE_LIBRARY.md#local-commons-and-alternative-licensed-images) accept saved Commons metadata/originals and explicitly reusable alternative-source images. They require the same taxon/license evidence and authenticated parent approval. Local CSV/JSON pronunciation references and the verified-only pre-generated audio cache are unchanged.

## Verification

Python 3.14 with optional media dependencies: **173 tests passed**. Core-only Python 3.14 and Python 3.12 each passed 159, skipping 14 optional media tests. Tests cover scope boundaries, ordinary robots denials, strict mode, redirects, identity, throttling, HTTP/API retries, Retry-After, refusal/cache handling, licensing, ambiguous taxa, staged downloads and unchanged scientific/audio data.

The real diagnostic passed local API-policy selection but hit a cloud ProxyError before a Wikimedia response. No real Commons image acquisition, live API availability, new pronunciation verification or audible improvement is claimed.
