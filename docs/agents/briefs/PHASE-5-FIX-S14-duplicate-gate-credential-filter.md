# Brief â€” S14 Duplicate-gate verified-credential filter

**Ticket:** #267 Â· **Parent:** #243 Â· **Refreshed:** 2026-09-02
**Reading surface:** ~13K tokens (budget 10K) â€” slightly over but manageable with targeted reads

## Scope

The credential duplicate gate's `_load_live_credential_types` reads every credential row regardless of state, so a previously rejected/cleaned credential could false-trip the "already have this credential type" duplicate rejection on a fresh submission. Filter to live/verified credentials only so only credentials that are actually active count toward the duplicate gate.

**Acceptance criteria:**

- [ ] `_load_live_credential_types` returns only credentials in the live set (verified/active, not rejected/expired/pending-cleanup).
- [ ] A partner with only non-live credentials can submit that credential type without a false duplicate rejection.
- [ ] Duplicate-gate unit/integration tests cover a stale (rejected) credential not tripping the gate.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py:496-519` â€” `_load_live_credential_types` definition; current query and return type (~60 tokens)
2. `apps/backend/modules/partner/facade.py:823-929` â€” `submit_credentials` caller; how the result feeds into the duplicate gate (~2,800 tokens)
3. `apps/backend/modules/partner/schema/models.py` â€” credential status vocabulary; `partner_credentials` table schema with `verified`, `round`, `cleanup_due_at` fields (~2,220 tokens)
4. `docs/spec/phase-5-partner-onboarding.md` â€” duplicate credential rule from the spec (~4,369 tokens)
5. `tests/unit/test_partner_prefilter.py:139-194` â€” existing duplicate-gate unit tests (~400 tokens)
6. `tests/unit/test_partner_rejection_recovery_facade.py:339-374` â€” existing `_load_live_credential_types` unit tests (~800 tokens)
7. `tests/integration/test_partner_credentials.py:174-338` â€” existing duplicate-gate integration tests (~1,600 tokens)

## Do NOT read

- `modules/iam` â€” out of scope
- `modules/notify` â€” out of scope
- `docs/archive/` â€” superseded by spec

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q` â€” 1151 passed (confirmed 2026-09-02)

## Done-verify (acceptance criteria â†’ commands)

- `npm run test:unit:backend` â€” partner unit/integration tests pass
- `npm run typecheck` â€” mypy strict passes

## Handoff notes

- The `partner_credentials` table has no status enum column; credential "state" is inferred from `verified` (bool), `round` (bigint), and `cleanup_due_at` (nullable datetime). A credential is "live" if `verified = true` AND `cleanup_due_at IS NULL`.
- The current `_load_live_credential_types` filters only on `round == current_round` â€” it does NOT filter on `verified` or `cleanup_due_at`. The fix should add a `WHERE verified = true AND cleanup_due_at IS NULL` clause (or equivalent).
- The caller in `submit_credentials` already bypasses the duplicate gate for `Rejected`/`Active` profiles by passing `frozenset()` â€” the fix should ensure the query itself also returns only live credentials.
- Test `test_live_credential_types_scoped_to_current_round` at line 343 of `test_partner_rejection_recovery_facade.py` directly tests `_load_live_credential_types` â€” this test should be extended to cover the verified/cleanup filter.
- Test `test_duplicate_submission_auto_fails_never_queued` at line 174 of `test_partner_credentials.py` is the integration test â€” add a case where a rejected credential of the same type doesn't trip the gate.
