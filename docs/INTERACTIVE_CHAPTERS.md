# Interactive chapters and individual creature pictures

**Historical implementation notes:** the subsequent [short-battle update](SHORT_BATTLES.md) changes the default to 20 seconds, adds WANT before THINK, permits any established matchup to play, and restores on-demand spoken names. Use its deployment and validation instructions for current behavior. Measurements below describe the earlier version.

New adventures keep the existing eight-creature, seven-battle bracket, but store their results, predictions, chapters and narration locally. Defaults are **40 seconds**, **Dramatic**, predictions enabled, simulation winners, and connected chapters. Adult duration choices are 20/30/40/50/60 seconds. Previously prepared chapters are immutable during normal playback. No full image import or image generation is part of this upgrade.

## Components reused and extended

- The existing FastAPI app, SQLite database, creature profiles, game ratings, habitat checks, vanilla mobile UI, bracket rendering and HTML5 playback remain.
- `app/chapters/store.py` adds namespaced settings/tournament/battle/chapter/version/job/calibration/image-history tables. `app/adventure.py` and the existing `/api/tournament` / `/api/adventure` contracts remain for legacy sessions.
- `simulation.py` computes seeded game outcomes from the captured creature profiles and arena. `narrative.py` builds validated local dramatic variants, not a paid/cloud language model. `worker.py` is one durable coordinator around the existing single-worker `AudioService`.
- `images.py` reuses `app/importer/internet_images.py` and its `PoliteClient` for targeted search, preview, download and WebP validation. It does not implement another scraper or run the bulk importer.
- `static/chapters.js` implements matchup → optional prediction → preparation → narration → reveal → next chapter. `static/adult-tools.js` reuses the existing parent passphrase/session/CSRF mechanism for Settings, regeneration and pictures. There are no user accounts or new routine content approvals.

## Data, migration and legacy preservation

New tables are `story_settings`, `story_tournaments`, `story_battles`, `story_chapters`, `story_chapter_versions`, `story_jobs`, `story_tts_calibration`, `story_image_candidates`, `story_image_history` and `story_image_choice`. Existing creature/profile/audio/image tables and any unrelated historical tables are retained. Numeric creature IDs do not change. The migration is additive and repeatable. A first migration of an existing database makes an online SQLite backup in its adjacent `backups/` directory; a fresh database does not need a pre-migration backup.

The inspected application previously kept tournament progress in browser sessionStorage, not a permanent tournament table. This upgrade does not fabricate historical tournament plans, predictions or chapter records. Legacy tab snapshots are displayed directly on restoration without recomputing their completed results; explicit legacy progression continues using the original stateless API. New persistent adventures use stored simulations only: GET/replay/retry never simulates a ready/completed battle again. Other legacy database tables remain untouched rather than guessing their schemas. Preserve old browser tab storage if you need an old session; newly saved adventures also appear under **Our saved adventures**.

A new adventure snapshots creature names/scientific fields and game inputs. Current picture URLs are overlaid for display, so picture changes do not change past outcomes or rewrite historical narration. Simulation JSON stores competitors, recorded inputs, game estimates, arena/modifiers, seed, probability/draw, version and completion timestamp. Predictions store tournament/battle association, guessed ID or skip, submission timestamp, actual winner and correctness. Actual winner/correctness are withheld from the normal active UI until completion. A saved prediction cannot be changed by retrying or replaying a battle.

Prepared chapter settings are snapshots. New server duration/tone/continuity choices apply when an unprepared chapter begins, not to existing text/audio. A tournament remembers its last narration engine/voice/rate; another device keeps that voice unless a user explicitly changes audio preferences. Regeneration is a separate authenticated, explicitly confirmed adult action: it preserves simulation/prediction, creates a new text/audio revision, and retains the old version. **View archived chapter versions** exposes old text and audio to the adult. A failed regeneration restores the most recent valid archived take.

## Simulation and narrative rules

The game model deliberately distinguishes inspected facts from fictional estimates. Positive inspected length/weight ranges contribute `0.25 * log1p(length_m)` and `0.12 * log1p(weight_kg)`. Existing game rating contributes strength; game agility is `max(1, 6 - 0.35 * rating)`. Inspected weapon/defense trait keywords give bounded game bonuses. They are not precise speed/strength measurements or a scientific prediction of animal combat.

The score is `0.60*strength + 0.35*agility + 0.20*weapons + 0.30*defense + size + environmental_modifier`. Forest/shallows cover favors game agility, open terrain favors strength, and an edge arena gives a small semiaquatic bonus. Win probability is the logistic score difference at scale 0.9, bounded to 15–85%. A seeded draw selects the winner. There are no species-name winner rules in this new simulation. Stronger entrants usually have better odds but can lose; guesses never enter the calculation.

Known shared habitats select a land or water arena. Known incompatible habitats in a new API-created mixed tournament use an explicitly fictional **split shore-and-water arena**, with each animal in its own habitat and `scientifically_realistic:false`. Unknown habitats fail closed. The existing child category/Ocean Mix selection and legacy APIs keep their compatibility rules.

A tournament plan contains title, theme, setting, atmosphere, seven-stage progression and continuity rules, without future winners. Each chapter receives the actual competitors, persisted simulation, plan, completed chapter summaries/events and its saved settings. Only completed chapters can be referenced. The championship has a stronger six-battle journey opening and champion conclusion. Structured output validates the winning ID, chapter number, participant names and future references. It has opening/setting, confrontation/reversal, decisive safe finish, summary/events and transition.

Inspected anatomical traits are used when available. Missing/unreviewed scientific detail is not filled with invented horns, powers, measurements or victories; generic position/dodge/contest actions remain the fallback. This limits species-specific detail in incomplete catalog profiles. Defeated creatures retreat safely; graphic injury/death is not used as the default. Local templates vary openings, contest moves, reversals, environment, filler clauses and chapter continuity rather than calling an unapproved model or paid service.

## Timing, CPU work and archival playback

Initial planning uses about 2.15 words/second adjusted for the selected natural speaking rate. Observed words/second are then retained by actual local engine, voice and rate for later estimates. The worker synthesizes via existing Kokoro/Piper, reads WAV frame count/sample rate, compares with `max(2 seconds, 5% of target)`, and adjusts text length for up to three attempts. It never speeds speech up to conceal a duration miss or pads the displayed scene to claim a spoken duration. The closest valid take survives if timing cannot be achieved; `timing_met:false` and actual seconds remain visible.

Metadata includes requested/actual seconds, engine, actual voice, speaking rate, original audio-cache key, attempts, timestamp, checksum, archive path/root and playback URL. Engine/voice fallback is recorded. Archived WAVs live in gitignored **data/chapter_audio/** (`BBS_CHAPTER_AUDIO` can override it), independently of `data/audio_cache/`. Clearing the ordinary audio cache does not delete a saved chapter. Audio file hashes provide immutable URLs; version metadata retains original takes. Pause/replay/GET do not submit synthesis jobs. User-selected playback speed is separate from the file's measured original duration; new playback starts at 1× because the requested natural speaking rate is already synthesized into it.

The coordinator and audio engine each have one bounded worker. A database-scoped file lock allows only one chapter coordinator, with at most eight pending/generating jobs. Short SQLite transactions claim jobs and publish state. Startup recovers interrupted jobs from SQLite; cached synthesis and published chapters are reused. Use one application process on the older home laptop. Native audio threads remain controlled by the existing `BBS_TTS_THREADS` (default 2). Image search runs on the same coordinator and can wait behind current narration; it makes bounded serial requests. No Redis, Celery, GPU or new runtime dependency is introduced.

If local packages/models/voices are unavailable, the chapter keeps valid text, records a failed local job, and offers read-along or device speech explicitly marked **unmeasured**. Try local narration again after fixing setup; the stored simulation and prediction remain unchanged. New timed chapters use local Kokoro/Piper only. Existing optional paid-provider configuration/previews are unchanged, but this pipeline does not choose a paid provider or invoke one as a fallback. Model downloads never occur at startup. Device speech cannot guarantee these timing targets.

## Individual image management

In **Settings → Grown-up controls → Creature Images**, search the local creature list by common/scientific name or category. Choose one animal to see its current image/source. Search automatically, use the scientific name, or enter a custom Commons query; refresh results when desired. Registered candidates are ranked by the existing identity/quality policy, paged in groups of 20, with bounded local WebP previews. Load More prepares the next preview page. Search failures/denials are shown to the adult and never replace the current picture.

**Use this image** downloads and validates that registered candidate for that exact creature, then installs it atomically. Only authenticated, CSRF-protected candidate IDs are accepted, never arbitrary URL/path bodies. Source HTTPS host/redirect checks, robots configuration, timeouts, rate limits/retries, HTTP 401/403 handling, file-size/pixel limits and Pillow validation remain. Missing/restrictive license metadata is still retained without a new license gate. Custom queries cannot authorize another taxon or bypass access restrictions.

The initial picture is snapshotted when first inspected; Internet/generated versions keep their actual installation timestamps when known. Older pictures without installation metadata are labeled with their **first-recorded** timestamp, rather than inventing an installation date. Replacement/restoration keeps previous files and source/creator/license metadata. **Restore** selects an existing registered history entry; a missing/corrupt/out-of-root file is refused. Current cards, profiles and persisted tournament portraits refresh through the shared renderer. Content-versioned URLs prevent stale browser images without clearing caches. Automatic importer installations also clear an obsolete restoration override, retaining all old files/versions.

No full-library import, generated image cleanup or third-party image commit is performed. Existing source/attribution information stays in Settings → Sources & Credits, with applicable displayed attribution retained. Live source access still depends on the server/network policy.

## Ubuntu 26.04 deployment

Use the existing checkout and existing production database. Stop the foreground app with Ctrl+C, or stop your previously configured application service. Keep `data/`, models, images, archived audio, browser legacy sessions and backups. Do not launch a second server on the same port.

After the PR is merged:

```bash
cd ~/bedtime-battle-stories
git fetch origin
git switch main
git pull --ff-only origin main
sudo apt update
sudo apt install python3.14 python3.14-venv
if [ ! -d .venv ]; then python3.14 -m venv .venv; fi
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt -r requirements-audio.txt -r requirements-media.txt
```

For testing before merge, instead use `git fetch origin` and `git switch --track origin/feature/interactive-chapters-image-manager` (or switch to its existing local branch). Preserve/move a mismatched old virtual environment under an unused backup name before recreating it; do not remove production data. The commands assume the normal production path `data/creatures.sqlite3`. If you use another path, export `BBS_DB_PATH=/absolute/path/to/your.sqlite3` and pass that path to each `--db` command below.

Back up and apply the additive migration before restarting:

```bash
.venv/bin/python scripts/manage_chapters.py backup --db data/creatures.sqlite3
.venv/bin/python scripts/manage_chapters.py migrate --db data/creatures.sqlite3
.venv/bin/python scripts/manage_chapters.py status --db data/creatures.sqlite3
```

`migrate` makes its own pre-migration backup as well. `backup` uses SQLite's online backup API, so WAL data is included. Database backups alone do not include image/model/audio files: back up the complete `data/` directory while the service is stopped if you need a full file-and-database recovery copy. No migration invents historical predictions or outcomes.

If no parent credential exists yet, configure the existing shared passphrase locally (never put it in shell history):

```bash
if [ ! -f data/importer/parent-auth.json ]; then
  .venv/bin/python scripts/configure_parent.py
fi
BBS_PYTHON=python3.14 bash START_APP.sh
```

`BBS_IMPORT_DIR` users should check their configured directory instead. An existing passphrase remains valid. The app retains port **8502**. If you already run a custom systemd application unit, restart that same unit instead of the foreground command; the repository does not assume a service name. Keep optional local image-generation services stopped; this upgrade does not enable or run them.

Existing Kokoro/Piper models and cached audio are reused. If Kokoro is not installed yet, explicitly run `.venv/bin/python scripts/setup_audio.py kokoro` after installing audio dependencies; it needs permitted model-host access. See [audio setup](AUDIO.md) and [Python 3.14 compatibility](PYTHON314.md). Starting the app itself never downloads models.

## Verify after deployment

1. Open `http://SERVER_LAN_IP:8502` on the home network. Start an eight-creature adventure. Choose a guess (or Surprise Me), wait for local narration, play/pause/replay, then reveal the winner and continue through all seven chapters. No winner should appear on the active bracket before completion.
2. In Settings, unlock grown-up controls, save 20/30/40/50/60 seconds, tone and prediction/continuity choices. An already prepared chapter must retain its original settings; the next unprepared chapter uses the new ones.
3. Read actual saved audio measurements and checksums:

```bash
.venv/bin/python scripts/manage_chapters.py status --db data/creatures.sqlite3
.venv/bin/python scripts/manage_chapters.py verify --db data/creatures.sqlite3
```

4. Finish a chapter, reload the browser, and use Our saved adventures/Continue. Restart the application with the same command or existing service and confirm the same winner, prediction, chapter text and audio still replay. The adult archive-version panel should retain older takes after explicitly confirmed regeneration.
5. In Creature Images, select **one** creature, search, compare candidates, replace it, then restore the previous entry. Verify its card/profile and tournament portrait update immediately. Re-check source credits. Do not run the full importer for this verification. A denied source or invalid download must leave the current picture intact.

Run automated checks from the checkout:

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python tests/chapters_smoke.py
PYTHONPATH=. .venv/bin/python tests/selection_visibility_smoke.py --full-regression
```

The browser scripts need the optional Playwright package and system Chromium (`/usr/bin/chromium`); install them only for browser testing. They use temporary databases, synthetic WAVs and mocked image HTTP. The legacy full-flow regression explicitly exercises the original session API; the dedicated chapter smoke exercises actual persistent APIs, prediction/reveal screens and server restart. Normal unit tests do not require Internet, paid services or real TTS models.

## Observed validation and limits

Real CPU Kokoro on Python 3.14.9 with `af_heart` at natural rate 0.95 generated and archived:

| Target | Measured narration | Attempts for that take | Observed wall time |
| --- | --- | --- | --- |
| 20 s | 19.329 s | 1 | 12.46 s |
| 40 s | 39.349 s | 2 (first 31.323 s) | 41.98 s total |
| 60 s | 60.014 s | 1 | 35.71 s |

These are measured examples on the cloud CPU, not a guarantee for every voice, creature-name length or the Dell laptop. An earlier 60-second take at 56.619 seconds was correctly retained with `timing_met:false`; finer text adjustment subsequently achieved the 60.014-second take in a new test tournament without rewriting that earlier record. Unit tests cover all five duration settings, bounded unsuccessful timing, caching, recovery and original-audio preservation. Audible quality and native iPhone Safari remain unverified. Browser mobile Chromium emulation passes the interactive flow, but is not physical iPhone testing.

Real narration validation used the installed isolated Python 3.14 audio runtime; the core-only Python 3.12 environment correctly reported its missing Sherpa dependency and retained readable text. Piper package/fallback integration is preserved, but actual Piper voice synthesis was not revalidated here because its voice model is absent. No paid API was called.

Image-manager network/file/serving behavior is tested with mocked sources and synthetic local images, including restoring an actual previous WebP and preserving immutable old URLs. Current cloud policy still blocks live Commons access; no claim is made about successful live replacement or visual quality in this environment. No full-library image run occurred. Native Ubuntu 26.04 on the physical Dell and hardware Safari playback still require the deployment checks above.

Final automated totals for this change: **316 passed on Python 3.12 and 316 passed on Python 3.14 with optional media dependencies**. Core-only Python 3.14: **271 passed, 45 optional media checks skipped**. The 31 new cases cover simulation/prediction independence, all five duration targets, measured WAVs/calibration, bounded timing misses, cache/archival publication, actual fallback-voice persistence, restart recovery, chapter continuity/version preservation, history pagination, migration, image search/pagination/preview/replacement/restoration and unsafe URL/file handling. A migration of a copy of the current 164-creature database preserved every row of all seven existing tables and fabricated no historical adventures or guesses. Cache deletion waits until chapter publication is finished; completed archived narration survives deletion of ordinary cached audio.
