# Bedtime Battle Stories

A little adventure book for bedtime. Pick eight dinosaurs, sharks or ancient sea creatures, listen to seven friendly story battles, and discover tonight’s champion. Built for a child and supervising parent on a home network: FastAPI, SQLite, vanilla JavaScript, no accounts and no saved tournament history.

## Start on Ubuntu 24.04 or 26.04

Core Python 3.12+ is required; standard CPython 3.14 is tested for core and CPU audio. On Ubuntu 26.04, use Python 3.14. Port **8502** remains the default; port 8501 is untouched.

```bash
sudo apt update
sudo apt install python3 python3-venv
cd bedtime-battle-stories
bash START_APP.sh
```

Visit `http://SERVER_LAN_IP:8502` on your home Wi-Fi. Stop with Ctrl+C; restart with the same command. This basic setup uses device speech until local models are installed. Do not expose the unauthenticated app publicly or forward its port from your router. If using UFW, restrict access to your actual home subnet.

## Free CPU narration and pronunciation

No GPU, CUDA, paid API or account is needed. Install these once, from the repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-audio.txt
.venv/bin/python scripts/setup_audio.py all
bash START_APP.sh
```

The setup command explicitly downloads Kokoro and Piper models; normal startup never downloads them. Kokoro runs through Sherpa-ONNX (compatible Python 3.14 wheels) and narrates with Heart by default; Piper uses the clear English Lessac voice for names. If one local engine is missing, the other is tried before device speech. OpenAI is never selected automatically.

Model downloads need GitHub release access and Hugging Face access (including its CDN redirects). Kokoro files occupy about 338 MiB; the selected Piper voice is roughly 60–70 MiB plus its JSON configuration. Allow at least 1–2 GB of disk for models and Python packages, and about 2 GB free RAM for comfortable single-worker CPU use. These are planning allowances, not minimum-hardware guarantees. See [audio setup and troubleshooting](docs/AUDIO.md).

## Ubuntu 26.04 / Python 3.14 upgrade

`kokoro-onnx==0.6.1` excludes Python 3.14. This version uses **sherpa-onnx 2.0.1**, **ONNX Runtime 1.31.1** and maintained **piper-tts 1.8.0**, without ignoring package compatibility checks. Kokoro uses an explicit English IPA phonemizer so words absent from a finite lexicon are not silently skipped.

Stop the app and back up `data/`. Check `.venv/bin/python --version`: if the old environment is broken or uses another Python minor version, preserve it under an unused backup name before creating a new one. Do not delete the creature database, cache or models.

```bash
sudo apt update
sudo apt install python3.14 python3.14-venv
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-audio.txt
.venv/bin/python scripts/setup_audio.py kokoro
.venv/bin/python scripts/setup_audio.py piper
BBS_PYTHON=python3.14 bash START_APP.sh
```

Run each setup command separately so a Piper network failure is distinguishable from Kokoro installation. `START_APP.sh` now detects a mismatched/broken virtual environment instead of using it silently. `BBS_VENV` can select another environment directory. Core-only operation still needs only `requirements.txt`.

The new Kokoro bundle goes in **data/models/kokoro-sherpa/**. Use the downloader; do not rename old `kokoro-onnx` files into it. Old models and cached audio are preserved, while model/runtime fingerprints prevent incorrect cache reuse. Model setup is repeatable and not run at startup.

Piper's Python 3.14 package/CLI and native phonemizer work in validation. Its official voice host still returned a proxy-policy 403 in this cloud. That is a network-access issue, not an obsolete package source. Where the voice is unavailable, Kokoro handles both stories and names locally; OpenAI remains opt-in and browser speech is the final fallback. Settings gives the missing-package/model reason and last generation-error type. See [compatibility investigation](docs/PYTHON314.md).

## Creature book, research and prepared names

Explore the creature book from Home without starting a tournament. Tap a creature picture for its profile and source/image credits. Selection keeps a separate Add/Remove action. Featured/category trails are available; biological trait trails show only reviewed claims. Existing creature IDs and fictional game ratings are preserved independently of encyclopedia data.

**Research is incomplete:** outbound policy blocked the museum/Commons sources. The inherited **110 dinosaur genera, 42 sharks and 12 marine reptiles remain unverified**; no new verified taxa or licensed species photos were added. All 164 images are explicitly marked placeholders. Verified pronunciation coverage and prepared name audio are both **0/164**. [The full audit](docs/CREATURE_AUDIT.json) names every unresolved record; [the maintenance guide](docs/CREATURE_LIBRARY.md) gives target gaps, schema, licensing and research steps. No target was met by inventing facts.

Creature speakers now play **pre-generated local audio only**, never request TTS on tap. Missing audio shows a written fallback. After researching and importing verified guidance, a parent runs:

```bash
bash GENERATE_PRONUNCIATIONS.sh --provider kokoro --voice af_heart \
  --report data/pronunciation_report.json
```

Repeat runs reuse current audio. The command skips unverified names, including inherited respellings. Parent voice previews remain explicit generation actions; story narration and its cache are preserved. To curate and inspect records:

```bash
.venv/bin/python scripts/library.py export --output /tmp/creatures-for-review.json
.venv/bin/python scripts/library.py schema --output /tmp/creature-schema.json
.venv/bin/python scripts/library.py validate /path/to/reviewed-creatures.json
.venv/bin/python scripts/library.py import /path/to/reviewed-creatures.json
.venv/bin/python scripts/library.py audit --output data/library_audit.json
```

Image preparation and real-image import validation use optional `requirements-media.txt`. Read the [licensed media workflow](docs/CREATURE_LIBRARY.md) before importing assets; never assume museum content is redistributable. Reviewed records, pronunciations and artwork are protected against automatic overwrites.

## Tonight’s adventure

1. **Start Adventure** → choose dinosaurs, sharks, prehistoric ocean creatures, or a compatible Ocean Mix. **Surprise Me!** creates a random valid tournament directly.
2. Pick eight large creature cards, or use **Random 8**. Eight visible slots preserve selection order and let you remove a creature. Popular creatures appear first; adult search and the full library are expandable.
3. Follow the connected quarterfinal → semifinal → championship → winner bracket. **Focus on Current Battle** finds the next match without shrinking names.
4. **Watch This Battle!** opens the illustrations, audio player and optional read-along text. Audio preparation runs in the background. Play, pause/resume, replay, speed, seeking and time/duration use HTML5 audio. On iPhone, tap Play if automatic playback is blocked.
5. The winner is shown only after narration finishes or the parent chooses **I’ve read it · reveal the ending**. After seven battles, celebrate the champion. Play Again and New Adventure never start automatically.

The gear stays available throughout the experience. Settings save on that device: separate narration/name providers, voices, previews and speeds; automatic narration; speaker buttons; pronunciation guides; 1–3 minute chapter defaults; realism; shuffle; bedtime timeout; reduced motion; and audio-cache management. Opening settings preserves the tournament. Story-setting changes apply to the next tournament. Names on cards remain unchanged when pronunciation overrides are used.

Quiet mode defaults to five idle minutes, preserves progress, and offers a large Wake Up button. Active playback and audio preparation for the current battle defer it. Operating-system reduced motion is respected alongside the app preference.

## Data and upgrades

Before updating, stop the app and back up `data/` (SQLite plus any models/cache you want to retain). After merging a reviewed PR:

```bash
git switch main
git pull --ff-only
bash START_APP.sh
```

If audio dependencies changed, refresh them with `.venv/bin/python -m pip install -r requirements-audio.txt`. Existing profiles/IDs, custom pronunciation guides, models and cached audio are preserved. New models require a deliberate setup command, not an application restart. Restart the app after changing model files.

The catalog still contains **110 dinosaur genera, 42 shark species and 12 marine reptiles**. It is editorial, not a verified 100-species dinosaur catalog. Scientific reference checks, measurements and fine habitat constraints remain pending. Existing data and deterministic game ratings are preserved. Game outcomes are fictional rules, not scientifically validated predictions. Stories are locally authored templates, not AI-generated narratives. Generic local illustrations are decorative placeholders, not species-accurate reconstructions. Existing illustrations can be referenced using safe `/static/...` paths; no external image requests are required.

SessionStorage keeps only the current tab’s entrants, seed, settings and completed-chapter count. The server reconstructs outcomes; it stores no tournament history. Browser session restoration can retain tab storage. Audio files persist by content hash for reuse; they contain generated story/name audio, not a tournament-history database.

## Configuration

`.env.example` documents optional configuration; it contains no credentials. Export desired values before running START_APP.sh; the app does not silently source `.env`.

| Variable | Default / purpose |
| --- | --- |
| `BBS_PYTHON` | `python3`; select `python3.14` explicitly on Ubuntu 26.04 |
| `BBS_VENV` | `.venv`; startup checks its interpreter matches `BBS_PYTHON` |
| `BBS_HOST` | `0.0.0.0` for trusted LAN; use `127.0.0.1` for local-only |
| `BBS_PORT` | `8502` |
| `BBS_DB_PATH` | `data/creatures.sqlite3` |
| `BBS_CATALOG` | `1`; `0` stops adding bundled catalog entries, without deleting data |
| `BBS_SAMPLE_DATA` | `0`; `1` uses separate `data/sample.sqlite3` unless DB path is overridden |
| `BBS_MODEL_DIR` | `data/models` |
| `BBS_AUDIO_CACHE` | `data/audio_cache` |
| `BBS_TTS_THREADS` | `2`, bounded to 1–4 ONNX CPU threads |
| `BBS_ENABLE_OPENAI` | `0`; explicit `1` required for paid audio |
| `OPENAI_API_KEY` | Optional server-only key, never returned to the frontend |
| `BBS_OPENAI_MODEL` | `gpt-4o-mini-tts`, configurable as provider models evolve |

Never point development sample mode at a production database. Unset `BBS_SAMPLE_DATA` to use the full catalog.

## Tests and evidence

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tests/redesign_smoke.py http://127.0.0.1:8502 /tmp/bedtime-screenshots
.venv/bin/python tests/library_smoke.py http://127.0.0.1:8502 /tmp/bedtime-library-screenshots
```

Normal tests use temporary data and mocked audio; models and paid API calls are not required. Browser tests use system Chromium (`CHROMIUM_PATH` overrides `/usr/bin/chromium`) and deterministic audio transport. They cover settings persistence, selection/removal, speaker controls, bracket progression, all seven battles, cache confirmation, HTML audio pause/resume/replay, quiet mode and mobile overflow. The older browser-script entry points delegate to this flow.

**Earlier Python compatibility validation:** Real CPU Kokoro generation, five voice selections, disk-cache hits and a real HTML pronunciation playback passed against a **Python 3.14.9** server. The earlier Python compatibility change passed 59 tests across those environments. This library change passes 78 tests with media dependencies installed; its mobile tests cover profiles and prepared-file playback using fixtures. Piper’s native extension, CLI and phonemizer were exercised on 3.14; its actual voice model was blocked by outbound policy, so full Piper inference remains unverified. These tests ran on Debian Linux, not a native Ubuntu 26.04 image. Physical iPhone Safari and the home laptop were not tested; no audible-quality claim is made. See [measurements and limitations](docs/PYTHON314.md).

## Architecture

- `app/library.py`, `app/library_routes.py`: versioned profile/provenance records, protected imports, audits and read-only prepared pronunciation delivery.
- `app/main.py`, `app/adventure.py`: existing SQLite library, compatibility rules, reproducible game outcomes and local chapters. Catalog loading is initialized once per active database configuration rather than repeated for every request.
- `app/audio/providers.py`: optional Kokoro, Piper and official OpenAI SDK adapters; CPU sessions and model-aware identity.
- `app/audio/service.py`: one worker, eight pending jobs, duplicate suppression, atomic WAV publication, persistent content-addressed cache and bounded job metadata.
- `app/audio/routes.py`: providers, jobs, safe audio URLs, cache management and local benchmark API.
- `static/settings.js`, `static/audio-player.js`, `static/app.js`: reusable preferences/playback modules and the child-facing flow. No frontend framework, remote fonts or image dependency.
- `static/assets`: locally bundled illustrative SVGs. `data/catalog.json`: existing editorial library. Models and generated audio are Git-ignored.

Next work: verify catalog facts and scientific names, test pronunciation and native audio on the actual iPhone, vary story templates and add reviewed species-specific illustrations. AI story/image generation remains outside this change.

## Populate and review the creature library

Use `./IMPORT_CREATURE_LIBRARY.sh --pilot 10` before `--all`. The importer researches exact scientific identities, queues licensed image candidates and pronunciation guidance, backs up changes and resumes interrupted work. Configure the adult Settings review with `.venv/bin/python scripts/configure_parent.py`; approvals preserve explicit review status. Local audio is generated only from approved guidance, never on a child's speaker tap.

See [exact Ubuntu 26.04 installation, commands, supported sources and limitations](docs/CREATURE_LIBRARY.md#automated-population-on-ubuntu-2604--python-314). The cloud pilot encountered blocked source access: the 164-record encyclopedia remains incomplete, with no newly verified real facts, images or pronunciations claimed.
