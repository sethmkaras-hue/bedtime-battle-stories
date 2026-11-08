# Bedtime Battle Stories

A little adventure book for bedtime. Pick eight dinosaurs, sharks or ancient sea creatures, listen to seven friendly story battles, and discover tonight’s champion. Built for a child and supervising parent on a home network: FastAPI, SQLite, vanilla JavaScript, no accounts and no saved tournament history.

## Start on Ubuntu 24.04

Python 3.12+ is required. Port **8502** remains the default; port 8501 is untouched.

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

The setup command explicitly downloads Kokoro and Piper models; normal startup never downloads them. Kokoro narrates with Heart by default; Piper uses the clear English Lessac voice for names. If one local engine is missing, the other is tried before device speech. OpenAI is never selected automatically.

Model downloads need GitHub release access and Hugging Face access (including its CDN redirects). Kokoro files occupy about 338 MiB; the selected Piper voice is roughly 60–70 MiB plus its JSON configuration. Allow at least 1–2 GB of disk for models and Python packages, and about 2 GB free RAM for comfortable single-worker CPU use. These are planning allowances, not minimum-hardware guarantees. See [audio setup and troubleshooting](docs/AUDIO.md).

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
```

Normal tests use temporary data and mocked audio; models and paid API calls are not required. Browser tests use system Chromium (`CHROMIUM_PATH` overrides `/usr/bin/chromium`) and deterministic audio transport. They cover settings persistence, selection/removal, speaker controls, bracket progression, all seven battles, cache confirmation, HTML audio pause/resume/replay, quiet mode and mobile overflow. The older browser-script entry points delegate to this flow.

Real CPU Kokoro generation and cache replay were separately measured in the cloud: Heart generated 7.76 s of audio in 5.94 s; Sarah generated 7.49 s in 4.43 s. Peak process RSS after both was about 794 MiB. See [benchmark details](docs/AUDIO.md#measured-validation). Piper’s actual voice download was blocked by cloud outbound policy, so its adapter is mock-tested but real generation and performance remain unverified. Physical iPhone Safari/Android and the home Ubuntu laptop were not tested. No audible voice-quality comparison is claimed.

## Architecture

- `app/main.py`, `app/adventure.py`: existing SQLite library, compatibility rules, reproducible game outcomes and local chapters. Catalog loading is initialized once per active database configuration rather than repeated for every request.
- `app/audio/providers.py`: optional Kokoro, Piper and official OpenAI SDK adapters; CPU sessions and model-aware identity.
- `app/audio/service.py`: one worker, eight pending jobs, duplicate suppression, atomic WAV publication, persistent content-addressed cache and bounded job metadata.
- `app/audio/routes.py`: providers, jobs, safe audio URLs, cache management and local benchmark API.
- `static/settings.js`, `static/audio-player.js`, `static/app.js`: reusable preferences/playback modules and the child-facing flow. No frontend framework, remote fonts or image dependency.
- `static/assets`: locally bundled illustrative SVGs. `data/catalog.json`: existing editorial library. Models and generated audio are Git-ignored.

Next work: verify catalog facts and scientific names, test pronunciation and native audio on the actual iPhone, vary story templates and add reviewed species-specific illustrations. AI story/image generation remains outside this change.
