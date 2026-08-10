# Brief - PHASE-1 T6a Module boundary checker

**Ticket:** #26 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

`check-module-boundaries.py`: walks the import graph and rejects module-to-module imports of `domain`/`schema`/`adapters`; allows cross-module imports only via `facade.py`; whitelists the transport carve-out (dispatcher); asserts namespace prefixes. Unit tests feed fixture module trees (legal facade-only import, forbidden domain import). Wired into pre-commit + CI over the real 11-module tree.

Acceptance criteria:

- [ ] Forbidden cross-module imports are rejected (fixture tests)
- [ ] Legal facade-only imports pass
- [ ] Transport carve-out (dispatcher) is whitelisted
- [ ] Runs in pre-commit and CI; the real 11-module tree passes

## Read-list (in order)

1. `docs/adr/0003-db-per-module-isolation.md` - the isolation rule being enforced (~0.5K).
2. `docs/standards/coding-standards.md` §2 - module layout + facade-only rule (~0.5K).
3. Issue #16 Implementation Decisions - isolation enforcement + transport carve-out (~1K).
4. `docs/architecture/internal-modules.md` §1 - the isolation strategy (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run lint`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria → commands)

- `npm run lint` (the new boundary-check hook runs and passes)
- `npm run test:unit:backend` (checker fixture tests pass)

## Handoff notes

- The transport carve-out is deliberate and must be whitelisted, not worked around: the dispatcher (and the migration harness) are the only cross-schema readers, and only of outbox/schema plumbing (ADR-0003).
- Table namespace prefixes (`consent_consents`, ...) are asserted by the same checker.
- Wire it into pre-commit (a script hook) and the CI lint job; it must run over the real 11-module tree.
- Baselines verified green on 2026-08-10.
