# Import validation, approval errors and automatic images

**Current artwork workflow:** [local CPU image generation](LOCAL_IMAGES.md) replaces normal internet image discovery and image approval. Scientific/pronunciation review and existing source records remain. Earlier image-import sections below document the retained legacy utilities.

Validated images now publish automatically. Uncertain matches, incomplete licenses, unresolved scientific updates and pronunciation guidance retain authenticated parent review. This follows the chosen workflow: no removal of the review controls needed for uncertain content. Already-applied image actions disappear; partial decisions no longer discard remaining work.

## Reproduced failures and fixes

The report did not include the home server's exact request bodies or logs. These are reproducible code-level causes, not a claim that every observed home-server 422 had the same cause:

| Boundary | Before | Now |
| --- | --- | --- |
| Sourced `habitat` approval | The approval builder accepted it but `CreatureRecord.reviewed_fields` rejected it, returning 422 | One shared scientific/reviewed-field definition accepts the validated field and its review stamp |
| Image/science action with unrelated pronunciation | Frontend submitted every pronunciation input regardless of selected scope; an overlong guide could make a valid image/science action return request-schema 422 | Only selected pronunciation approvals submit edited guidance; backend type/length checks remain enforced |
| Missing proposal | Generic 422 “Proposal is not pending” | 404 `proposal_not_found` |
| Repeated/stale decision | Generic 422 | 409 `proposal_conflict`; refresh the queue |
| Partial approval | Closed the whole proposal, dropping other pending work | Records completed scopes; remaining guidance/images/science stay pending |
| License identifier/declaration mismatch | Source filtering rejected it, but the canonical image model could accept a forged/malformed staged record | Shared model and source acquisition use the same license/declaration check; mismatch remains rejected |
| Reviewed measurement refresh | Protected range could lose its original citation or mutate the incoming proposal's source-ID list | Preserve reviewed citations, deep-copy normalization, validate the merged result |
| Installed image in an open selection | Server data changed but the frontend still held old creature objects | Refresh cached creature objects after a successful action, preserving selected IDs and tournament state |

No request or content validation was removed to hide 422s. Missing required confirmation, wrong types, unknown scopes, incomplete evidence, bad measurement ranges, mismatched taxa, checksum changes and invalid media still fail. Whitespace-only pronunciation guidance cannot become verified.

## Endpoints and response types

- `POST /api/admin/proposals/{pid}/decision` is the content-write endpoint. Its body has `decision: "approve" | "reject"`, `confirm: true`, `scopes` chosen from science/image/pronunciation, an integer `image_index` when applicable, and optional bounded pronunciation edits. Extra fields are rejected. Positive integer proposal IDs are required.
- `POST /api/admin/login` can return request-schema 422 for a missing/invalid password field. Authentication failures remain 401; attempt throttling is 429. Passwords and request bodies are not logged.
- `GET /api/admin/proposals/{pid}/image/{index}` can return request-schema 422 for malformed path types, or 404 for an unavailable staged preview. It remains authenticated and restricted to known staged files.
- The proposal/session listing endpoints do not accept import bodies or arbitrary filesystem paths.

Request-schema errors retain 422 with code `invalid_request`. Import-schema/licensing failures retain 422 with code `invalid_content`. Missing proposals are 404, stale decisions/identity conflicts 409, and busy/unavailable canonical database writes 503. Authentication, same-origin and CSRF checks also apply when request parsing fails.

Content errors return a structured `detail` object with `code`, `message`, `creature`, `stable_key`, `proposal_id`, `operation` and `issues` containing field paths/messages/types. The UI displays these instead of “Review action was not accepted.” Logs identify the same operation/creature/proposal and validation problem. They exclude passwords, cookies, CSRF values, request bodies and Pydantic input dumps. For a failed request, retain the HTTP status, proposal ID and the field-level detail alongside the server log.

## Shared persistence and automatic publication

`app/importer/persistence.py` is the common boundary for parent approvals, automatic scientific-field updates and automatic image installation. It validates normalized content, full profile and WebP files; backs up the database; checks that the record has not changed during preparation; and writes through `library.import_records` in a transaction. The manual route no longer has a separate direct-SQL profile update. Reviewed fields, sources, stable IDs, game rules and existing approved assets remain protected. Explicit scoped parent decisions can replace reviewed content; ordinary automatic refreshes cannot.

Automatic image updates are separately constrained to image/import-stage changes. They can fill missing artwork on a fully reviewed scientific profile without changing its scientific claims, pronunciation or verification. They do not replace existing approved artwork. Interrupted image commits reconcile queue bookkeeping on restart without duplicating or regenerating installed images. Invalid resumed scientific updates are reported with context rather than aborting the entire batch.

An automatic image requires a supported parsed candidate, exact scientific identity, suitable described image medium, clear identity evidence, complete creator/attribution/source/license metadata, a matching reusable-license declaration, a checksum-verified original and valid optimized WebP files. Canonical validation is repeated before persistence. No `supported:true` flag alone bypasses these checks. Valid images receive `approval_method: "automated"` and reviewer identifier `automated-import:v1`; manual images receive `approval_method: "manual"` and `parent-review`. The date records the relevant check. The automated label is not a claim of human scientific certification; the whole profile remains unverified unless its scientific evidence independently meets the existing requirements.

Only image publication becomes automatic. No invented pronunciation is approved and no paid/cloud audio is invoked by it. Existing pronunciation signatures/manifests remain unchanged for image-only updates. Child speaker taps still play prepared files only.

## Ubuntu upgrade and use

Stop the app, preserve your existing data/assets, update to this change, then:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-media.txt
bash START_APP.sh
```

In another terminal, from the repository:

```bash
# Review what would change; no canonical or preview writes:
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --dry-run --report /tmp/import-preview.json
# Apply validated facts and install evidence-complete images:
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --refresh --skip-audio --report data/import-report.json
# Stage everything without automatic publication when desired:
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --propose-only --skip-audio
# Existing offline source route also uses the shared validated publisher:
./IMPORT_CREATURE_LIBRARY.sh --pilot 10 --offline \
  --image-references /path/to/images.json --skip-audio
```

Importer version 5 revisits older checkpoints once. Re-running an old failed approval uses the fixed schemas; stale/already-decided IDs should be refreshed rather than resubmitted. `--propose-only` stages both science and images without publishing. `--dry-run` is still read-only. JSON reports include `images_published`, scientific updates, pending review and problems. Exit status 2 still means unresolved coverage/review/source issues; a valid image may have installed even while other records remain incomplete. Inspect per-creature issues and Settings → Image credits & library care.

Parent Review keeps unresolved scopes available. Rejecting *remaining* updates does not undo artwork or facts that were already installed. An image whose evidence is insufficient must be researched and reimported with correct source metadata, not approved by suppressing an error. Approved guidance can subsequently enter `GENERATE_PRONUNCIATIONS.sh` as before.

## Evidence and limits

- **195 tests pass on Python 3.14 and Python 3.12 with media dependencies.** Core-only Python 3.14 passes 178 with 17 optional media tests skipped.
- Regression cases reproduce the previous habitat 422, identifier/status misclassification and shared-license gap, and cover request fields/types, partial scopes, protected citations, measurement validation, database rollback/diagnostics, verified-profile preservation and interrupted automatic publication.
- Mobile Chromium's actual CLI-installation check creates a disposable database and synthetic source originals/credits, installs real WebP derivatives, obtains HTTP `image/webp` responses, checks RIFF/WEBP bytes, and confirms decoded selection images. Manual approval updates an already-open selection without a reload and preserves selected IDs; an automatic import is visible on a fresh child selection without parent interaction. Temporary test derivatives are removed afterward.
- Parent-review mobile checks confirm that an overlong unrelated guide is not submitted with a science approval, field errors remain actionable and partial decisions retain pending work. Full-catalog, prepared-playback and seven-battle regressions also pass.

These are local fixture/transport tests. No new real taxon, licensed species image, authoritative pronunciation or audible-quality improvement was researched or verified in this cloud session. Physical Safari/Android devices were not tested. The change preserves the evidence requirements for real imports on the home server.
