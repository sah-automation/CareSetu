# Brief - 459 Integration fixtures drive the real activation seam (drop hand-built SQL rows)

**Ticket:** #459 · **Parent:** #455 · **Refreshed:** 2026-09-17
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The integration tests that need a directory-visible partner stop hand-building it with SQL fixture rows and instead drive the real operator-approval path (the activation seam from #456) so a test partner becomes directory-visible exactly the way a real doctor does. Drop the hand-built `partner_directory_index` INSERTs and `partner_credentials.verified = true` UPDATEs that were masking the missing application seam.

Acceptance criteria:

- [ ] The directory-search and credential-expiry-sweep integration tests construct directory-visible partners through the operator-approval path (activation seam), not hand-built SQL rows.
- [ ] No test fixture under the integration suite still hand-writes `partner_directory_index` rows or force-stamps `partner_credentials.verified = true` for partner setup (only legitimate test-data seeds remain, if any).
- [ ] Integration suite green (local PostgreSQL; skipped when unreachable).

## Read-list (in order)

1. `tests/integration/test_directory_search.py` and `tests/integration/test_partner_credential_expiry_sweep.py` - the fixture rows to convert; also check `test_directory_search_cache.py` and `test_directory_index_backfill.py` for the same hand-written pattern (~4K).
2. The activation seam's entry interface (from #456's merged transition) - how a test partner gets approved/activated (~0.5K).
3. Integration harness: the conftest/engine/fixture build pattern in `tests/integration/` (plus its README if present) (~1.5K).

## Do NOT read

- Unrelated integration tests (care, iam-operator MFA, notify, etc.), worker-bus wiring, artifact store, frontend/UI code, `docs/archive/`.

## Baseline verify

- `npm run test:unit:backend` (minus the 3 recorded OTP config failures) and `npm run test:integration` (skips if PostgreSQL unreachable - record whether it ran).

## Done-verify

- `npm run test:integration` green with the converted fixtures; `npm run typecheck`.

## Handoff notes

- Depends on #456 (the seam) and #457 (the corrected visibility predicate) - the converted fixtures exercise both: activate via decision path, and re-submission scenarios depend on the round-scoped predicate.
- The expiry-sweep test's de-listing assertion depends on `close_out_credentials` (unchanged) - the fixtures should drive it through the real seams end to end.
- If a fixture legitimately needs a partner visible WITHOUT a full operator round (e.g. an unrelated test's data seed), keep it only with a comment naming the exemption; the AC forbids partner-setup hand-writes, not all seeds.
