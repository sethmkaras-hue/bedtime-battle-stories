# Bedtime Battle Stories · Version 2

A mobile-first bedtime adventure game for an Ubuntu home server. Choose eight creatures, play a friendly story tournament, and advance through seven chapters to a champion. Everything runs locally: no accounts, paid APIs, AI generation, or permanent tournament history.

## Ubuntu installation and startup

Requires Python 3.12+ (Ubuntu 24.04 provides it).

```bash
sudo apt update
sudo apt install python3 python3-venv
cd bedtime-battle-stories
bash START_APP.sh
```

Open `http://SERVER_LAN_IP:8502` on the same home network. Port 8501 is untouched. Stop with Ctrl+C; restart with the same command. Do not forward this port from your router: this app has no authentication and is intended for a trusted home LAN. If using UFW, allow port 8502 only from your actual home subnet.

The default library now loads 164 editorial catalog records: 110 dinosaur genera, 42 shark species, and 12 marine reptiles. Existing creature IDs and profiles are preserved. Missing pronunciation guides can be filled; custom guides are retained. New catalog entries are added, not used to replace existing user profiles. Back up `data/` before an upgrade. Database schema additions are additive; no tournament history is stored there.

To update from Version 1 after this branch is merged, stop the app, back up `data/`, run `git pull --ff-only` on main, then run `bash START_APP.sh`. If you previously enabled `BBS_SAMPLE_DATA=1`, unset it for the full library. An explicitly configured `BBS_DB_PATH` is retained; do not accidentally reuse the development sample database as your production database.

Configuration:

- `BBS_HOST`: defaults to `0.0.0.0` for home LAN access; use `127.0.0.1` for server-only access.
- `BBS_PORT`: defaults to 8502.
- `BBS_DB_PATH`: database override, default `data/creatures.sqlite3`.
- `BBS_CATALOG=0`: disables bundled catalog additions (does not delete already loaded records).
- `BBS_SAMPLE_DATA=1`: uses the separate 24-creature development sample library at `data/sample.sqlite3` unless a database override is set. Never point sample mode at production data.

## Play

Choose Dinosaurs, Sharks, Prehistoric Sea Creatures, or Ocean Mix. Search common/scientific names, open a creature's details, then select eight in pairing order or pick eight randomly. Ocean Mix lets sharks meet marine reptiles; every tournament must share a supported arena. Land-only creatures cannot enter water tournaments. Semi-aquatic habitat rules are supported; specific disputed swimming abilities are not assumed for catalog dinosaurs.

Choose realism, chapter length, and optional shuffled matchups. Listen to the next chapter or read along. Play, pause/resume, replay, stop, and story-speed controls use device speech synthesis. The winner remains hidden in the visible player until the narration finishes or you tap “Reveal the ending.” Winners automatically populate the semifinals and championship. Finishing all seven chapters shows the champion.

Chapters use locally written, non-graphic templates. Everyone stays safe. The 1/2/3-minute choices scale word count; actual playback time depends on the chosen voice and speed. No images are supplied yet. These are fictional adventure contests, not scientific combat simulations: editorial game ratings and 10%/30%/50% upset chances for unequal ratings distinguish Realistic/Balanced/Anything Can Happen. Equal ratings use an even choice. Outcomes are reproducible for a given seed, match, ratings, realism and entrant ordering.

Your bracket, seed and completed-chapter count are retained in this tab's sessionStorage and reconstructed after reload. Browser session restoration may retain this storage. Starting a new tournament replaces the current one; no server-side tournament history is saved. After five idle minutes, quiet mode stops paused/idle playback. Active speech or audio defers the timeout. Resume manually.

## Pronunciation

Open **Voice & pronunciation** to select an English voice, slow down names, and toggle guided pronunciation. Dinosaur and marine-reptile entries have written approximate English pronunciation guides. Shark buttons use their common names. The same adapter replaces creature names in narrated stories. Voice preferences are saved locally; Hear buttons remain available in the library and bracket.

Existing Version 1 sample databases receive missing guides without replacing custom pronunciation. Guides are approximate, not verified scientific audio. Browser engines interpret respellings differently. Choose the clearest voice on the actual device; some voices may require a device-managed download or network connection. If speech is unavailable, the written story and guides still work. No guarantee of natural audio quality is claimed from headless tests.

## Catalog quality

`data/catalog.json` is an initial editorial catalog, **not a scientifically verified catalog**. It records taxonomic rank, broad diet/habitat, a pronunciation guide, and suggested museum reference links. Source checks were blocked by the build environment's outbound policy; links are reference starting points, not per-claim citations. Every newly inserted catalog profile is marked `reference_check_pending`. All measurements remain unknown. Existing parent-entered profiles are not silently replaced by catalog descriptions.

Scientific review, species-specific provenance, finer habitat constraints, measurements, abilities, and pronunciation recordings remain outstanding. The museum references need review for coverage and current URL validity. Do not treat game ratings as scientific facts.

## Tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Mobile browser integration (run the default-catalog server first):

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
# Install Chromium with your system package manager if needed.
.venv/bin/python tests/adventure_smoke.py http://127.0.0.1:8502
```

The script uses `/usr/bin/chromium` (override with `CHROMIUM_PATH`). It covers a 390×844 touch viewport, pronunciation adapter output, speech controls, seven chapters, winner advancement, reload recovery, champion, ocean mixing and timeout. Speech is stubbed for deterministic completion; audible quality and physical iPhone Safari/Android Chrome require device testing. `tests/mobile_smoke.py` retains the older sample-library regression.

## Architecture

- `app/main.py`: FastAPI, SQLite initialization, additive catalog loading, search, random sampling, habitat validation and API schemas.
- `app/adventure.py`: seed-based fictional outcomes, local story templates and canonical bracket progression.
- `data/catalog.json`: editorial catalog with review status; `data/sample_creatures.json`: isolated development fixtures.
- `static/`: responsive interface, voice adapter, story player, session state and quiet mode.
- `tests/`: isolated SQLite/API tests and browser integrations.
- `START_APP.sh`: virtual environment creation, dependency installation and configurable LAN startup.

API: `GET /api/config`, `GET /api/creatures?category=dinosaur&q=rex`, `GET /api/selection/random?category=ocean`, `POST /api/tournament`, `POST /api/adventure`. A tournament takes eight distinct integer `creature_ids`, `realism`, `duration`, optional `shuffle` and `seed`. Adventure reconstruction adds `completed` (0–7). No client-supplied winner or bracket is trusted; the server reconstructs outcomes. Endings are present in chapter responses to support speech but are not shown early by the normal UI. These are local game controls, not an anti-cheat protocol.

## Next development

Review the catalog against accessible scientific sources and listen to difficult names on real devices. Then replace generic game ratings with reviewed traits and configurable, documented simulation rules; vary authored stories by capabilities and habitat. Generated stories, illustrations, verified pronunciation recordings and narration services remain future work requiring explicit configuration and cost controls. Dependencies currently use version ranges rather than a lockfile.
