# Brief - T02 Intake + pre-summary domain state machines

**Ticket:** #346 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Both lifecycle state machines exist as pure, no-I/O logic with deterministic transition-matrix tests, following the module state-machine convention. Intake machine: `Captured -> Structuring` (accepted, AI job spawned), `Structuring -> Ready for Review` (pre-summary produced, clean or dirty), `Structuring -> Re-record` (audio unusable, attempts remain), `Re-record -> Structuring` (retry accepted, attempt +1), `Re-record -> forced text` (attempts exhausted, intake finishes as text), `Structuring -> Ready for Review` via raw text when forced/short-circuited. Pre-summary machine: exactly three states `Draft -> Reviewed -> Final` (ADR-0001, never a fourth) with `low_confidence` as a derived property - `structuring_confidence < 0.70` (or missing) sets it and structurally forces doctor review before `Final`. Illegal transitions raise the module's typed exception.

Acceptance criteria:

- [ ] Unit tests cover the full transition matrix for both machines including the re-record attempt cap and forced-text path
- [ ] Illegal transitions raise the typed IntakeError subclass
- [ ] low_confidence derivation is boundary-tested at 0.70 (at-or-above clean, strictly-below flagged, missing flagged)
- [ ] Machines import nothing from schema/facade/adapters (pure logic, no I/O)

## Read-list (in order)

1. Issue #344 Implementation Decisions (both state-machine tables) - the ratified transition matrix (~1.5K)
2. `CONTEXT.md` glossary - pre-summary, structuring confidence, low_confidence flag, forced doctor review (~0.5K)
3. `apps/backend/modules/partner/domain/state_machine.py` - pure transition pattern to mirror (~1K)
4. `apps/backend/modules/intake/domain/exceptions.py` - module error hierarchy, the typed exception subclasses (~0.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- adapters/routes
- AI gateway internals
- schema/facade/adapters module code (machines must not import them)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Pure no-I/O rule is structural: the machine modules import nothing from schema/facade/adapters; keep them side-effect free.
- Boundary is strict: confidence 0.70 is clean, anything strictly below or missing is flagged low_confidence.
- The `intake` module skeleton already exists; new machine modules land under `modules/intake/domain/`.
