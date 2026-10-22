# Brief - 13 One consented read behind both doctor history surfaces

**Ticket:** #658 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A doctor can no longer see two different histories for one patient. The consented-history component accepts an already-loaded timeline as an optional prop and falls back to its own consented read when given nothing. The case workspace passes the console detail projection's consultation history, so the two doctor surfaces render from **one** read and structurally cannot disagree.

Two things must not move, and both are decisions rather than omissions:

- the fallback read keeps its hardcoded `consultations` scope - widening it changes what a doctor may see, which is a consent decision, not a rendering one;
- a null prop renders the calm "not shared" note - never a crash, never an error state, preserving fail-closed denial behaviour.

The two surfaces come to the same information density, so moving between them teaches nothing new, and the loading, empty, and error states - including the retry affordance and its trace id - are preserved.

## Acceptance criteria

- [ ] The consented-history component accepts an already-loaded timeline as an optional prop.
- [ ] Given nothing, it falls back to its own consented read exactly as today, on the unchanged `consultations` scope.
- [ ] Given a null prop, it renders the calm "not shared" note - no crash, no error state, fail-closed preserved.
- [ ] The case workspace History tab passes the console detail projection's consultation history.
- [ ] The two surfaces show the same information density.
- [ ] The existing loading, empty, and error states are preserved, including the retry affordance and its trace id.
- [ ] Tests cover: prop supplied renders the prop's entries; prop null renders the not-shared note; no prop falls back to the consented read with the unchanged scope; and the error / retry path still recovers.

## Read-list (in order)

1. The `#645` spec's history user stories (53–60) and the "One history, not two" paragraph - the single-read intent, the unchanged scope, and the "not shared" sentence. (~600 tokens)
2. The consented-history component **in full** - it is small. Its props, its internal status machine, its entry-badge labelling, and its denial rendering. This is where the optional prop and the three-state prop contract belong. (~800 tokens)
3. The case workspace page - **the History tab region only**: how it renders the component, what the console detail projection exposes as consultation history, and its test id. (~700 tokens)
4. The case workspace page test suite - the History tab describe and its fixtures. (~1K)
5. The doctor patient profile page - **the consultation-history block only**, for the density and the entry formatting the workspace must match. (~800 tokens)
6. The consent API client's consented-read signature. Signature only - the scope constant is what you must confirm, not the implementation. (~300 tokens)
7. The dictionary file's case-workspace and doctor-patients namespaces in **both** locales - the not-shared note and the entry-badge labels. (~600 tokens)

## Do NOT read

- `docs/archive/`.
- The other pages that mount the consented-history component. Their existing suites are the behavioural coverage for the fallback path; you do not need to change them, and changing them would be scope creep.
- The consent API client beyond that one signature, and the consent backend.
- The record timeline page - that is the patient's view, a different surface.
- The doctor patients list and the cases list.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**

No blockers. This ticket can start immediately.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - the four new cases green; the suites of every other page that mounts the component still green (they prove the fallback path); the one pre-existing failure is still the only failure.
- `npm run typecheck` - `tsc --noEmit` is also the bilingual gate.
- `npm run lint`

## Handoff notes

- **Three distinct prop states, not two.** Undefined → fetch the consented read. An array → render it. Explicit `null` → render the "not shared" note and **do not fetch**. Collapsing null into undefined would make a denied history start firing a read that answers denied anyway, which is both a wasted round trip and a confusing empty-then-error flicker.
- **Do not widen the scope.** The hardcoded `consultations` scope is a consent boundary. "The doctor should see labs too" is a product change that goes through the consent model, not a prop refactor. Leave the constant exactly as it is and let the test assert it.
- **"Not shared" is a first-class state, not an error.** It has its own calm rendering already. The trap is routing `null` through the error branch, which would put a trace id and a retry button on a screen where retrying cannot help.
- **One read means the badge labelling cannot drift.** Both surfaces use the same entry-badge labelling inside the component, which is why one read is enough to make them agree. Do not re-badge entries at the call site.
- **Density is a real acceptance criterion.** If the workspace history shows fewer fields per entry than the profile page does, moving between them still teaches something new. Compare them side by side and match.
- **The trace id on retry is preserved.** It is how a support ticket gets tied to a log line. Keep it on the refused-fetch error path.
