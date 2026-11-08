# Bedtime Battle Stories

A dark, mobile-first bedtime adventure picker for an Ubuntu home server. Phase 1 provides creature browsing, eight-creature selection, bracket setup, and a clearly labeled placeholder player. No accounts, tournament database history, paid APIs, or AI calls.

## Install and run (Ubuntu 24.04 / Python 3.12+)

```bash
sudo apt update
sudo apt install python3 python3-venv
cd bedtime-battle-stories
bash START_APP.sh
```

Open `http://SERVER_LAN_IP:8502` on the same home network. Port 8501 is untouched. Keep access on a trusted LAN; do not forward this port from your router. The app has no authentication. If UFW is enabled, allow port 8502 only from your actual home subnet, not the whole Internet.

The production library starts empty. To exercise Phase 1 with the separate development library:

```bash
BBS_SAMPLE_DATA=1 bash START_APP.sh
```

This uses `data/sample.sqlite3` and loads 24 labeled sample entries (8 dinosaurs, 8 sharks, 8 marine reptiles) from `data/sample_creatures.json`. It does not populate `data/creatures.sqlite3`. The sample provides species identities and broad habitats; measurements and detailed abilities are deliberately unset pending scientific review. Seeding is idempotent and preserves existing rows. Use a separate `BBS_DB_PATH` when experimenting; never point sample mode at your production database.

Stop with Ctrl+C in the terminal running the app. Restart by running the same startup command. To restrict access to the server itself:

```bash
BBS_HOST=127.0.0.1 bash START_APP.sh
```

`BBS_PORT` overrides 8502; `BBS_DB_PATH` overrides the database path. Relative paths are resolved from the repository when using the startup script. Back up SQLite data before upgrades. Keep secrets out of the repository; none are required for Phase 1.

## Use

Choose a category, search common or scientific names, and tap eight creatures in pairing order (or use “Pick eight for me”). Choose realism and 1-, 2-, or 3-minute story settings, optionally shuffle, and create a complete seven-match bracket. Hear buttons pronounce names using browser speech synthesis when available. The placeholder player does not generate or narrate stories.

The current bracket survives reloads in that tab using sessionStorage. Starting another bracket replaces it. There is no server-side tournament history. Browser session restoration may retain tab storage; storage is not a privacy guarantee. Back navigation preserves selection while the page remains open. After five idle minutes the app enters a quiet screen; active speech or audio defers this until playback ends. Resume manually.

## Tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Optional mobile browser regression (run a sample server in another terminal first):

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
# Install Chromium using your system package manager if needed.
BBS_SAMPLE_DATA=1 bash START_APP.sh
# In a second terminal:
.venv/bin/python tests/mobile_smoke.py
```

The browser script uses `/usr/bin/chromium`; set `CHROMIUM_PATH` for another installation. It tests a 390×844 touch viewport, including search, selection, shuffle/settings, bracket persistence, player, simulated timeout and horizontal overflow. It does not validate physical iPhone Safari, Android Chrome, pronunciation quality, or real narration. No paid services are used.

## Architecture

- `app/main.py`: FastAPI lifespan/database initialization, search/filter API, unbiased random sampling, shared-arena compatibility, validated bracket construction.
- `data/sample_creatures.json`: opt-in development fixtures; separate from production SQLite.
- `static/`: responsive HTML/CSS and vanilla JavaScript; replaceable pronunciation adapter, tab-session bracket state, idle policy.
- `tests/`: isolated temporary SQLite tests and optional mobile browser regression.
- `START_APP.sh`: virtual environment creation, dependency installation, configurable LAN startup.

API: `GET /api/config`, `GET /api/creatures?category=dinosaur&q=rex`, `GET /api/selection/random?category=shark`, `POST /api/tournament`. Categories are dinosaur, shark, marine_reptile. Exactly eight distinct integer IDs are required. Realism accepts realistic/balanced/anything; duration accepts short/normal/long. Match IDs, source-match IDs, pending status and winner slots support future progression. No winner advancement endpoint exists yet.

Habitat rules map land, marine, and semi_aquatic habitats to supported arenas. Every participant must share an arena. Sharks and marine reptiles can share water; land-only animals cannot. Unknown habitats fail closed. This is a conservative foundation; species-specific depth, salinity and mobility constraints require Phase 2 review. Current random category selection is uniform without replacement; a future mixed-habitat category needs an explicit arena filter rather than silently excluding candidates.

## Limitations and roadmap

Phase 1 does not simulate battles, advance winners, create stories/images, or play narrated audio. Duration and realism are retained settings for future phases. Speech synthesis is browser-dependent and not verified scientific pronunciation. Dependencies use supported version ranges rather than a lockfile. Plain HTTP is intended only for a trusted home LAN.

Phase 2: curated, sourced species catalog (100+ dinosaurs, 40+ sharks, marine reptiles), reviewed habitats and pronunciations. Phase 3: seeded battle simulation, outcomes and winner advancement. Phase 4: optional server-side AI stories, illustrations and narration with explicit credentials and cost controls. Phase 5: audio reliability, physical-device testing and deployment polish.
