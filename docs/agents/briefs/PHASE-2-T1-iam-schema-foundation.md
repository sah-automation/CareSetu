# Brief - PHASE-2 T1 `iam` schema foundation

**Ticket:** #52 · **Parent:** #51 · **Refreshed:** 2026-08-12
**Reading surface:** ~3K tokens (execution budget 120K incl. initial read + tests) - within budget

## Scope

The `iam` schema data foundation: migration `v1.0__init_iam.sql` creates `identities`, `otp_challenges`, `sessions`, `role_grants`, and `iam_outbox`; SQLAlchemy models mirror them under the `iam` schema metadata with `iam_` prefixes. The migration harness, module boundary checker, and migration single-head gate stay green.

Acceptance criteria:

- [ ] Migration creates `identities` (phone_e164 unique, status Unverified/Active/Suspended), `otp_challenges` (hashed, single-use, TTL, cooldown), `sessions` (jti, expiry, scope), `role_grants`, `iam_outbox`
- [ ] Models are `iam_`-prefixed under the `iam` schema metadata (coding-standards table-namespace rule)
- [ ] `npm run migration-check` passes (single head, no cross-schema FK)
- [ ] `npm run check:boundaries` passes (iam owns its schema only, ADR-0003)
- [ ] Integration test asserts the five tables exist after upgrade

## Read-list (in order)

1. `docs/agents/briefs/PHASE-1-T1b-bootstrap-schemas.md` - how schemas + the async Alembic harness were bootstrapped in Phase 1 (~0.5K).
2. `apps/backend/alembic/versions/` - the v0.0 bootstrap migration and an empty baseline to copy revision/style from (~1K).
3. `apps/backend/modules/iam/schema/models.py` - the existing scaffold (metadata pattern) to extend (~0.5K).
4. `apps/backend/bus/outbox_ddl.py` - the outbox table shape every module reuses (~0.5K).
5. `docs/adr/0003-db-per-module-isolation.md` + CONTEXT.md glossary `module isolation rule`, `outbox` (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`, the bus dispatcher internals, any module domain logic.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run migration-check`
- `npm run check:boundaries`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (new five-tables test passes)
- `npm run migration-check`
- `npm run check:boundaries`
- `npm run test:unit:backend`

## Handoff notes

- `phone_e164` is the unique duplicate-arbiter column; nothing else about uniqueness is needed yet.
- Status values are the canonical `Unverified`/`Active`/`Suspended` strings (CONTEXT glossary, FEAT-001).
- No business events are registered in this ticket; the outbox table is empty contract only.
- Migrations are async Alembic revisions - copy the harness style from the nearest Phase 1 revision.
