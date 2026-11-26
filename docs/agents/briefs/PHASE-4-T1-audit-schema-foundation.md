# Brief - T1 Audit schema foundation + tamper trigger

**Ticket:** #235 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Create the full database schema for MOD-011 (Audit) and the patient access history table in MOD-003 (Health). This is the foundation all other Phase 4 tickets depend on. Builds `audit.audit_events` (append-only, hash-chained), `audit.tamper_attempts`, bus plumbing tables, `health.record_access_history`, a PostgreSQL trigger for tamper detection, and the Alembic migration `v3.0__init_audit.py`.

Acceptance criteria: see #235 body verbatim.

## Read-list (in order)

1. Most recent migration `apps/backend/alembic/versions/b27d495bfe70_v2_2__consent_egress_log.py` - naming convention, DDL style, `op.execute()` pattern (~1K)
2. `apps/backend/modules/audit/schema/models.py` - current empty scaffold, single placeholder table (~0.3K)
3. `apps/backend/modules/audit/outbox.py` - outbox table constant (~0.2K)
4. `apps/backend/modules/health/schema/models.py` - existing health tables including `health_record_access_history` (~1K)
5. `apps/backend/bus/outbox_ddl.py` - DDL templates for outbox/consumed_events tables (~0.5K)
6. `docs/standards/coding-standards.md` - section on append-only table protection (~0.3K)
7. `docs/standards/security-phii-standards.md` - audit trail DB protection rules (~0.3K)
8. `docs/architecture/internal-modules.md` - MOD-011 section for table shapes, MOD-003 for health tables (~1.5K)

## Do NOT read

- Other module schemas or facades, bus infrastructure internals, docs/archive/, frontend code, any test files beyond the patterns you need.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`, `npm run migration-check`.

## Done-verify (acceptance criteria -> commands)

- `npm run migration-check` (single head preserved, no cross-schema FKs)
- `npm run test:unit:backend` (no regressions from new models)
- Manual: migration applies on fresh DB, REVOKE test passes on `audit_events`, trigger fires on UPDATE/DELETE

## Handoff notes

- Migration continues the linear chain after `b27d495bfe70_v2_2__consent_egress_log`; version `v3.0` maps to Phase 4.
- The `audit_events` table needs: `id UUID PK`, `event_type TEXT NOT NULL`, `actor_id UUID`, `target_id UUID`, `scope TEXT`, `metadata JSONB`, `timestamp TIMESTAMPTZ NOT NULL`, `prev_hash TEXT NOT NULL`, `hash TEXT NOT NULL`. Append-only enforced via `REVOKE UPDATE, DELETE`.
- `tamper_attempts` columns: `id UUID PK`, `attempted_at TIMESTAMPTZ`, `attempted_operation TEXT`, `target_event_id UUID`, `attempted_by UUID`, `details JSONB`.
- `health.record_access_history` columns: `id UUID PK`, `record_id UUID NOT NULL`, `actor_id UUID NOT NULL`, `actor_type TEXT`, `scope TEXT`, `accessed_at TIMESTAMPTZ`, `denied BOOLEAN DEFAULT FALSE`, `denial_reason TEXT`.
- The trigger function catches UPDATE/DELETE as defense in depth (REVOKE is the primary guard). Trigger inserts into `tamper_attempts` with the operation details.
- No cross-schema imports/SQL/FKs ever; only legal seams are facade calls + outbox events.
