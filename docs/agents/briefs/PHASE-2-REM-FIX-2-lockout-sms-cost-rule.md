# Brief - FIX 2 Lockout streak SMS-cost rule, formalized

**Ticket:** #102 · **Parent:** #51 · **Refreshed:** 2026-08-14
**Reading surface:** ~9.5K tokens (budget ~10K) - within budget

## Scope

Wrong-guess OTP failures all route through one `_record_failed_attempt` helper so the SMS-cost counting rule is structural, not incidental: only attempts against an actually-issued challenge (`wrong_code`, `spent`, `expired`, `replay`) count toward the lockout streak. `no_challenge`, `suspended`, and `locked` rejections never touch the counter. Behavior is already correct; this formalizes the rule, documents it in ADR-0004, and pins it with tests.

Acceptance criteria:

- [ ] `verify_otp` wrong-guess failures flow through the extracted `_record_failed_attempt` helper (auth_failed event + `evaluate_failure` + counter update + `otp.failed`-on-threshold in one place).
- [ ] A `no_challenge` verify attempt leaves `lockout_failed_attempts` unchanged.
- [ ] An `expired`/`spent` verify attempt increments the streak.
- [ ] A locked phone's verify attempt does not mutate the streak (existing `test_iam_resend_lockout.py` coverage confirmed, gaps added).
- [ ] ADR-0004 decision 4 records the counting rule and the guard's never-extends-inside-the-window statement.
- [ ] `npm run test:unit:backend` and `npm run test:integration` (native PostgreSQL) pass.

## Read-list (in order, token estimates)

1. `modules.iam.facade` `verify_otp` - the wrong-guess block: `_record_failure` call, `evaluate_failure`, identity counter update, `patient.auth_failed` envelope, `otp.failed`-on-threshold, and the `locked`/outcome returns. This whole block (~474-524) becomes `_record_failed_attempt`; note the existing `_record_failure` helper (challenge write-back) is a separate concern it may reuse, not replace (~2.2K).
2. `modules.iam.facade` `_reject` - the no-counter rejection path (`no_challenge`/`suspended`/`locked`) that must NOT route through the new helper (~1K).
3. `modules.iam.domain.lockout` - `evaluate_failure` + `LockoutDecision` + `lockout_remaining_seconds`; the docstring clarification (facade `FOR UPDATE` guard means the in-window growth line is defensive) goes here (~1K).
4. `docs/adr/0004` decision 4 - add the counting rule (which rejection kinds count and why) + the never-extends-inside-the-window statement (~0.5K).
5. `tests/integration/test_iam_resend_lockout.py` - the lockout test surface to confirm which of `no_challenge`/`expired`/`spent`/locked-streak cases already exist and which to add (~3.6K).

## Do NOT read

- register/resend issue paths (FIX 1's helpers), the gateway, frontend, `docs/archive/`.
- `tests/unit/test_iam_sms_adapter.py`, session tests.

## Baseline verify (from ticket)

- `npm run test:unit:backend` (green this session: 545 passed)
- `npm run typecheck:backend` (green)
- `npm run lint` (green)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration` (needs native PostgreSQL; unverified this session)

## Handoff notes

- Blocked by #101 - both edit `facade.py`; the FIX 1 helper extraction lands first. Re-grep `_record_failed_attempt` if the name no longer resolves (FIX 1's branch may have refactored the region).
- SMS-cost rule: only attempts against a challenge that was actually issued incurred SMS cost, so only those count. `no_challenge` never sent an SMS; `suspended`/`locked` are guards, not attempts.
- ADR-0004 decision 4's counter-reset sentence must stay consistent with the never-extends-inside-the-window statement (ADR-0001 records the 0.70 forced-review threshold, unrelated).
