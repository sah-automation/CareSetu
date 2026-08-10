# Brief - PHASE-1 T5b Module scaffold batch 2

**Ticket:** #25 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

The remaining five module packages (`diagnostics, fulfillment, settlement, notify, audit`) via the batch-1 generator, the full-11 layout-assertion test, and `mypy --strict` green across all modules. No business logic.

Acceptance criteria:

- [ ] Five modules scaffolded via the generator: diagnostics, fulfillment, settlement, notify, audit
- [ ] Layout-assertion test passes across all 11 modules
- [ ] `mypy --strict` green on all modules
- [ ] Namespace-prefix convention holds on every table model

## Read-list (in order)

1. `docs/standards/coding-standards.md` §2 - module structure and namespace prefixes (~0.5K).
2. `docs/architecture/internal-modules.md` §3 - the five module names + owning schemas (~0.5K).
3. Brief from #24 - the generator usage pattern (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck:backend`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (full-11 layout test passes)
- `npm run typecheck:backend` (`mypy --strict` across all modules)

## Handoff notes

- Reuse the batch-1 generator for consistency; do not hand-write divergent structure.
- The full-11 layout test is the input to #26 (T6a, boundary checker) which lints the real tree.
- No business logic - packages and seams only.
- Baselines verified green on 2026-08-10.
