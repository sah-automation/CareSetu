# Brief - PHASE-1 T1b Bootstrap: 11 schemas + outbox DDL template

**Ticket:** #18 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

A versioned bootstrap migration creates the 11 private schemas (`iam, partner, health, consent, intake, care, diagnostics, fulfillment, settlement, notify, audit`) plus the shared outbox/`consumed_events` DDL template and a Python helper that later tickets use to materialize throwaway outbox/ledger tables. An integration test asserts all 11 schemas exist after `alembic upgrade head`.

Acceptance criteria:

- [ ] `alembic upgrade head` creates all 11 private schemas
- [ ] Integration test asserts the full 11-schema list after upgrade
- [ ] The outbox DDL template + materialization helper exist and are importable by tests
- [ ] No module outbox tables are created yet (Phase 2+) - only the template/helper

## Read-list (in order)

1. `docs/roadmap/implementation-roadmap.md` §2.1.3 - the bootstrap schema delta and outbox DDL template plan (~0.5K).
2. `docs/adr/0003-db-per-module-isolation.md` - the 11-schema layout and no-cross-schema rule (~0.5K).
3. `docs/standards/coding-standards.md` §5 - additive versioned deltas (~0.5K).
4. Issue #16 Implementation Decisions - migration harness + outbox row contract (~1K).
5. Brief from #17 + `tests/integration/conftest.py` - the harness shape and fixture pattern to build on (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run migration-check`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (schema-list test passes)
- `npm run migration-check` (single head)

## Handoff notes

- The helper must be importable by tests (Python) and support both outbox and `consumed_events` materialization - #19 (T2a) and #20 (T2b) depend on it.
- Per-module `*_outbox` tables are deliberately NOT created now; only the template/helper.
- Baselines verified green on 2026-08-10.
