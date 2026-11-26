# Brief - T11 Patient journey e2e

**Ticket:** #220 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The whole phase proven as one patient journey in the browser against the live backend: open My Record, filter the timeline, walk the grant sheet to a visible receipt, revoke with the inline confirm, then observe the revoked receipts and the egress slice - bilingual toggle spot-checks along the way. Timeline entries are seeded by emitting synthetic outbox rows through the real dispatcher in test setup (no producer exists yet by design). This is the phase's end-to-end gate riding the auth-loop prior art.

Acceptance criteria: see #220 body verbatim.

## Read-list (in order)

1. Roadmap PHASE-3 testing decisions - the e2e row defining this journey (~0.7K)
2. Auth-loop e2e spec + playwright config - boot pattern (live backend + mock SMS), selectors/page-object conventions, CI wiring (~2K)
3. The four screens as T7/T8/T9/T10 landed them - routes, data-testid hooks, user-visible flows (~2K)
4. Round-trip harness seeding pattern from T6's tests - synthetic outbox emission for timeline entries (~1K)
5. Integration conftest - how the suite reaches native Postgres / skips cleanly (~0.7K)
6. `docs/standards/error-handling-observability.md` - no-PHI logging rules for test output (~0.5K)

## Do NOT read

- Producer/diagnostics code (none exists yet); AI flows; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; backend units 654 passed; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:e2e` (auth-loop green).

## Done-verify (acceptance criteria → commands)

- `npm run test:e2e` (journey spec green alongside auth-loop)

## Handoff notes

- Seed via synthetic outbox rows fanned out through the real dispatcher - do NOT insert record_entries directly; that would bypass the idempotency contract the phase proves.
- Bilingual spot-checks are assertions on rendered strings after locale toggle, not screenshot diffs.
- Journey asserts the stop-forward copy and egress-slice visibility post-revocation - those are story-level acceptance, not cosmetic.
