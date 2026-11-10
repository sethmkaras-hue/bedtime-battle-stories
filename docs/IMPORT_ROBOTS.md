# Importer robots configuration

Requests respect robots.txt by default, including PBDB and Commons. Only
`IMPORT_RESPECT_ROBOTS=false` (case-insensitive, surrounding whitespace ignored)
disables robots retrieval/enforcement for the importer's existing allowed HTTPS
hosts. Other values and an unset variable keep enforcement enabled.

```bash
IMPORT_RESPECT_ROBOTS=false ./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --refresh --skip-audio
```

This applies to `paleobiodb.org/data1.2/`, `commons.wikimedia.org/w/api.php`, and
allowed redirect destinations. It does not expand the HTTPS host allowlist,
change authentication, solve CAPTCHAs, ignore HTTP 401/403, or bypass network
policy. Timeouts, identified User-Agent, pacing, retries, Retry-After and image
license/attribution checks remain. Diagnostics record `robots_disabled` and
`respect_robots:false`; no robots.txt request is made in that mode.

The earlier `BBS_COMMONS_API_POLICY` exception is retired: it cannot override
the safe default. Metadata classification still supplies maxlag/API-error
handling. Config changes participate in restart checkpoints; `--refresh` can
also explicitly retry earlier attempts. Nothing deletes scientific/audio data.

The `.env.example` is documentation: export variables or prefix the command;
the scripts do not automatically source `.env`.
