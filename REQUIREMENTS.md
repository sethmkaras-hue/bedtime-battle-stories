# Bedtime Battle Stories requirements

## Experience
A five-year-old chooses an eight-creature tournament and listens to one battle chapter at a time while in bed. Audio-first, dark mobile interface, one or two realistic still illustrations per battle. No user accounts or permanent tournament history.

## Library
Searchable, expandable collection of at least 100 dinosaurs, 40 shark species and prehistoric marine reptiles including Mosasaurus and Tylosaurus. Allow 200+ dinosaur entries. Store common/scientific names, category, habitat, length, weight, diet, offense, defense, locomotion, description, pronunciation and image reference. Unknown scientific facts remain unknown rather than invented.

## Tournament
Exactly eight distinct creatures, paired in selection order unless randomized. Optional random selection of all eight. Four quarterfinals, two semifinals, one final. Winners advance. Default separate dinosaur, shark and marine-creature categories. Sharks may face marine reptiles; no implausible land-dinosaur-versus-shark underwater matches. Explicit compatibility rules for semi-aquatic species.

## Realism
Realistic, Balanced (default), Anything Can Happen. Python engine determines outcomes, including configurable upset probabilities; AI writes the narrative without overriding the outcome.

## Stories
One battle per chapter, approximately 1, 2 (default), or 3 minutes. Reveal winner only at chapter end. Accurate animal capabilities and suspenseful but child-appropriate combat; biting, clawing, kicking and tail strikes permitted without graphic gore.

## Audio and images
AI narration with play/pause/replay/speed control. Prominent pronunciation button for every creature. One or two still images per chapter, anatomically credible and age-appropriate.

## Bedtime mode
Five-minute inactivity timeout stops playback. Avoid stopping an actively playing story solely because no one touches the screen; timeout policy should be refined when actual audio is implemented.

## Deployment
Ubuntu home server, Python 3.12+, FastAPI, SQLite, local-network access from iPhone/iPad, startup script. Server-side API secrets, no public exposure by default.

## Phases
1. App skeleton, screens, database, tests and documentation. No paid APIs.
2. Verified creature catalog, habitat rules, search and random selection.
3. Deterministic battle engine, bracket advancement and realism settings.
4. AI-generated stories, images and narration with cost controls.
5. Bedtime audio polish, reliability and deployment.

## Validated Phase 1 scope

Phase 1 includes opt-in isolated development data, search/filtering, unbiased random selection, strict tournament validation, shared-arena habitat compatibility, session-only bracket persistence, source-match references for future progression, browser pronunciation and a resumable quiet state. No outcomes, progression or generated narration are implemented. Active narration defers the five-minute idle timeout. Phase 2 owns scientifically reviewed species profiles and finer habitat rules. Development sample records omit unverified measurements.

## Version 2 local adventure scope

The next iteration adds an editorial catalog (164 entries; scientific source review pending), browser voice selection and guided pronunciation, seed-based fictional game outcomes, seven locally authored template chapters, winner advancement and champion display. Ratings are explicitly game rules, not scientifically validated probabilities. Session reconstruction sends entrant IDs, settings, seed and completion count; no server history. Approximate chapter durations depend on voice speed. Scientific catalog verification, trait-based simulation, verified audio and generated media remain outstanding. No paid services are configured or called.

## Kid-friendly UX and CPU audio iteration

The main flow is Home → Adventure → Eight Creatures → Visual Bracket → Story → Updated Bracket → Champion. Advanced controls live in persistent local Settings. Popular creatures precede expandable search/all browsing; locally bundled decorative SVGs are safe fallbacks. Displayed names and existing data remain intact. The inherited catalog has 110 dinosaur genera, not a verified 100-species catalog; scientific validation remains pending.

Kokoro is the primary CPU narrator, Piper the primary CPU name provider; the other local provider and then browser speech provide fallback. OpenAI is optional, server-configured, never an automatic fallback. One bounded background worker generates content-addressed WAVs with duplicate suppression, atomic publication and confirmed cache management. Models and generated audio are ignored by Git and retained across updates. Native HTML audio handles playback/time/seek; browser fallback does not claim accurate progress. Winner reveal occurs at narration end or explicit read-complete action. Quiet mode defers while active narration or current-battle generation is underway.

Real Kokoro CPU generation is measured. Piper's model download was blocked by cloud policy, so real Piper generation/performance remains an acceptance item for an environment with model access. Physical iPhone Safari and Ubuntu laptop validation remain outstanding; Chromium touch-viewport tests do not replace them.
