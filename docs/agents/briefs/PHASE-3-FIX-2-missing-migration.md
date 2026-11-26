# Brief - FIX-2 Add missing consent_egress_log migration

**Ticket:** #221 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

`consent.consent_egress_log` table exists in the database. The SQLAlchemy model is defined but the alembic migration is missing, causing runtime failures on any egress log operation.

**Acceptance criteria:**

- New alembic migration `v2_2__consent_egress_log.py` creates the `consent.consent_egress_log` table
- Migration includes all constraints, indexes matching `consent/schema/models.py` exactly
- `npm run migration-check` passes (single-head gate + no cross-schema FK violations)
- Integration test proves the table is queryable after migration

## Read-list (in order)

1. `apps/backend/modules/consent/schema/models.py:112-136` - the `consent_egress_log` SQLAlchemy model to replicate in DDL (~136 tokens)
2. `apps/backend/alembic/versions/7be3a5c92d10_v2_1__init_consent.py` - migration conventions (revision IDs, DDL style, downgrade pattern) (~115 tokens)

**Total:** ~250 tokens of reading, well within budget.

## Do NOT read

- Facade code, route code, frontend code
- Other migration files (not relevant to this fix)
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run migration-check` - verify current state
- Confirm `consent_egress_log` is NOT in any existing migration (grep `versions/` for `egress_log`)

## Done-verify (acceptance criteria → commands)

- `npm run migration-check` passes
- `npm run test:integration` passes (if DB available)
- `alembic upgrade head` creates the table (manual verification)

## Handoff notes

- The table DDL is in `consent/schema/models.py:112-136` - replicate it exactly in the migration
- Follow the pattern in `v2_1__init_consent.py` for DDL style (raw SQL with `op.execute`)
- Downgrade must drop indexes before the table
- The table has: `id`, `patient_id`, `consent_id`, `lineage_ref`, `version`, `counterparty_type`, `counterparty_id`, `record_scope`, `disclosed_entry_ids` (JSONB), `disclosed_at`
- CHECK constraints: `counterparty_type IN ('doctor', 'lab', 'chemist')`, `record_scope IN (...)`
- Indexes: `ix_consent_egress_log_patient`, `ix_consent_egress_log_consent`
