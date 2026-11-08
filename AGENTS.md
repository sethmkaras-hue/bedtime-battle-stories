# Codex instructions

- Work in small, testable phases and preserve user data.
- Python 3.12+, FastAPI, SQLite, responsive HTML/CSS/JS.
- Run pytest before reporting completion.
- Keep API keys server-side, use environment variables, never commit secrets.
- No paid AI calls in tests or without explicit configuration.
- Prioritize simple bedtime-friendly mobile controls and audio-first storytelling.
- Do not introduce user accounts or permanent tournament history.
- Respect creature habitat compatibility and avoid fabricated scientific facts.
- Keep child-facing combat non-graphic; biting, kicking and tail strikes are permitted.
- Document incomplete features and distinguish placeholders from implemented behavior.
- Preserve compatibility with Ubuntu Linux and local-network hosting.
- Keep development sample data opt-in and separate from the production database; tests use temporary SQLite files.
- Require a shared compatible arena across all tournament participants; unknown habitats fail closed.
- Use unbiased sampling without replacement and preserve bracket selection order unless shuffling is requested.
- Session-only brackets may use browser sessionStorage; do not add server-side tournament history.
- Idle timeout must not interrupt active narration; provide explicit resume from quiet mode.
- For frontend changes, run the optional mobile Chromium regression when available and distinguish it from physical Safari/Android validation.
- Keep editorial catalog review status explicit. Do not describe unverified reference links, approximate pronunciation guides or game ratings as scientifically validated.
- Keep version-2 outcomes reproducible from entrants/settings/seed/completion; never trust submitted winners or persist tournament history.
- Test speech controls with deterministic stubs, and report audible/device validation separately.
- Keep the child flow simple; keep settings global and preserve active progress when opening them. Use bundled assets and speaker icons with accessible labels and 44px+ targets.
- TTS must be optional and CPU-only. Do not download models during app startup or import heavy engines into the request event loop. Keep one bounded generation worker and never choose a paid fallback automatically.
- Cache identity must include provider/model/voice/text/speed/overrides. Publish audio atomically, deduplicate concurrent jobs and require confirmation before clearing. Never commit model binaries or generated audio.
- Retain HTML5 audio controls and Safari user-gesture recovery. Do not regenerate on pause/resume/replay or reveal the winner before end/read-complete.
- Report real model generation, mocked adapter tests, browser transport tests, audible quality and physical-device checks separately. Benchmark measured CPU time/duration/RSS without claiming unmeasured improvements.

- Keep Python 3.14 installability tested. Do not bypass Requires-Python; use the maintained Sherpa Kokoro API and external IPA rather than lexicon-only inference that can omit words.
- Distinguish Piper package/native-extension support from voice-host network access. Missing Piper models must retain an explicit, tested Kokoro fallback and useful Settings diagnostics.

- Never promote a taxon, pronunciation or image license from a suggested URL or an AI respelling. Record inspected evidence/reviewer/date and retain explicit unverified states. Do not add entries merely to satisfy count targets.
- Preserve numeric IDs and stable import keys. Keep reviewed profiles, pronunciations and artwork protected; store fictional outcome ratings separately. Unknown measurements are null, never zero.
- Creature speaker taps must only play prepared local files. Do not call local/cloud/browser TTS during browsing; generate verified guidance explicitly with GENERATE_PRONUNCIATIONS.sh. Parent previews are separate.
- Real imagery requires matching taxon identity, complete reusable-license credit and validated local WebP assets. Use an explicit artwork-review placeholder when evidence is missing.
