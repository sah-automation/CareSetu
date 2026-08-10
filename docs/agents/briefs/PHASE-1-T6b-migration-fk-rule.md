# Brief - PHASE-1 T6b Migration-check cross-schema FK rule

**Ticket:** #27 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

Extend the `migration-check` gate to reject cross-schema foreign keys (a migration may not create an FK that references a table in another schema), preserving the existing single-head invariant. A fixture migration with a cross-schema FK must fail the gate; the real migration tree passes.

Acceptance criteria:

- [ ] A fixture migration with a cross-schema FK fails `npm run migration-check`
- [ ] The real migration tree passes `npm run migration-check` (single head + no cross-schema FK)
- [ ] Existing single-head behavior is preserved

## Read-list (in order)

1. `docs/adr/0003-db-per-module-isolation.md` - the no-cross-schema-FK rule (~0.5K).
2. `docs/standards/coding-standards.md` §5 - migration rules (~0.5K).
3. The existing `migration-check` script - the single-head gate to extend (~0.5K).
4. Issue #16 Implementation Decisions - isolation enforcement FK rule (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run migration-check`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria → commands)

- `npm run migration-check` passes on the real tree
- Fixture cross-schema-FK migration fails the gate (unit/script test)

## Handoff notes

- The single-head invariant from #17's baseline must be preserved - this adds FK scanning on top, not a replacement.
- Only the bootstrap revision from #18 exists in the real tree today, so the real-tree pass covers that.
- The FK rule is part of the module isolation rule (ADR-0003).
- Baselines verified green on 2026-08-10.
