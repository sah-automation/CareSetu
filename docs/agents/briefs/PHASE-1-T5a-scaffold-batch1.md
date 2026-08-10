# Brief - PHASE-1 T5a Module scaffold batch 1 + generator

**Ticket:** #24 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

A scaffold generator script plus the first six module packages (`iam, partner, health, consent, intake, care`), each with the hexagonal layout (`domain/`, `adapters/`, `schema/`, `facade.py`, `outbox.py`). A layout-assertion unit test checks structure and table namespace prefixes. No business logic.

Acceptance criteria:

- [ ] Generator script can emit a module package with the hexagonal layout
- [ ] Six modules scaffolded: iam, partner, health, consent, intake, care
- [ ] Layout-assertion unit test passes for batch 1
- [ ] `mypy --strict` green on the new packages

## Read-list (in order)

1. `docs/standards/coding-standards.md` §2 - module structure, namespace prefixes, facade-only rule (~0.5K).
2. `docs/adr/0003-db-per-module-isolation.md` - schema ownership per module (~0.5K).
3. `docs/architecture/internal-modules.md` §3 - the six module names + owning schemas (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`, any module business logic (Phase 2+).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck:backend`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (layout-assertion test passes)
- `npm run typecheck:backend` (`mypy --strict`)

## Handoff notes

- Hexagonal layout per coding-standards §2: `domain/` (pure, no I/O), `adapters/` (routers/handlers), `schema/` (SQLAlchemy models for THIS module's schema only), `facade.py` (only legal cross-module import target), `outbox.py`.
- Table namespace prefixes: `consent_consents`, `care_prescriptions`, etc.
- No business logic in this ticket - packages and seams only.
- Baselines verified green on 2026-08-10.
