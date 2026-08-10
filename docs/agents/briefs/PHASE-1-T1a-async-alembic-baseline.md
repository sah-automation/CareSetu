# Brief - PHASE-1 T1a Async Alembic migration harness

**Ticket:** #17 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The migration harness exists and is async. A fresh native PostgreSQL runs `alembic upgrade head` cleanly (a no-op on the empty baseline), `alembic upgrade head` then `alembic downgrade base` round-trips, and the existing `migration-check` gate reports a single head.

Acceptance criteria:

- [ ] `alembic upgrade head` succeeds against a fresh PostgreSQL with no migration applied
- [ ] `alembic upgrade head` then `alembic downgrade base` round-trips cleanly
- [ ] `npm run migration-check` exits 0 reporting a single head
- [ ] The migration harness is async SQLAlchemy (no sync-only migration path)

## Read-list (in order)

1. `docs/roadmap/implementation-roadmap.md` §2.1.3/§2.1.4 - the migration-harness intent and the `v0.0__bootstrap_schemas` plan (~1K).
2. `docs/standards/coding-standards.md` §5 - one harness, additive versioned deltas (~0.5K).
3. `docs/adr/0003-db-per-module-isolation.md` - the 11-schema baseline the harness must later create (~0.5K).
4. The existing alembic scaffold (`apps/backend/alembic/` env, ini, versions) - what must be converted to async (~1K).
5. `scripts/migration-check.cjs` and `tests/integration/conftest.py` - the gate and the native-PG fixture the harness works with (~1K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`, any module business logic (none exists yet).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run lint`
- `npm run typecheck:backend`
- `npm run migration-check` (currently reports "no migrations yet" - expected pre-T1a)

## Done-verify (acceptance criteria → commands)

- `npm run migration-check` exits 0 with a single head
- `alembic upgrade head` then `alembic downgrade base` against the local native PG round-trips

## Handoff notes

- Baselines verified green on 2026-08-10 (162 unit passed; migration-check "no migrations yet" is the pre-T1a truth).
- `scripts/migration-check.cjs` resolves the venv via `CARESETU_BACKEND_ENV` (default `backend-env`) at `D:\Dev\venvs\`.
- The alembic env.py is currently the stock sync template - the async conversion is this ticket's core.
- Stack is locked: async SQLAlchemy 2.0 + asyncpg, no paid dependencies (`NFR-001`).
- Repo conventions: no em-dashes (use simple dashes); markdown runs through prettier/pre-commit.
