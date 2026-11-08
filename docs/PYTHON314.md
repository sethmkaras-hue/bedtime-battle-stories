# Python 3.14 CPU audio compatibility

## Findings and selected implementation

| Component | Investigation | Decision |
| --- | --- | --- |
| `kokoro-onnx` | Latest checked release 0.6.1 declares Python >=3.10,<3.14. | Replace the wrapper; do not force-install it or edit its metadata. |
| `kokoro` / `misaki` | Checked releases 0.9.4 also exclude 3.14 (require <3.13). | Not a supported substitute for this deployment. |
| ONNX Runtime | 1.31.1 publishes CPython 3.14 manylinux x86_64 wheels; real import succeeds. | Pin 1.31.1 for Piper's CPU sessions. |
| Sherpa-ONNX | 2.0.1 has native CPython 3.14 Linux wheels, bundled CPU runtime and maintained Kokoro support. | Run Kokoro through this supported API and its official v1.0 model bundle. |
| English G2P | Sherpa 2.x no longer uses its old `data_dir` espeak setting. Lexicon-only inference skipped the word “begins” in a real trial. | Use `phonemizer==3.6.0` + `espeakng-loader==0.2.4` to supply supported IPA `phoneme_codepoints`, sentence by sentence. |
| Piper | Maintained OHF `piper-tts==1.8.0` supplies a cp39-abi3 manylinux wheel; installed, imported, CLI and native espeak phonemizer all worked on CPython 3.14.9. | Keep the current maintained package and Python provider; a separate runtime is unnecessary on the tested platform. |
| Piper voice access | Official Hugging Face model/manifest requests received proxy-policy HTTP 403. | Report the network failure accurately; retain Kokoro for both narration and pronunciation until the voice is downloaded. |

Direct ONNX Runtime integration was considered: its Python 3.14 wheel is usable, but implementing and maintaining the raw Kokoro inference protocol, voice layout, tokenization and splitting would duplicate a maintained engine. Sherpa supplies that inference API. A small application-owned G2P adapter addresses its finite-lexicon limitation without vendoring or bypassing an unsupported Python package.

No CUDA, GPU extras, PyTorch or dedicated GPU is required. Optional audio dependencies remain in `requirements-audio.txt`; core dependencies remain in `requirements.txt`. Standard, GIL-enabled CPython 3.14 was tested. Free-threaded builds and non-x86_64 audio platforms were not validated.

## Why Piper was described as inaccessible

The earlier environment **installed the Piper package successfully**. It could not obtain `en_US-lessac-medium.onnx` and its JSON configuration because the cloud outbound allowlist excluded Hugging Face. Retesting the official model URL and the installer produced the same proxy-policy 403. A missing voice model does not demonstrate Python incompatibility or a moved package.

The maintained source is [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl). Its downloader still uses the `rhasspy/piper-voices` repository **on Hugging Face**. That voice-host namespace is distinct from the archived original GitHub application. The installer follows the maintained project's documented voice source and verifies the official manifest checksums.

Standalone operation was investigated. The maintained wheel installs a CLI (`python -m piper`) that also works on 3.14. A CLI in a separate supported Python environment could isolate a platform-specific extension problem, but it cannot fix blocked voice-model access. The maintained CLI documentation's old precompiled tarball links point to the original archived project's v1.2.0 releases; this change does not adopt them. The app retains its maintained in-process adapter instead of adding an unneeded second runtime/process protocol.

On a home server with normal outbound access:

```bash
.venv/bin/python scripts/setup_audio.py piper
.venv/bin/python scripts/benchmark_audio.py piper
```

The maintained CLI can also diagnose the voice independently after setup:

```bash
.venv/bin/python -m piper \
  -m data/models/piper/en_US-lessac-medium.onnx \
  -f /tmp/piper-name.wav -- 'tie ran oh sore us'
```

Do not add `--cuda`. Never disable TLS or checksum verification. If a proxy blocks downloads, allow `huggingface.co` and the exact official CDN redirect hosts reported by that environment. No network policy was replaced in this change.

## Kokoro model migration

The old Kokoro-ONNX model/NPZ voices are not interchangeable with the Sherpa bundle. Run:

```bash
.venv/bin/python scripts/setup_audio.py kokoro
```

This obtains the official `kokoro-multi-lang-v1_0.tar.bz2` from the maintained Sherpa project's GitHub `tts-models` release, checks the pinned SHA-256, safely extracts only the required model/voices/tokens and license/readme, and atomically publishes `data/models/kokoro-sherpa/`. It keeps old `data/models/kokoro/` files untouched. The compressed archive is about 334 MiB; installed selected files are about 338 MiB. Allow roughly 700 MiB transient free space for the archive and staged installation, plus dependencies and any retained old models. Subsequent setup recognizes the installed bundle without another download.

Voice IDs remain `af_heart`, `af_sarah`, `bf_emma`, `am_michael`, and `bm_george`, mapped to the pinned bundle's documented speaker IDs. Existing voice preferences survive. English US/UK phonemization follows the voice selection. Long sentences are split at word boundaries to fit the model's style table; words outside a dictionary are phonemized rather than skipped. Guides remain approximate, not verified scientific pronunciation.

Cache identity now includes Sherpa version, model/voice/token fingerprints, phonemizer/loader versions and G2P format identity, alongside text, voice, speed and pronunciation overrides. Old cached files are retained, but are not confused with new engine outputs. Clear cache only through the existing confirmed action if you want to reclaim old audio storage.

## Ubuntu 26.04 installation

Back up `data/` and stop the app first. If `.venv` uses a different minor version, preserve it under an unused backup name, then create a new environment. Do not reuse a broken interpreter path or override package Python restrictions.

```bash
sudo apt update
sudo apt install python3.14 python3.14-venv
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-audio.txt
.venv/bin/python scripts/setup_audio.py kokoro
.venv/bin/python scripts/setup_audio.py piper
BBS_PYTHON=python3.14 bash START_APP.sh
```

If only Piper setup fails, Kokoro remains usable for names and stories. If all optional audio is absent, core startup still succeeds and Settings explicitly reports missing dependencies/models. The application does not install optional audio or download models silently during startup.

`BBS_PYTHON` selects the runtime; `BBS_VENV` selects the environment directory (default `.venv`). The launcher rejects a broken environment or a mismatched Python minor/ABI before installing anything. It does not move/delete an existing environment automatically. Port 8502, SQLite data, other home-server applications and the bounded audio queue remain unchanged.

## Executed validation

Validation host: Debian 13 Linux x86_64. Test interpreter: **CPython 3.14.9**, installed in an isolated environment. This establishes tested Python/runtime behavior, not native Ubuntu 26.04 hardware coverage.

- Exact `requirements-audio.txt` installation succeeded; `pip check` passed.
- **59 pytest tests passed** with Python 3.14 audio dependencies installed.
- **59 tests passed** in a second clean Python 3.14 environment with only core requirements; core startup without models/engines and explicit diagnostic statuses passed.
- **59 tests passed** on the existing Python 3.12 environment.
- `START_APP.sh` launched the real 3.14 server using explicit interpreter/environment selection.
- Real CPU Kokoro WAVs were generated using all five configured voices. Repeated requests were disk-cache hits and voice changes produced distinct cache keys.
- Piper's maintained native extension, CLI `--help`, and real espeak phonemization of “Tyrannosaurus” succeeded on 3.14. Its full voice inference could not run because model download was blocked.
- A pronunciation request selecting Piper fell back to Kokoro on the server, generated a real WAV, was cached, and played through HTML audio in Chromium. Settings showed CPython 3.14.9, Kokoro ready and the exact missing Piper model files. No page errors were observed.
- No paid API calls, compatibility overrides, GPU dependencies or generated model/audio commits were used.

Measured CPU generation in the real HTTP service, two threads, same short sentence (“A gentle story begins beneath the moon.”):

| Voice | Generation seconds | Audio seconds | Real-time factor |
| --- | ---: | ---: | ---: |
| Heart (first, includes model load) | 2.759 | 2.334 | 1.182 |
| Sarah | 1.682 | 2.469 | 0.681 |
| Emma | 1.576 | 2.447 | 0.644 |
| Michael | 1.665 | 2.572 | 0.647 |
| George | 1.779 | 2.704 | 0.658 |

Kokoro fallback for the guided name took 1.076 s for 1.539 s audio. These short samples include different cold/warm conditions; they are not an audio-quality ranking or a benchmark of the user's laptop. Physical Safari, audible pronunciation accuracy, long-session reliability on Ubuntu hardware and real Piper model inference remain unverified. Use the existing local benchmark script on the home laptop; more CPU threads are not automatically faster.
