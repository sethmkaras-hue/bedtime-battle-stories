# Short battles, winner choices and spoken creature names

New unprepared chapters default to **20 seconds of measured local narration**, with 18–22 seconds accepted. The worker calibrates text length for the actual engine/voice/rate, measures the WAV, and tries at most three takes. It keeps the closest valid take and discloses timing misses instead of accelerating speech. Custom 30/50/60-second settings remain; the former default of 40 changes to 20 once during migration. A grown-up can subsequently choose 40 again. Prepared chapters, historical settings, outcomes and archived audio remain unchanged unless a grown-up explicitly regenerates a chapter.

## What changed

Before each new fight, **WANT** selects its actual winner; **THINK** predicts it. Either question can be skipped independently. WANT is saved immediately, before THINK and any synthesis. Choosing a winner uses a separate deterministic resolution path; skipping WANT uses the existing seeded simulation. THINK cannot influence either path. The result is committed before narration starts; refresh, retry, replay and restart reuse it. Grown-up prediction settings can hide THINK without disabling WANT.

SQLite receives nullable `desired_winner_id`, `desired_submitted`, `winner_method`, and `choices_submitted` battle columns, a migration marker, and a separate `spoken_name_assets` cache registry. Existing prediction JSON retains predicted/actual winner IDs, correctness and timestamp; tournament and battle IDs already identify each record. History displays WANT, THINK and actual winner/method. Old records retain null new fields and are labeled as earlier results, without invented choices. Migration backs up existing databases before altering them.

Each known matchup has **Play Battle**, completed fights have **Replay Battle**, and unknown matchups have disabled **Waiting for Winners**. Quarterfinals can be played in any order. A semifinal needs both feeder results; the championship needs both semifinals. Winners appear in the next round as soon as established. Mobile uses a vertical bracket, remembers the selected card's scroll position, highlights the completed card and labels the next available fight. All seven connected chapters remain, with brief continuity and a championship finish.

Combat now includes attacks, counterattacks, bruises/cuts and tactical retreats, with species weapons where supported by reviewed traits or explicit editorial genus rules. Sharks bite and swim; known horned, clubbed and clawed genera use those weapons. Unknown animals use body contact. This fictional choreography does not modify scientific profiles or verification status. Predetermined winners use a dodge, turn or terrain opening to land the decisive blow. No graphic internal anatomy or dismemberment is generated.

## Pronunciation regression and repair

The earlier interface changed picture/card taps into profile navigation and restricted playback to source-verified, explicitly prepared clips. With no verified clips, all 164 inherited entries were silent. Pictures and main cards now speak; **Creature notes** opens the profile, and Add/Remove remains separate. WANT/THINK cards select an answer; their pictures deliberately do not trigger competing speech.

Prepared clips are preferred. Missing/corrupt clips enqueue bounded local work through the existing CPU audio service, with Piper→Kokoro local fallback. Generated files are cached by engine/model/voice/text/rate and registered against the current name/guidance signature. WAV integrity and registered URLs are checked before serving `audio/wav`. Broken files can be repaired on another tap without refreshing. Ordinary cache clearing removes generated names but preserves archived battle narration; a later tap prepares the name again.

Verified source TTS guidance is used when present. Otherwise the display name is synthesized and marked **synthesized_display_name / verified_pronunciation:false**; it is not an authoritative pronunciation or an invented respelling. All 164 catalog entries have supported local spoken-name recipes. The research CLI remains available to prepare verified guidance in bulk; no full-library synthesis runs at startup. Settings still exposes missing dependencies/models and provider errors. No paid fallback is chosen.

One reusable HTML audio element handles names; a new name tap cancels the previous name and pauses narration. Narration playback cancels pending names. Rapid taps cancel stale frontend work and the queue deduplicates identical requests. Safari receives a short silent audio unlock within the original gesture. If it still blocks playback after background generation, the UI asks for another tap and reuses the ready file. If both local voices fail, a device voice is disclosed as fallback. Physical iPhone playback and audible pronunciation quality still need the checks below.

## Ubuntu 26.04 / Python 3.14 update

Stop the running app with Ctrl+C. From the existing checkout (substitute its actual directory and any existing custom data environment variables):

```bash
cd ~/bedtime-battle-stories
git status --short
git fetch origin
# Until the PR is merged:
git switch feature/short-battles-choices-pronunciation
git pull --ff-only origin feature/short-battles-choices-pronunciation
# After merge, use main and git pull --ff-only origin main instead.

.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt -r requirements-audio.txt -r requirements-media.txt
.venv/bin/python scripts/manage_chapters.py backup
.venv/bin/python scripts/manage_chapters.py migrate
.venv/bin/python scripts/manage_chapters.py status
.venv/bin/python scripts/manage_chapters.py verify
BBS_PYTHON=python3.14 bash START_APP.sh
```

These commands assume the existing `.venv` is Python 3.14; do not replace an environment that already works. If starting fresh, first run `python3.14 -m venv .venv`; see [runtime and model installation](PYTHON314.md). Dependencies are unchanged by this update. Keep your existing `data/` directory, image files, models, ordinary cache, archived chapters and parent passphrase file. Custom database deployments must pass the same `BBS_DB_PATH` or `--db` to management commands. Startup also performs the additive migration automatically.

Models are not downloaded on startup. Only if missing, use the existing deliberate commands:

```bash
.venv/bin/python scripts/setup_audio.py kokoro
# Optional; Kokoro also handles names if Piper's voice host is unavailable:
.venv/bin/python scripts/setup_audio.py piper
```

Use one app process on the home CPU. First inference loads the model; a name can wait behind the current chapter job. Lower CPU speed can increase preparation time without changing playback speed. Settings → Audio shows provider availability and missing files. HTTP/model failures do not erase history or require paid services.

## iPhone acceptance checks

1. Put phone and Ubuntu machine on the same Wi-Fi; open `http://<Ubuntu-LAN-IP>:8502` in Safari. If using an existing tab after upgrading, reload once to load the new JavaScript. No refresh is required for subsequent missing-name generation.
2. Start an adventure, select a category, tap a picture/card, then its speaker. Wait for first-time preparation; if prompted, tap again. Try another name rapidly and confirm only the latest plays. Open Creature notes separately. Repeat with a shark and an ocean reptile.
3. Select eight creatures. Scroll to quarterfinal 4 and use its Play Battle. WANT one competitor and THINK the other. Listen at natural speed, reveal, and confirm WANT won and THINK was incorrect. Follow the adventure back: the completed card stays at the same location, is highlighted, and has Replay Battle.
4. Replay without answering again; verify the same result and audio. Skip WANT and THINK separately in other fights. Check a locked semifinal cannot launch until both results exist. Finish all seven fights and verify the champion and saved choice history.
5. Reload/resume and restart the server, then replay an old chapter. Its old duration/audio/result must remain. While narration plays, tap a creature speaker and confirm narration pauses; resume narration and confirm names stop. Confirm portrait/landscape layouts have usable touch targets and no sideways scrolling.
6. In grown-up Settings, confirm 20 seconds for future fights and inspect provider errors if speech is missing. `scripts/manage_chapters.py verify` reports actual archived WAV duration/checksum and timing status, independently of the browser display.

## Validation observed here

Full unit suites and mobile Chromium tests use temporary databases, synthetic CPU WAV adapters and mocked external HTTP; no paid services or production data are used. Cases cover desired-vs-predicted winners, idempotency, independent skips, eligible/out-of-order matchups, feeder locks, all 164 name recipes, cached/corrupt WAV delivery, non-destructive migration, anatomical combat, existing audio, seven chapters, restart, saved choices and scroll restoration. Mobile browser tests additionally play prepared/generated name files and chapter WAVs through HTML audio.

Real CPU Kokoro on Python **3.14.9**, `af_heart`, natural rate **0.95**, generated a new physical Allosaurus/Ankylosaurus battle at **20.217 seconds** after two takes (first 14.392 seconds), taking **20.07 seconds** total on this cloud CPU. Text was lengthened after measuring the first take; the speaking rate stayed unchanged. Real cached name files for Allosaurus and Ankylosaurus measured **1.183** and **1.361 seconds**, with about **1.01 seconds** preparation each. These are examples, not guarantees for every voice or name. Generated artifacts stayed outside the repository.

Physical iPhone Safari, audible quality, native Ubuntu 26.04 and the home Dell CPU were not available here. Actual Piper voice synthesis remains unverified because its model is absent; the local Kokoro fallback is covered. No images, catalog records, existing production histories or audio were regenerated by this work.

Final automated results: **330 passed on Python 3.12; 330 passed on Python 3.14 with optional audio/media dependencies; 285 passed and 45 optional media checks skipped on core-only Python 3.14.** The focused spoken-name regression also passed after improving stale-file diagnostics. Mobile Chromium passed the persistent chapter flow (including a simulated Safari `NotAllowedError` and second-tap recovery), full 164-entry catalog visibility, the legacy seven-battle flow, profile/search/selection, prepared-file playback and image replacement/restoration. A simulated Safari rejection tests our recovery code, not the Safari engine itself.

Repeat automated checks from the checkout:

```bash
.venv/bin/python -m pytest -q
# Optional Playwright and system Chromium must already be installed:
.venv/bin/python -m tests.chapters_smoke
PYTHONPATH=.:tests .venv/bin/python tests/selection_visibility_smoke.py --full-regression
```
