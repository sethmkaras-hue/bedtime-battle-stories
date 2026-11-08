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
