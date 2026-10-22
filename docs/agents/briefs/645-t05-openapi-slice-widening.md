# Brief - 05 Widen the exported OpenAPI slice to the four new DTOs

**Ticket:** #650 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The exported OpenAPI contract slice widens to cover the two new doctor-case DTOs and the two consent DTOs, so both new backend contracts are pinned by the same schema-walking mechanism that exists because the doctor patients guard once drifted untested. The exported schema list and the checked-in slice artifact are updated together, and the slice-pinning test keeps asserting the checked-in copy matches the served schema - so a backend rename fails a contract test instead of failing a page.

## Acceptance criteria

- [ ] The exporter's schema list includes both new doctor-case DTOs and both consent DTOs alongside the existing nine.
- [ ] The checked-in slice artifact is regenerated from the served schema and committed with the list change, in the same commit.
- [ ] The slice-pinning test still asserts the checked-in copy matches the served schema, and still asserts every listed schema is published.
- [ ] The slice carries no backend prose, as the existing gate requires.
- [ ] No runtime behaviour changes: this ticket is the export list and its artifact only.

## Read-list (in order)

1. The `#645` spec's accessibility / consistency bullet about the exported contract slice widening to cover both new doctor-case DTOs _and_ the two consent DTOs - the "why" is one sentence. (~150 tokens)
2. The slice export script in full - it is ~190 lines. The schema-list tuple, the `--check` mode, the docstring's regeneration instructions, the keys stripped as noise, and the comment explaining that names must match the backend class names so a rename makes the export fail loudly. (~1.5K)
3. The slice-pinning backend test in full (~90 lines) - what it compares, the parametrised "every exported schema is published" case, and the no-prose assertion. (~700 tokens)
4. The checked-in slice artifact's top-level shape only - it is generated JSON; do not read it line by line. (~100 tokens)
5. The class names from #646 and #648's diffs. (~150 tokens)

## Do NOT read

- `docs/archive/`.
- The full served OpenAPI document - the script generates or fetches it for you.
- The frontend contract test. It consumes the artifact you regenerate; it is #652's read, not yours.
- Any module's business logic. The schema names are all you need.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - **currently green: 2867 passed.** The pin test is inside this suite, so a green run means the checked-in artifact currently matches the served schema.

Both #646 and #648 must have landed before you start: a schema name that does not exist yet makes the exporter fail loudly rather than produce a partial artifact.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - the pin test green and the parametrised case covering all thirteen names green.
- `npm run lint` - the JSON is checked for whitespace/formatting.

## Handoff notes

- **Two edits, one commit.** The list tuple and the artifact. The pin test compares parsed documents, so a list change without a regenerated artifact fails the suite, and an artifact change without a list change is dead weight in the diff. Land them together.
- **The names must match backend class names exactly.** The script raises listing every missing name if any entry does not resolve. That loud failure is the mechanism - do not work around it by renaming an entry to something that happens to exist.
- **Regeneration runs through the repo's Python shim**, not a bare `python`: `node scripts/py.cjs scripts/export_openapi_schemas.py`. The script's `--check` mode is the same comparison the pin test performs, so it is the fast pre-commit confirmation.
- **This is the guard that prevents the #624 class of bug.** A field added to either new backend DTO now automatically gains a removal case in the frontend contract test, because that test generates its cases by walking these schemas. Nothing about that is in scope here - but it is why widening the slice is part of the same change as the DTOs rather than a follow-up.
- **The frontend unit suite has one pre-existing failure** in `record/page.test.tsx` (an access-history empty state expecting "No access yet."). It fails on the untouched tree and is not yours.
