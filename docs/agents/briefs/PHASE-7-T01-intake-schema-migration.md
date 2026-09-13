# Brief - T01 Intake schema migration + SQLAlchemy models

**Ticket:** #345 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The `intake` database schema becomes real: a single alembic migration (next free revision id) creates the Phase 7 tables - `intakes` (mode voice|text, language hi|en, status, record_attempts, text, transcript, transcript-usability flag, forced-text flag, timestamps), `pre_summaries` (structured fields JSONB, structuring confidence, low_confidence flag, review state, patient edits, doctor corrections, review attribution + timestamp), `ai_jobs` (task type, provider, model, tokens, cost paise, status, error, confidence, duration, attempts), `media_refs` (audio duration, size, record attempt), plus the module's `intake_outbox` and consumed-events ledger - all under the private `intake` schema with no cross-schema FKs. SQLAlchemy models under `MODULE_METADATA = MetaData(schema="intake")` expose them. Nothing else works yet, but every later intake ticket has tables to write to.

Acceptance criteria:

- [ ] `npm run migration-check` passes with the new migration as the single chain head
- [ ] Migration creates tables intakes, pre_summaries, ai_jobs, media_refs, intake_outbox and the consumed-events ledger under schema `intake`, with no cross-schema foreign keys (passes the migration FK scan)
- [ ] SQLAlchemy models import cleanly and unit test asserts the table/column surface (mode/language/status enums, JSONB fields, attempt counters)
- [ ] Baseline backend unit suite still passes

## Read-list (in order)

1. `docs/architecture/internal-modules.md` §3.5 (intake data model) - columns/statuses the schema must expose (~1.5K)
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - outbox + consumed-events ledger contract (~1K)
3. `apps/backend/bus/outbox_ddl.py` - outbox + consumed-events DDL to replicate under schema `intake` (~0.5K)
4. A recent alembic migration that created a module schema (e.g. consent or partner init migration) - tables via `op`, own `MetaData` per module (~1.5K)
5. `apps/backend/modules/partner/schema/models.py` - SQLAlchemy model conventions (`MODULE_METADATA`, enums, JSONB) (~1.5K)
6. `apps/backend/bus/bootstrap.py` - schema registration list where `intake` joins (~0.5K)
7. Existing `apps/backend/modules/intake/` skeleton (`schema/models.py`, `domain/exceptions.py`) - what is already stubbed (~0.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- worker internals beyond the registration list
- modules other than the consent/partner init migrations and partner models

## Baseline verify (must pass before the first edit)

- `npm run migration-check` - green at single head `dfde54f96bb1` (verified 2026-09-08)
- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - mypy + tsc clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run migration-check`
- `npm run test:unit:backend`

## Handoff notes

- The `intake` module skeleton already exists (`modules/intake/schema/models.py`, `facade.py`, `outbox.py`, `domain/exceptions.py`) - do not add a second models file, extend `schema/models.py`.
- Migration revision id: use the next free revision after the current single head; `scripts/migration-check.cjs` is the gate.
- The todo marked `status: ready-for-agent` on the ticket already carries the authoritative context pack; this brief refreshes it against the live tree.
