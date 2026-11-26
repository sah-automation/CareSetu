# Brief - 458 Backfill migration for already-approved Active partners (verified + directory index)

**Ticket:** #458 · **Parent:** #455 · **Refreshed:** 2026-09-17
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

One idempotent alembic migration that backfills every `Active` partner with an approved round but absent/failed verified-state or directory-index requirements: stamp that round's `partner_credentials` rows `verified = true` and upsert the `partner_directory_index` row, using the same semantics as the runtime activation seam (#456). Fixes the population the v6_0 one-shot backfill missed (every approval since) and removes the need for ad-hoc dev-DB repair.

Acceptance criteria:

- [ ] One new alembic migration, idempotent (re-run is a no-op against an already-consistent DB), covering: `Active` partners with an approved round but no index row, and `Active` partners with unverified current-round credentials.
- [ ] Migration semantics mirror the runtime activation seam (#456) - same verified-stamp and index-upsert conditions - so backfill and live path agree.
- [ ] `npm run migration-check` and `alembic upgrade head` against the repo DB pass.

## Read-list (in order)

1. The v6_0 directory-index migration (`9f6c2e1b7d3a4` backfill, rows ~100-136) - the SQL pattern (idempotent INSERT ... ON CONFLICT, EXISTS guards mirroring `has_any_credential` / "no invalid credential") (~1.5K).
2. The activation seam's verified-stamp + index-upsert semantics from #456's implemented transition (its SQL is the source of truth; #456 must land/merge first) (~1K).
3. Alembic revision header/file convention - a recent migration (`v8_5` era, e.g. the consultation-fee column migration) for revision id, `revision`/`down_revision` wiring, and `run_migrations_online` style (~1.5K).
4. `tests/integration/test_directory_index_backfill.py` - existing backfill test harness to extend for the new migration's conditions (~1K).

## Do NOT read

- Worker-bus wiring, artifact store, domain rule modules, credential-intake internals, `docs/archive/`, unrelated migrations.

## Baseline verify

- `npm run migration-check` (single-head gate) and `npm run test:unit:backend` (minus the 3 recorded OTP config failures).

## Done-verify

- `npm run migration-check`; `alembic upgrade head` (and downgrade/re-upgrade where the convention mandates) against the integration DB; new/extended migration test green.

## Handoff notes

- The seam (#456) is blocked-by-this? No - this is blocked BY #456 (semantics source). Do not author the SQL until the seam's exact conditions are visible in the merged transition.
- The v6_0 migration used raw `op.execute` SQL - match that style unless the #456 transition used the ORM; prefer identical expressions either way.
- Migration must leave genuinely-correct data: never stamp `verified = true` on a round that the operator did not approve (`partner_verifications.status = 'approved'` gate).
