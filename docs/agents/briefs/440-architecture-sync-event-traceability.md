# Brief - 440 Docs: architecture sync/event/traceability matrices

**Ticket:** #440 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

Register the new PHASE-8.1 seams in `internal-modules.md`: §4.1 sync matrix (doctor pick / assigned-partner scoping, doctor review-queue read, doctor full pre-summary read, working prescription read, consultation fee on directory and provider-profile projections, one-action review→final path), §4.2 event registry, and §5 traceability rows.

AC:

- [ ] The sync matrix registers the new PHASE-8.1 seams with module owners
- [ ] The event registry gains a row for every new event the seams publish (or explicitly none, if no new events exist)
- [ ] Module traceability rows reflect the PHASE-8.1 additions
- [ ] No invented event names or module links - every edge is registered here, not in code

## Read-list (in order)

1. `internal-modules.md` §4.1 sync matrix and §4.2 event registry - the edge-registration tables to extend (~1800 tokens)
2. `internal-modules.md` §5 traceability (feature↔module↔storage) - rows to extend (~700 tokens)
3. `internal-modules.md` MOD-002 (partner/directory), MOD-004 (consent), MOD-005 (intake/pre-summary), MOD-006 (care) specs - module-owner context for each new seam (~1600 tokens)
4. Issue #438 "Implementation Decisions" backend deltas 1-6 and the glossary terms they name (assigned-partner scoping, care case, verification declaration) (~600 tokens)

## Do NOT read

- `docs/archive/`, roadmap, PRD, blueprint, any application code or tests.

## Baseline verify (must pass before the first edit)

- `npm run lint` on the untouched tree (docs-only change).

## Done-verify (acceptance criteria → commands)

- Diff review of §4.1/§4.2/§5; cross-check each named seam against issue #438's six backend deltas.
- For every new seam there is a matrix row naming its owning module; no seam appears only in code.
- `npm run lint` passes.

## Handoff notes

- Sibling tickets: #439 (roadmap) and #441 (blueprint/PRD) - keep the same PHASE-8.1 phrasing; do not touch those files.
- Do not invent events: if the deltas publish nothing new, state that explicitly rather than adding rows.
