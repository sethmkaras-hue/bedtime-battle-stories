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
