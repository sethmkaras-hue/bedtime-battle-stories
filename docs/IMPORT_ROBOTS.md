# Importer robots configuration

The private creature importer defaults to **`IMPORT_RESPECT_ROBOTS=false`**.
False (case/whitespace-insensitive) skips fetching/evaluating robots.txt. An
explicit true, or any other non-false value, enables enforcement.

```bash
IMPORT_RESPECT_ROBOTS=false ./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --refresh --skip-audio
IMPORT_RESPECT_ROBOTS=true ./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --skip-audio
```

This covers approved scientific/image HTTPS hosts, including PBDB and the exact
Commons Action API. It does not override website terms, authentication,
CAPTCHAs, paywalls, 401/403 responses or network policy. Identified User-Agent,
timeouts, host/redirect checks, serial pacing, retries and Retry-After remain.
Access events record the configured mode. The retired BBS_COMMONS_API_POLICY
flag does not override it. `.env.example` documents configuration; export values
or prefix commands, since scripts do not source `.env` automatically.

Image rights metadata is now retained without a license eligibility gate in the
private Internet pipeline. See [installation, safeguards and source credits](INTERNET_IMAGES.md).
