# Local audio operation

## CPU setup

Use Python 3.12+ on Ubuntu 24.04 or Python 3.14 on Ubuntu 26.04. The optional file selects `sherpa-onnx==2.0.1` for Kokoro, `onnxruntime==1.31.1` for Piper, maintained `piper-tts==1.8.0`, `phonemizer==3.6.0`, `espeakng-loader==0.2.4`, soundfile and the official OpenAI SDK. The old `kokoro-onnx==0.6.1` wrapper excludes Python 3.14 and is no longer used. See [Python 3.14 investigation and current validation](PYTHON314.md). Normal app dependencies remain small. Do not install `[gpu]`, training extras, CUDA or NVIDIA drivers.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-audio.txt
.venv/bin/python scripts/setup_audio.py all
```

Or download engines separately:

```bash
.venv/bin/python scripts/setup_audio.py kokoro
.venv/bin/python scripts/setup_audio.py piper
```

Models are retained at:

```text
data/models/kokoro-sherpa/model.onnx
data/models/kokoro-sherpa/voices.bin
data/models/kokoro-sherpa/tokens.txt
data/models/piper/en_US-lessac-medium.onnx
data/models/piper/en_US-lessac-medium.onnx.json
```

The downloader checks pinned SHA-256 hashes for the selected official Sherpa Kokoro archive. Piper files are checked against sizes and MD5 digests in the official HTTPS voice manifest. Downloads go to `.part` files and are renamed only after verification; failed partial downloads are removed. Existing files with unexpected checksums are not overwritten. Keep TLS verification enabled. Model setup is explicit and never happens during application startup.

Sources and licenses:

- [Sherpa-ONNX runtime and examples](https://github.com/k2-fsa/sherpa-onnx); [selected Kokoro v1.0 model archive](https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_0.tar.bz2). Review the bundled model license, runtime license and espeak/phonemizer licenses before redistribution.
- [Maintained OHF Piper](https://github.com/OHF-Voice/piper1-gpl) and [Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md). Piper runtime: GPL-3.0. [Voice model repository](https://huggingface.co/rhasspy/piper-voices) contains voice-specific model cards/licenses; do not assume all voices share a license.
- [Official OpenAI Python SDK](https://github.com/openai/openai-python).

Allow roughly 338 MiB for Kokoro files, roughly 60–70 MiB for the selected Piper voice, and additional Python dependencies. The development virtual environment with audio and browser-test Python packages measured about 440 MiB here; system/browser libraries are additional. Audio cache storage grows with usage and can be cleared from Settings. Reserve 1–2 GB of disk and around 2 GB free RAM for planning, then benchmark on the actual server.

## Providers and voices

Kokoro is the default narrator. Heart (`af_heart`) is the editorial default; Sarah, Emma, Michael and George are available alternatives. This is a selection/pacing control, not arbitrary voice instructions. Piper Lessac is the default name voice. The same pronunciation override mapping is used for local names and narration without changing displayed scientific names. Guides remain approximate and need listening on real devices.

Each provider exposes availability, voices, identity and generation through a shared interface. Missing local packages/models trigger the other installed local provider, then browser speech. OpenAI is never an automatic fallback. Browser speech stays entirely frontend-side; it has no generated file or reliable time/progress API. The UI identifies the fallback and supports reading when the device has no voice.

Kokoro explicitly selects Sherpa’s `cpu` provider with two threads (configurable 1–4). Piper sessions select `CPUExecutionProvider`, two intra-op threads (configurable 1–4), one inter-op thread, and disable the CPU memory arena. Kokoro supplies external English IPA to Sherpa; it does not rely on a finite word lexicon or the deprecated espeak data-dir setting. Models are loaded lazily and reused by the worker. Restart after model replacement. No model files are committed.

## Cache and worker

WAV files live in `data/audio_cache/narration/` and `data/audio_cache/pronunciation/`. SHA-256 identity covers original text, effective provider, voice, runtime/model-file fingerprints, generation speed, overrides and cache-format version. HTML playback speed does not regenerate an unchanged waveform. Requests for the same identity reuse a file or the same in-flight job.

One bounded worker executes CPU-heavy jobs outside the FastAPI event loop; at most eight jobs wait. Excess requests get a retryable 429. Results metadata is bounded to 128 recent jobs; older ready files can still be found on disk. File locks also prevent duplicate writes across processes, though a **single Uvicorn worker** is the supported low-memory deployment. Each additional process would load its own models.

The worker validates WAV duration, writes temporary output/metrics, then atomically renames completed files. Failures remove partial files and can be retried. Models, SQLite and unrelated files are outside cache clearing. Cache metadata contains timing/provider information, not story text. Empty lock files may remain so lock identities stay stable. A process killed without cleanup can leave an ignored `.part`; confirmed cache clearing removes such leftovers when no local job is active.

Settings shows file count and cache bytes. Clear Audio Cache requires a visible confirmation and a confirmation header; deletion is rejected while this process has pending work. Do not clear the cache concurrently from a second app process; use the supported single-worker setup. Audio URLs accept only fixed kinds and 64-character hexadecimal keys, never arbitrary filesystem paths. No tournament history is persisted.

## Playback and Safari

Generated audio uses HTML5 audio controls, including seeking, elapsed/total time and playback speed. Pause/resume/replay use the same source without generation. Narration and pronunciation stop one another. Leaving the player stops playback; returning retrieves the cached source. Automatic narration is off by default. If Safari rejects an asynchronous `play()`, a prominent Play button remains available for a new user gesture.

The native HTML media controls remain available alongside the large custom buttons. Device speech has sentence segmentation, pause/resume and replay but no fabricated time bar. Active audio and active-battle generation defer the quiet timeout. Paused/idle playback can enter quiet mode and resume manually without losing bracket progress.

## Optional paid OpenAI audio

Not needed for local operation. Install the optional dependencies, configure credentials only on the server, explicitly enable it, and select OpenAI in Settings:

```bash
export BBS_ENABLE_OPENAI=1
# Set OPENAI_API_KEY securely in the server environment.
export BBS_OPENAI_MODEL=gpt-4o-mini-tts
bash START_APP.sh
```

`.env.example` is documentation, not a secret store. The application does not auto-load it. The official SDK uses a configurable model, chosen voice, WAV output, a timeout and no automatic paid retries. Changing models changes cache identity. Provider status reports only configured/enabled state, never credential values. Previews and generation can incur charges when deliberately enabled; all automated tests mock the SDK and make no paid calls.

## Benchmarks

Run locally after model setup:

```bash
.venv/bin/python scripts/benchmark_audio.py kokoro
.venv/bin/python scripts/benchmark_audio.py kokoro --voice af_sarah
.venv/bin/python scripts/benchmark_audio.py piper
```

The script prints generation seconds, audio seconds, real-time factor (generation/audio), cache status and peak process RSS. Settings offers the same fixed local sample benchmark. An already cached benchmark is labeled cached; its recorded synthesis timing is historical, not a new measurement. For a fresh measurement, clear the cache explicitly first, and account for cold model loading. Do not benchmark a paid provider; the benchmark endpoint accepts only local engines.

## Historical validation before the Python 3.14 migration

The measurements below used the old wrapper and are retained as historical evidence only. Current engine/version measurements and validation are in [PYTHON314.md](PYTHON314.md).

These are measurements from this Debian 13 cloud environment, Python 3.12.14, CPUExecutionProvider, two ONNX threads. They are not laptop or physical iPhone measurements and do not establish perceived voice quality.

| Voice / sample | Generation | Audio | Real-time factor |
| --- | ---: | ---: | ---: |
| Kokoro Heart, first generation including load | 5.944 s | 7.763 s | 0.766 |
| Kokoro Sarah, same process with model loaded | 4.430 s | 7.487 s | 0.592 |

Peak process RSS after both samples: **793.8 MiB**. Samples have the same 22-word text. Differences include cold/warm startup, so they are not a controlled ranking of voices. No improvement over Version 2 has been asserted from these timings.

A separate real HTTP test generated an 8.039 s Heart WAV in 5.861 s, returned the queued submission in 0.277 s, and served a creature API request during generation in 0.058 s. The identical repeated audio request was a disk-cache hit. Real WAV bytes and metadata were checked; audible output was not judged. A separate real Chromium story-player check prepared a short Kokoro chapter in 44.123 s, loaded 68.545 s of audio, and advanced the winner on the real HTML media `ended` event (the test sought near the end rather than listening through it).

The official Piper Hugging Face model URL returned an outbound-policy 403 in this cloud environment. Piper package compatibility and adapter behavior were verified with mocks, but **real Piper generation and benchmarks are unverified**. To validate in cloud, allow `huggingface.co` and the exact CDN hosts reported by its redirects (commonly `cdn-lfs.huggingface.co` / `cas-bridge.xethub.hf.co`) in environment network settings, then rerun setup and the benchmark. No network policy was broadened by this change. On an unrestricted home server, run the documented setup command normally.

## Troubleshooting

- **Local provider unavailable:** install `requirements-audio.txt`, run model setup, confirm file names in the configured model directory, and restart. The app remains usable with the other local engine or device speech.
- **403 downloading models:** inspect the blocked hostname; allow that official destination through the network policy. Never disable TLS or checksums.
- **Audio takes time:** first generation includes model loading. Repeated playback should be a cache hit. Keep one app worker; try one or two threads on the actual laptop and measure rather than assuming more threads are faster.
- **No sound on iPhone:** tap Play directly, check device volume/output, and try the native media controls. Browser voice fallback needs an installed device voice. Physical Safari verification remains outstanding.
- **Wrong name pronunciation:** review the creature’s pronunciation field, select a clearer voice and preview. Overrides affect speech/cache identity, not the displayed name. Do not claim guides are verified phonetics.
- **Cache busy:** let generation finish before confirming clear. A failed request does not require deleting models or the SQLite database.
- **OpenAI missing:** local audio needs no key. Premium audio requires both explicit enablement and a server-side key; the API does not reveal it.
