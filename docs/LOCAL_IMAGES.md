# Local CPU creature illustrations

The normal artwork workflow is now local text-to-image diffusion. No Commons image search, source-photo download, per-image license approval, paid API, GPU or cloud image-generation service is required. Scientific importing and source-backed pronunciation remain separate. Existing creature IDs, scientific profiles, fictional game rules and audio caches are preserved.

**Validation limit:** the CPU runtime installed and imported successfully here, but the cloud proxy rejects Hugging Face model downloads. No real diffusion image, ten-image pilot, scientific-anatomy quality assessment or real-generation performance benchmark was completed. The CLI/SQLite/API/UI tests use a clearly synthetic mock backend. Run the single-image and pilot commands on the home server before committing to the full library.

## Model and runtime choice

| Option | Assessment |
| --- | --- |
| Stable Diffusion 1.5 / Diffusers / CPU float32 | Selected: established 512px pipeline, Linux CPU wheels, portable across Intel/AMD, manageable compared with SDXL/FLUX; supports one image at a time and memory-saving attention/VAE slicing |
| OpenVINO / Optimum Intel | Potential advantage on the Dell's Intel CPU, but needs converted IR artifacts and a separate compatibility/performance check; no meaningful Dell benchmark is available here, so no speed advantage is claimed and it is not silently selected |
| Compact/turbo models or quantized external runtimes | Can trade detail/compatibility for lower time/RAM; not the implemented preset. No untested adapter or anatomy-quality improvement is claimed |

Default model: [`stable-diffusion-v1-5/stable-diffusion-v1-5`](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5). The published model license is **CreativeML Open RAIL-M**, with use restrictions; inspect the publisher's current model card/license when downloading. The setup retains README/license files and records the actual immutable snapshot commit. This identifies the model license, not a guarantee about copyright or scientific correctness of generated outputs.

The isolated Python **3.12** environment pins `torch 2.7.1+cpu`, `diffusers 0.35.1`, `transformers 4.56.2`, `accelerate 1.10.1`, `huggingface-hub 0.34.4` and `safetensors 0.6.2`. These installed and imported together on Linux in this session. The existing FastAPI Python 3.14 environment is not downgraded. Model weights were unavailable, so successful library imports are not represented as successful model initialization/inference.

Expect several GB of model/runtime storage; allow roughly **10–15 GB free disk** for the environment, cached FP32 weights and working room. WebP illustrations are usually much smaller than the model, but actual file sizes depend on output. Old successful versions are kept; repeated force regeneration grows storage. Budget **16 GB installed RAM or more**, with at least **8 GiB currently available** for the conservative 512px preset; 24–32 GB gives more room for the app, narration and other workloads. These are planning/guardrail values, not measured minimums or guarantees. Larger resolutions require more available RAM. `--check` detects CPU name, affinity, AVX2, physical/effective RAM and cgroup limits on the machine actually running the command. The cloud machine is not the Dell.

## Exact Ubuntu 26.04 setup

From the repository, preserve your existing `data/` and restart the app after updating its code. The web app can keep its Python 3.14 environment. For a separate Python 3.12 interpreter when Ubuntu does not package it directly:

```bash
sudo apt update
sudo apt install python3.14 python3.14-venv
python3.14 -m venv .venv-image-bootstrap
.venv-image-bootstrap/bin/python -m pip install uv==0.9.8
.venv-image-bootstrap/bin/uv python install 3.12

BBS_IMAGE_PYTHON="$(.venv-image-bootstrap/bin/uv python find 3.12)" \
  ./SETUP_CREATURE_IMAGES.sh --download
```

If Python 3.12 is already installed, simply run:

```bash
./SETUP_CREATURE_IMAGES.sh --download
```

Setup creates `.venv-images`, installs the **CPU** Torch wheel before the other dependencies, explicitly downloads pretrained safetensors components, validates their presence and records `data/models/illustrations/image-model.json`. It does not train a model, change the app's environment or start generation. It never downloads unsafe pickle checkpoints as a fallback. Public model access does not require a paid key. Network access to Hugging Face and its current download/CDN redirects is needed once; access restrictions, gated repositories and model-license conditions remain authoritative. A failed download leaves no ready-model manifest.

The core app still starts without image libraries/models. Model/runtime installation is separate; app startup, creature browsing and speaker taps never download or load diffusion models.

```bash
# Confirm actual machine resources without loading a model:
./GENERATE_CREATURE_IMAGES.sh --check
# Start/restart the FastAPI app using its existing environment/port:
bash START_APP.sh
```

The app remains on port 8502. No lease-tracker process, port, environment or database is touched. Generation defaults to two CPU threads, lowers worker scheduling priority and checks available memory before loading a model. These are best-effort resource precautions; schedule heavy generation outside story time and monitor the actual laptop.

## Generate one, pilot, full library and resume

Start the app once to initialize the existing creature database, then run generation independently of the app/browser:

```bash
# First real test image (no manual approval step):
./GENERATE_CREATURE_IMAGES.sh --creature "Tyrannosaurus" --steps 20 --resolution 512 --threads 2
# Inspect quality and actual timing before this pilot:
./GENERATE_CREATURE_IMAGES.sh --pilot 10 --resume
# Only after the pilot is satisfactory, explicitly choose the full library:
./GENERATE_CREATURE_IMAGES.sh --all --resume
# Resume queued/interrupted work and retry failed jobs:
./GENERATE_CREATURE_IMAGES.sh --resume
# Regenerate an individual creature with another deterministic seed:
./GENERATE_CREATURE_IMAGES.sh --creature "Spinosaurus" --force --seed 123
```

No command automatically starts the full 164-creature run unless `--all` is explicitly supplied. The pilot starts with familiar dinosaurs including Tyrannosaurus, Triceratops, Stegosaurus and Velociraptor. `--creature` matches exactly one display/scientific name.

Other options: `--guidance 7.5`, `--steps 1..100`, `--resolution 256|384|512|640|768`, `--threads 1..32`, `--seed INTEGER`, `--output-dir PATH`, and `--db PATH`. Defaults are 512 square, 20 steps, guidance 7.5, CPU float32, batch size one, two threads. `BBS_IMAGE_VENV`, `BBS_IMAGE_MODEL_DIR`, `BBS_IMAGE_DIR` and `BBS_DB_PATH` select trusted server-side locations. Prefix/export these consistently for the app and CLI; `.env.example` is documentation and is not automatically sourced.

Choose a compatible alternate pretrained SD 1.x/2.x pipeline at setup time, with its actual license:

```bash
./SETUP_CREATURE_IMAGES.sh --download --model OWNER/COMPATIBLE-MODEL \
  --revision IMMUTABLE-COMMIT-OR-TAG --model-license 'ACTUAL MODEL LICENSE'
```

SDXL/FLUX and arbitrary remote Python are not supported by this CPU preset. Existing queued jobs pin their original model path/revision; the worker releases one model before loading another. Keep one model/preset for visual consistency. Seed reproducibility is best effort within the same weights/runtime/CPU settings, not a cross-platform bit-for-bit guarantee.

## Prompts and scientific limits

All images share the requested detailed natural-history encyclopedia style, realistic proportions/textures, full-body composition, lighting and natural colors. Prompts identify the stored scientific taxon and category context. Anatomical/contextual details come only from a verified profile or individually inspected fields. Unverified editorial descriptions are not promoted to evidence; no hardcoded movie anatomy or guessed species-specific horns/feathers are inserted to fill gaps.

Many inherited profiles still lack inspected anatomy. Their prompt metadata explicitly records `identity_only_no_verified_anatomical_details`. The model then relies on its learned visual prior, which can be wrong—especially for rare genera, fin counts, feather evidence or extinct-animal proportions. Prompt grounding does not make diffusion a scientific anatomy validator. **Every generated image is labeled AI-generated and not verified anatomical evidence.** Inspect the pilot's accuracy/style before requesting all 164; do not present generated artwork as a researched photograph or source citation.

Negative prompts exclude cartoons, anthropomorphism, fantasy/movie styling, text/labels/borders/watermarks, unrelated animals, cropped/severed bodies and blood/gore. The model's available safety checker remains enabled; flagged outputs and blank/constant pixels are rejected. These checks do not guarantee anatomy or eliminate every possible unwanted artifact. Prompts use one CLIP window. Immediately before inference, the worker uses the loaded model tokenizer and encoder limits (77 tokens for SD 1.5, including BOS/EOS) to fit both positive and negative prompts. It retains the scientific name, then inspected anatomical details, full-body composition, encyclopedia style, environment, and secondary lighting details in that order. Lower-priority clauses are shortened or dropped using actual tokenizer counts; an oversized scientific name fails clearly instead of changing identity. The final text and token counts appear in generation.log, console output, and successful image metadata. Existing version-1 queued recipes are rebuilt from their recorded identity/evidence on resume; image files and older metadata are preserved. New recipes use prompt version 2.

The pinned Diffusers 0.35.1 loader still accepts `torch_dtype`, rather than a loader-level `dtype`. The application now uses the supported `pipeline.to(device="cpu", dtype=torch.float32)` interface without passing the deprecated loader keyword. Internal third-party loading code may still emit its own Transformers deprecation warning; no warning filters or dependency monkey patches are used.

## Persistence, interruption and permanent cache

One process-level file lock per configured library prevents CLI/web workers from loading simultaneous diffusion models. SQLite stores queued/generating/ready/failed states, attempts, progress step, errors, measured duration, complete prompts/settings, seed, immutable model revision, timestamp and active/version manifests. New scientific facts are never written from pixels or prompts. Numeric IDs, relationships, game outcomes and pronunciation assets remain intact.

Successful output is decoded/size-checked, converted to quality-90 WebP and written atomically under `data/generated_images/<creature>-<key>.webp`. SHA-256 and file-bound manifests control serving. The corresponding creature's image reference and separate generated-image manifest update in a short SQLite transaction; scientific profile JSON is preserved. The worker backs up the database before processing. Existing licensed/source artwork remains recorded, but a valid generated version takes display precedence. Old immutable generated URLs remain servable after successful regeneration.

Resume skips valid completed recipes. Model revision, prompt/negative prompt, seed, resolution, steps and guidance affect identity; moving runtime paths or changing thread scheduling does not by itself regenerate intended pixels. `--force` creates a new version without overwriting the active file first. Failed/invalid generations preserve the previous working image. A hard-killed in-flight image is retried after restart; registered completed images are retained. Some uncommitted orphan files may remain after a power loss; they are not served as completed artwork.

Ctrl+C/SIGTERM requests a stop at a diffusion step boundary, saves the current job as queued and exits; the current step may take time to finish. Restart with `--resume`. Out-of-memory/backend resource failures halt rather than continually loading models; the browser supervisor does not restart-storm a halted/killed worker. Resolve resources and explicitly resume. A failure can be retried with `--resume`, or select/force a new seed. There is no paid/cloud fallback.

`generation.log` and `worker.log` contain progress/errors. Terminal output reports actual measured duration, completed/failed/queued work and an estimate based on successful timings; no example “18 minutes per image” is used as a prediction. First-load overhead and changing hardware/presets can make estimates rough. No real-generation ETA was measured in this cloud.

For overnight operation, a terminal multiplexer is sufficient:

```bash
sudo apt install tmux
tmux new -s creature-images
./GENERATE_CREATURE_IMAGES.sh --all --resume --threads 2
# Detach with Ctrl+B, then D. Later:
tmux attach -t creature-images
```

The CLI does not need FastAPI or a browser to remain open. After a reboot, restart the same resume command. Existing successes are permanent until you deliberately remove the files/database. Back up the SQLite database, image output, model manifest and retained source data together; no automatic cache clearing is performed.

## Settings and scientific importer separation

Settings → Local creature illustrations shows total/generated/remaining/failure counts, selected model, output location, active work, prompts and generation metadata. Regenerate queues a managed background subprocess rather than running inference in a request. A parent must unlock existing parent controls for this administrative action; there is no per-image approval. Queued duplicates are collapsed, and the same worker lock covers browser and CLI generation. Normal browsing, selection, profiles, bracket/champion imagery use the shared renderer and generated URLs. Missing/invalid generated assets use the prior artwork/placeholder.

The normal scientific importer no longer calls Commons image discovery. It retains PBDB/GBIF/museum fact and pronunciation research. Existing source-photo files/provenance are not deleted. Legacy source-art utilities remain available only by explicit legacy options (`--legacy-source-images` or supplied image references), with their existing licensing checks; generated artwork does not require that workflow. Obsolete image preview/approval UI is removed; the authenticated review endpoint now accepts only science/pronunciation scopes, preserving useful source review.

The earlier requested `IMPORT_RESPECT_ROBOTS=false` configuration is also included for optional scientific HTTP importing; it is not needed for cached diffusion inference. Default HTTP importing respects robots. It never overrides authentication, CAPTCHA, 401/403, proxy policy or image-license checks for legacy source art.

## Verification completed here

- Linux Python 3.12 CPU Torch/Diffusers/Transformers imports and a CPU tensor operation succeeded; `pip check` reports no broken requirements. CUDA availability was false.
- Core/application unit tests use mocked generation and temporary SQLite files; they cover prompt evidence selection, paths/settings, conversions, database updates, cache/resume, duplicate locks, failed/invalid regeneration recovery, immutable old URLs, serving and authenticated queueing.
- Mobile Chromium shows a real locally served WebP produced by the mock backend, AI labels in selection/profile, status/prompt metadata and protected regeneration. Existing complete tournament, prepared-audio and 164-entry browsing regressions remain passing.
- Hugging Face requests failed at the cloud proxy. **Phase 2 real model initialization/inference, phase 5 real ten-creature pilot and phase 6 visual/scientific quality validation remain unverified.** No real generated creature images are bundled or claimed. Phase 7 full-library execution is prepared, not started.

Run checks locally after installing dev/media dependencies:

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python tests/generated_images_smoke.py
PYTHONPATH=. .venv/bin/python tests/import_review_smoke.py
PYTHONPATH=. .venv/bin/python tests/selection_visibility_smoke.py --full-regression
```

### Optional automatic restart after reboot

For a user service, first complete model setup and the one-image test above. Stage only the desired batch without starting inference:

```bash
./GENERATE_CREATURE_IMAGES.sh --pilot 10 --enqueue-only
mkdir -p ~/.config/systemd/user
image_project="$(pwd -P)"
cat > ~/.config/systemd/user/bedtime-creature-images.service <<EOF_UNIT
[Unit]
Description=Local bedtime creature illustrations
[Service]
Type=simple
WorkingDirectory="$image_project"
ExecStart="$image_project/.venv-images/bin/python" "$image_project/scripts/generate_creature_images.py" --resume --db "$image_project/data/creatures.sqlite3"
Environment="BBS_IMAGE_MODEL_DIR=$image_project/data/models/illustrations"
Environment="BBS_IMAGE_DIR=$image_project/data/generated_images"
Nice=10
Restart=on-failure
RestartSec=60
RestartPreventExitStatus=2 3 130
TimeoutStopSec=300
[Install]
WantedBy=default.target
EOF_UNIT
systemctl --user daemon-reload
systemctl --user enable --now bedtime-creature-images.service
journalctl --user -u bedtime-creature-images.service -f
```

For startup without an interactive login, optionally enable user lingering with `sudo loginctl enable-linger "$USER"`. The service resumes only previously queued/failed work; it never stages the full library by itself. Unexpected process termination restarts it, while known model/resource/validation failures stop for inspection instead of spinning forever. To choose the full library later, explicitly stage `./GENERATE_CREATURE_IMAGES.sh --all --enqueue-only`, then `systemctl --user start bedtime-creature-images.service`. Adapt paths if using custom directories. This service is optional and is not installed/enabled by this repository or this cloud task.

If browser regeneration needs parent credentials configured for the first time, run `.venv/bin/python scripts/configure_parent.py` once on the server. This secures administrative CPU work; it does not add image-by-image approval.

Resume retry is conservative: it retries at most the latest failed version for a creature without a valid working image and does not replay historical failed versions over a newer success. To retry a failed regeneration while an older good image remains, explicitly select that creature with `--force`. Use `--all --resume` to rescan the whole library for missing/corrupt cache files as well as pending work.

Final automated validation in this change: **249 tests passed on Python 3.14 and Python 3.12 with optional media dependencies**. The core-only Python 3.14 run passes 222 and skips 27 optional media checks. The isolated image runtime also completed a mocked conversion/persistence worker smoke test without requiring the FastAPI environment; that test did not load pretrained diffusion weights.

Prompt-budget fix validation: **259 tests passed, 2 optional diffusion checks skipped** in each application environment (Python 3.12 and 3.14). All **12 prompt-budget tests passed** in the isolated image runtime, including real CLIP tokenization and a two-step CPU generation with a tiny randomly initialized pipeline. That runtime test uses temporary test weights and does not establish pretrained image quality. A separate check with OpenAI's official CLIP BPE vocabulary reduced a long Tyrannosaurus fixture from 143 to 77 positive tokens; its negative prompt used 52 tokens, both including special tokens. Actual pretrained Tyrannosaurus generation remains unverified: the CLI reports the missing model, and the Hugging Face download probe receives a proxy HTTP 403. Once the documented model installation succeeds, verify with `./GENERATE_CREATURE_IMAGES.sh --creature Tyrannosaurus --force`; use `--resume` for already queued work.
