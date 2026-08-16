# Brief - FIX 1 Register-login challenge invalidation (latest-wins) + dedupe

**Ticket:** #101 · **Parent:** #51 · **Refreshed:** 2026-08-14
**Reading surface:** ~7K tokens (budget ~10K) - within budget

## Scope

Re-entering an existing phone on register invalidates the prior pending challenge before issuing a fresh one (latest-wins, same as resend). The old challenge can no longer verify, and the issue-and-invalidate block is deduplicated into shared helpers used by both `register_patient` and `resend_otp`.

Acceptance criteria:

- [ ] Re-registering an existing phone inside its resend cooldown yields `["Expired", "Pending"]` challenge states (previously `["Pending", "Pending"]`).
- [ ] The old (shadowed) challenge no longer verifies.
- [ ] `resend_otp` behavior is unchanged after the shared-helper extraction.
- [ ] Module docstrings updated (register/resend semantics), no behavior drift on the resend path.
- [ ] `npm run test:unit:backend` and `npm run test:integration` (native PostgreSQL) pass.

## Read-list (in order, token estimates)

1. `modules.iam.facade` `register_patient` - the existing-phone "sent" branch: `_lock_identity` + `_latest_cooldown_until` + `evaluate_resend`, then the fresh-challenge insert + `otp.sent` outbox + `delivery_queue.enqueue` tail (the block `_issue_challenge` must own; today the old challenge is shadowed, not invalidated). Include the register docstring's §2.4 anti-spam-gate text (~2K).
2. `modules.iam.facade` `resend_otp` - the Pending->Expired invalidate (inline at the resend tail) + the same insert/outbox/enqueue block, and its latest-wins docstring. The extracted `_invalidate_pending_challenges` + `_issue_challenge` must match this shape exactly (~1.8K).
3. `tests/integration/test_iam_resend_lockout.py` `test_resend_after_cooldown_issues_fresh_challenge_and_invalidates_pending` - the mirror to replicate for the register path (`["Expired", "Pending"]` assert + old-code-cannot-verify) (~0.8K).
4. `tests/integration/test_iam_registration.py` - the module-level harness (`_facade`/`_flush`/`_query`/`clean_iam`/`MutableClock` fixtures, ~top 150 lines) plus the existing-phone sent-branch tests to mirror the fixture style (~2.2K).

## Do NOT read

- verify/session/refresh facade paths, the gateway, frontend, `docs/archive/`, outbox writer internals.
- `tests/integration/test_iam_verification.py` and lockout internals beyond the mirror test.

## Baseline verify (from ticket)

- `npm run test:unit:backend` (green this session: 545 passed)
- `npm run typecheck:backend` (green: no issues in 136 files)
- `npm run lint` (green: all 16 pre-commit hooks pass)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration` (needs native PostgreSQL; unverified this session)
- `npm run typecheck:backend`

## Handoff notes

- Parent #75 finding: `register_patient`'s existing-phone sent branch leaves two Pending challenges (`["Pending", "Pending"]`) - the old code is shadowed, not invalidated; login must be latest-wins like resend (plan §2.4).
- Keep the `FOR UPDATE` identity lock semantics untouched; the invalidate runs inside the same transaction as the fresh insert.
- The `otp.sent` outbox write + `SmsSendRequest` enqueue must stay in the same helper invocation - one issuance, one SMS cost (SMS-cost rule, FIX 2).
