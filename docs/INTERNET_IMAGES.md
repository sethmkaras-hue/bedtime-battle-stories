# Automatic private Internet image imports

The normal importer now acquires existing images instead of generating diffusion artwork. It processes the current library, one creature at a time, without adding names to meet count targets. `--all` means all existing records (the bundled catalog has 164), not a taxonomy expansion. Scientific facts, written pronunciation references and image downloads run independently. There are no routine parent approval steps. Existing numeric IDs, science profiles, audio caches and session tournament behavior are preserved.

## Ubuntu 26.04 commands

From your existing checkout, stop the foreground application with Ctrl+C. Preserve `data/` and its backups. If you previously installed the optional diffusion user service, stop it before importing replacements; otherwise it can continue work already queued independently of the web app:

```bash
cd ~/bedtime-battle-stories
if systemctl --user cat bedtime-creature-images.service >/dev/null 2>&1; then
  systemctl --user disable --now bedtime-creature-images.service
fi
```

The service is not installed automatically. Stop any separately running foreground diffusion worker with Ctrl+C. Do not remove models, generated images, database or audio caches.

After this PR is merged, update and install the core/media requirements in your existing Python 3.14 environment:

```bash
git switch main
git pull --ff-only origin main
sudo apt update
sudo apt install python3.14 python3.14-venv
# Create .venv only if absent; preserve a working existing environment.
if [ ! -d .venv ]; then python3.14 -m venv .venv; fi
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt -r requirements-media.txt
BBS_PYTHON=python3.14 bash START_APP.sh
```

For testing before merge, replace the first two Git commands with `git fetch origin` and `git switch --track origin/feature/automatic-internet-creature-images` (or switch to that existing local branch). `START_APP.sh` checks the environment's Python version and retains port 8502. If you installed a custom application service, restart that same service instead of launching a second server. There is no repository-wide service name to assume. Pillow is optional for web startup, but required for image imports. No Torch, diffusion model, GPU or paid API is required. Existing audio dependencies do not need removal or reinstallation.

In a second terminal in the checkout, run the pilot:

```bash
IMPORT_RESPECT_ROBOTS=false ./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --refresh --skip-audio
```

Inspect coverage and the persistent report:

```bash
./IMPORT_CREATURE_LIBRARY.sh --coverage
.venv/bin/python -m json.tool data/importer/latest-report.json
```

When ready, import the full library:

```bash
IMPORT_RESPECT_ROBOTS=false ./IMPORT_CREATURE_LIBRARY.sh --all --refresh --skip-audio
```

Resume an interrupted pilot or full run by repeating it **without `--refresh`**:

```bash
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --skip-audio
./IMPORT_CREATURE_LIBRARY.sh --all --skip-audio
```

Choose the appropriate one, rather than running both. Completed, checksum-valid images are skipped. Failed/missing/corrupt images remain retryable. Scientific failures are retried without redownloading completed artwork. Use `--refresh` to search again; a lower identity score never replaces a higher one. Existing usable manually identified canonical artwork is conservatively protected at score 100; old automatically published canonical artwork has floor 95. Missing/corrupt canonical files do not block repair. `--dry-run` searches/scores without image downloads or application database writes. `--verbose` prints the full JSON; normal output is short progress and a summary. `--report /path/report.json` saves an additional report. Unsupported flags fail through argparse. The old `--propose-only`, `--review` and `--legacy-source-images` modes are retired. `--diagnose-commons` is read-only network diagnosis; `--coverage` requires no network.

Without `--skip-audio`, the existing generator prepares only source-verified names using configured local audio providers. Unverified supplied guidance is saved without inventing verification and remains ineligible for audio until verified source evidence is supplied. Child speaker taps still play cached files only. No source-backed update needs a parent-interface approval. Manually inspected fields and existing verified pronunciation remain protected from lower-quality automated changes.

## Access and provenance

`IMPORT_RESPECT_ROBOTS` defaults to **false for this importer**. False (case/whitespace-insensitive) makes no robots.txt requests or rule decisions. Set `IMPORT_RESPECT_ROBOTS=true` to enforce robots again; malformed values also enable enforcement. This does not override site terms or technical access restrictions. HTTPS host/redirect restrictions, identifiable `BedtimeBattleStoriesImporter/…` User-Agent, 25-second timeout, serial per-host pacing, three bounded retries, exponential backoff, Retry-After and Commons maxlag handling remain. Authentication, CAPTCHAs, paywalls and 401/403 responses are not bypassed. Long Retry-After delays stop for a later run rather than hammering a server.

License metadata is provenance, not a selection gate in this private importer. Unknown/missing/restrictive/noncommercial declarations and incomplete attribution do not alone reject an image. An otherwise exact tie prefers a recognized open declaration. Creator, source page, direct URL, original license declaration/URL, attribution, retrieval timestamp and modifications remain accessible in **Settings → Sources & Credits**. Missing declarations remain unknown; no permission or public-domain status is invented. Available CC BY credit is also displayed on the creature profile.

Downloaded originals/API bodies live in `data/importer/http/`; optimized WebP files live in `data/creature_images/` (`BBS_CREATURE_IMAGE_DIR` overrides it). Both are gitignored. Do not include them in GitHub commits, release archives or shared application bundles. This is local private acquisition, not a redistribution mechanism. Source access and attribution obligations still apply.

## Discovery and deterministic selection

Commons Action API search is primary and independent of Wikidata. It searches scientific/display names and available synonyms, then reconstruction/paleoart/life-restoration/illustration/skeleton queries (wildlife/underwater for living sharks), plus named and taxonomic Commons categories. Each query requests 50 files with image URLs, dimensions, MIME and extended metadata, follows up to three API continuation pages, and deduplicates original URLs. The overall cap is 160 candidates per creature. It does not stop at five results or twenty candidates; where enough results exist the pagination tests demonstrate 40 unique candidates despite duplicate results across searches. Optional `--use-wikidata` adds taxon-checked P18 references without gating Commons access.

Living sharks also use GBIF's exact accepted species match and exact-species occurrence media. Direct media is limited to the existing approved HTTPS sources plus `static.inaturalist.org` and `inaturalist-open-data.s3.amazonaws.com`; arbitrary redirects and private hosts are not enabled. Other publicly accessible sources can be supplied as local image/metadata manifests. No supported additional live paleoart API is claimed.

Eligibility requires source metadata identifying the actual subject: the scientific name in the caption, corroborated by title/category or a subject-led caption. Known other-taxon titles, ambiguous comparisons, speculative identities, movie/toy/cartoon/commercial/graphic subjects and small thumbnails are rejected. Living sharks need photographs. Ranking orders the identity evidence score first, then illustration/photo type, full-body wording, resolution and text/fossil penalties, then open-license ties and stable URL ordering. Fossils can serve as a lower-ranked fallback when no reconstruction is suitable. No metadata heuristic proves anatomical accuracy, detects every cropped/incorrect image or visually inspects pixels. Scores are deterministic evidence scores, not calibrated scientific probabilities. Uncertain candidates are skipped with reasons, without an approval queue; the existing image remains.

The importer validates actual downloaded image data, dimensions, decoded-pixel limits and corruption using Pillow. JPEG, PNG and WebP work; supported Pillow formats may also work, while SVG/nonimage/unsupported content fails and the next candidate is tried. Originals are bounded at 20 MB and 25 megapixels. WebP fits inside 768px at quality 85. Content hashes deduplicate files, publication is atomic, and a transaction checks current creature identity before updating the active SQLite manifest. Immutable prior image URLs remain valid. A failed replacement does not destroy a working file or active manifest. A database-scoped lock prevents concurrent importers using different work directories.

The new Internet manifest is separate from the old licensed canonical artwork schema. This avoids the old approval endpoint's required `confirm`/`scopes`/identifier DTO and mandatory reusable-license fields without suppressing errors or altering scientific validation. Previous approval regressions still test the isolated, unmounted legacy implementation; production approval/generation write endpoints return 404. Database/identity/file failures include creature, operation and error in diagnostics. The common creature renderer overlays Internet artwork before preserved AI artwork and canonical placeholders, so selection, profile, bracket/story and winner images share the same versioned URL and MIME path.

## Local image and pronunciation references

`--offline --image-references /path/images.json` accepts the existing schema-version-1 image manifest with image_file/metadata_file paths contained within its directory. Saved Commons imageinfo responses work without license fields. For other sources use `source_kind: "licensed_reference"` (a legacy format name; the private pipeline no longer requires a license). Example metadata:

```json
{
  "title": "Diplodocus life restoration",
  "identified_taxon": "Diplodocus",
  "source_url": "https://example.org/actual-source-page",
  "description": "Diplodocus life restoration",
  "identity_evidence": "Literal exact subject caption in the saved reference",
  "identity_status": "supported",
  "creator": null,
  "license": null,
  "license_url": null
}
```

This illustrates structure only; replace it with real inspected source data. Images with uncertain/mismatched identity are still skipped. Local files are checksum-checked before installation. Source-backed pronunciation CSV/JSON and saved HTML references retain their existing `--pronunciation-references` format and source verification metadata. Explicitly unverified references remain unverified; supplying verified evidence applies automatically without parent UI.

## Diagnosis and remaining validation limits

The old five-result search accounts for the 50 candidates in a ten-creature pilot. Its caption-prefix-only rule, generic `and`/`with` ambiguity rejection, reconstruction-only restriction, license/creator allowlist, two-preview cap, and placeholder-only publication could all suppress installations. The original 48 rejected records and original installed Diplodocus/Allosaurus files were not present in this checkout, so an exact per-candidate accounting cannot be reconstructed. Per-creature `data/importer/candidates/ID.json` reports retain every discovered candidate's metadata and eligibility/reasons; the main JSON report records their paths, rejection totals and selected download failures. The in-memory run summary does not retain all full candidate metadata for all 164 creatures. Per-record progress writes contain counters and the last result, avoiding repeated rewrites of a growing full report. SQLite stores each record's state immediately; the complete latest-report.json is written once at completion.

The bundled database currently has placeholders for Diplodocus and Allosaurus here. Mobile integration tests install synthetic fixtures for those exact records and verify disk → SQLite → FastAPI WebP → decoded selection/profile image → Sources & Credits. These are not claimed to be the user's original artwork. Browser regression also covers all 164 book entries, 110 initially visible dinosaurs, search/category/lazy loading, eight selections, all seven battles and prepared audio transport. Physical Ubuntu laptop/iPhone testing remains separate.

Live pilot results and exact automated test totals are recorded in the PR. No full 164-creature network import is started by installation or app startup. Do not infer coverage from candidate counts or from passing mocked tests: use `--coverage` on the home server. CPU diffusion code and old generated files remain isolated and readable, with normal generation UI/write routes disabled.


## Validation performed for this PR

- Complete Python 3.12 and 3.14 application suites and the optional-media-free 3.14 suite are reported in the PR; no paid services or live Internet are needed for unit tests.
- A mocked ten-creature pilot was interrupted after five installs, resumed the remaining five, and then skipped all ten completed images. This validates restart mechanics, not actual taxon artwork.
- Mobile Chromium passes synthetic imported Diplodocus/Allosaurus display, credits/coverage and retired controls. The complete existing browser flow passes all 164 book entries, 110 dinosaurs initially visible, search/category/lazy loading, eight-entrant cap, seven battles, audio/cache controls and prepared-name playback.
- The **live ten-creature pilot on a copy of the cloud database processed 10, discovered 0, installed 0**. Its 20 PBDB/Commons requests recorded `robots_disabled` followed by proxy denials; no robots requests occurred. Independent HTTPS probes to both documented endpoints received proxy CONNECT HTTP 403. These are environment-policy denials before a source response, not evidence that PBDB/Commons forbid the requests. No access restriction was bypassed.
- Actual network artwork quality and successful live acquisition remain unverified in this environment. The original home-server files, physical Dell/Ubuntu 26.04 and iPhone Safari were unavailable. No full-library live run occurred. Run the documented pilot and coverage commands on the home server before the full batch. If a configured outbound proxy blocks access, its policy must permit Commons, upload.wikimedia.org, paleobiodb.org and (for alternatives) api.gbif.org / supported media hosts; optional Wikidata needs www.wikidata.org.

Final automated totals: **285 passed on Python 3.12 and 285 passed on Python 3.14 with media dependencies**. Core-only Python 3.14: **245 passed, 40 optional-media checks skipped**. The 36 new importer tests use mocked services or local synthetic images. JavaScript/shell syntax, Python undefined-name checks and pip dependency consistency also passed. These are Debian cloud checks; native Ubuntu 26.04 and physical-device checks are not claimed.
