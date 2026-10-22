# Brief - 03 Record access history stops recording owner reads

**Ticket:** #665 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

The record access history answers only "who ELSE has seen my record": owner reads stop dual-writing an access-history row or outbox envelope (plain own-record read and allowed addressed read; the addressed read's DENIED path stays), a purge migration deletes stored self rows while keeping cross-patient denied rows, and the read path filters self rows as belt-and-suspenders with the both-columns predicate (actor is patient AND accessor is the record's owner). The record-access-history glossary entry is updated.

Acceptance criteria:

- [ ] Owner reads (plain own-record read and allowed addressed read) write no access-history row and no outbox envelope
- [ ] The addressed read's DENIED path still records its row
- [ ] An alembic migration (single head) purges stored self rows with the both-columns predicate; cross-patient denied rows are retained
- [ ] The access-history query excludes self rows at read time even if the migration has not run
- [ ] Integration tests re-seeded via counterparty reads prove: owner reads leave no rows, a pre-existing self row is invisible, a cross-patient denied row survives; unit tests pin the filter predicate and row mapping
- [ ] The record-access-history glossary entry is updated
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run migration-check`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. Spec #662 §Solution "Access history: no self rows, real names" - focus on the no-self-rows bullets; user stories 14-15, 21-22, 25; Implementation Decisions (write stop, read-path filter, purge migration, deployment order) and Testing Decisions (~2.5K)
2. CONTEXT.md glossary entry "record access history" - the entry to update (counterparty reads and denied attempts, not owner reads) (~0.3K)
3. `HealthFacade` write seam: `_log_access` (the single ledger+outbox dual-write), `get_own_record` (owner read), `get_record_as_owner` (allowed = stop, denied = keep) - apps/backend/modules/health/facade.py (~1.8K)
4. `HealthFacade.query_access_history` + `AccessHistoryEntry` + `get_access_history` - the SQL, row mapping, and entry model the filter and (later) the display-name field attach to (~1.2K)
5. The access-history table definition in the health schema models (~0.5K)
6. Migration prior art in apps/backend/alembic/versions/: the additive-column migration for this table (raw `op.execute` ALTER) and one existing data migration using raw `DELETE FROM ... WHERE` - the shape to copy; chain the new revision onto the current head reported by `alembic heads` (~1.5K)
7. `tests/integration/test_patient_access_history_api.py` - currently seeded via owner reads; those seeds and assertions must be reworked (~1.5K)
8. `tests/unit/test_access_history_facade.py` - pins the SELECT shape and row mapping (~1K)
9. Owner-read-recorded tests in `tests/integration/test_health_record_shell.py` - assert exactly the behavior being removed; update, do not delete (~1K)
10. Audit route serving the view (read-path delegation only - no change expected) (~0.3K)

## Do NOT read

- The counterparty display-name resolver and `actor_display_name` work (ticket #668 owns it)
- Frontend rendering (ticket #670)
- Consent facade, egress log, outbox dispatcher internals
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 2919 passed (2026-10-08)
- `npm run migration-check` - single head `3e7c5a1d8f24`, FK check OK (2026-10-08)
- `npm run test:integration` - see Handoff notes (baseline: 263 passed, 1 pre-existing failure, 22m39s)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration` - owner reads write nothing; purge predicate hides pre-existing self rows; cross-patient denied row survives; doctor counterparty read writes a row
- `npm run migration-check` - single head after adding the purge migration
- `npm run lint`, `npm run typecheck`

## Handoff notes

- The filter predicate keys on BOTH actor and accessor columns: doctor rows store partner ids in the same accessor column, so bare accessor-inequality would mis-handle id-namespace collisions (spec decision - do not "simplify" it).
- Purge migration is the primary cleanup; the read filter is belt-and-suspenders. Deployment order: migration ships with the code; rollback of code alone still hides self rows (harmless).
- Owner reads also stop emitting `record.accessed`/`record.denied` outbox envelopes - no event names change, no registry change (consequence recorded in spec).
- Integration baseline (2026-10-08): 264 tests, 263 passed, 1 pre-existing failure - `tests/integration/test_consent_check_gate.py::test_p95_latency_under_50ms` (p95 latency budget, environment-sensitive). Do not blame this change for it; the suite takes ~23 minutes locally (native PostgreSQL required).
