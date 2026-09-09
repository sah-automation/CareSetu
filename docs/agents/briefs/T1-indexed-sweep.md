# Brief - T1 Indexed daily credential-expiry sweep

**Ticket:** #323 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The operator's daily credential-expiry sweep runs against an index instead of scanning the full credential table, so it stays fast as the directory grows - the same "simple indexed job" promise as the daily backup. Purely a physical-plan fix: the sweep's idempotency key (`invalidation_reason IS NULL`), single-transaction close-out, index deactivation, and one `credential.invalidated` event per credential stay exactly as shipped.

Acceptance criteria (from #323):

- [ ] A new Alembic migration (v-prefixed, matching the repo naming pattern) creates a partial index over the sweep predicates on `partner_credentials`; the migration is tested by the repo's alembic single-head + cross-schema-FK gate.
- [ ] `close_out_expired_credentials` is byte-for-byte unchanged in semantics: single transaction, idempotent on replay, exactly one `credential.invalidated` per expired credential with deindex + audit.
- [ ] The existing integration sweep suite (expiry close-out, idempotent replay, lazy read-hide, no double-fire with revocation) stays green unchanged.
- [ ] `npm run migration-check` and `npm run test:integration` pass.

## Read-list (in order)

1. `CONTEXT.md` Phase-6 glossary blocks - `credential expiry`, `credential revocation`, `directory entry`, `verified` - the domain vocabulary the sweep preserves (~0.5K)
2. `docs/architecture/internal-modules.md` MOD-002 spec + event registry §4.2 - module seams, `partner_credentials` ownership, the `credential.invalidated` outbound event (~1.5K)
3. `docs/roadmap/implementation-roadmap.md` Phase 6 section - the "simple indexed job like the daily backup" promise and what Phase 6 shipped (~1K)
4. `docs/standards/coding-standards.md` migration rules - alembic single-head, v-prefixed naming, no cross-schema FK (ADR-0003) (~2K)
5. `partner` schema model: `partner_credentials` and the existing partial index `ix_partner_credentials_cleanup_due` - the `postgresql_where` pattern to mirror (~0.5K)
6. The latest `partner` Alembic migration in `apps/backend/alembic/versions/` (head `9f6c2e1b7d3a`, the phase-6 directory index) - revision naming/convention to copy (~0.5K)
7. The facade method `close_out_expired_credentials` - the sweep whose semantics you must NOT change (filter incl. `invalidation_reason IS NULL`, single `async with self._engine.begin()`, bulk UPDATE, per-partner deindex, one outbox row per credential) (~1.5K)
8. `tests/integration/test_partner_credential_expiry_sweep.py` - the pinning suite (close-out+deindex, idempotent replay, lazy read-hide, revocation interplay) (~1.5K)

## Do NOT read

- Any other module schema, `docs/archive/`, the frontend, the artifact store, credential _types_ domain, or worker-scheduler internals beyond what the sweep test references. The index goes in the `partner` schema only.

## Baseline verify (must pass before the first edit)

- `npm run migration-check`
- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run migration-check`
- `npm run test:integration`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Baseline truth (2026-09-06, before any edit): backend unit 1243 pass, migration-check single-head OK, integration 198 pass / **2 pre-existing failures unrelated to MOD-002** (`test_bootstrap_schemas.py`, `test_consent_check_gate.py::test_p95_latency_under_50ms`) - do not chase them.
- The partial index mirrors `ix_partner_credentials_cleanup_due`: an `Index(..., postgresql_where=text(...))` on the `partner_credentials` model, surfaced by the partner model's `__table_args__`, not inline SQL in the migration body beyond the standard alembic op.
- Sweep predicates to index over, from the unchanged WHERE: `expires_at IS NOT NULL` / overdue + `invalidation_reason IS NULL` + `verified` (the `[Active]` profile join is on `profile_id`/`identity_id`).
- Single-head today is `9f6c2e1b7d3a`; your migration becomes the new head and must stay single-head.
- Ticket #324 (bounded results) also touches `search_directory`; it does not touch the sweep or migrations - no overlap beyond both passing `test:integration`.
