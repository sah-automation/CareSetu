# Brief - T2 Lockout lifts after its 15-minute window (streak reset)

**Ticket:** #85 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~9K tokens (budget ~10K) - within budget

## Scope

A brute-force phone lockout is genuinely temporary: once the 15-minute window has fully elapsed, a patient can try again and a single mistake does not instantly re-lock the phone for another 15 minutes. The consecutive-failure streak resets when the window lifts, so ten fresh failures across challenges are needed to lock again - matching the spec's "try again after 15 minutes" promise.

Acceptance criteria:

- [ ] A failure occurring after the lockout window has elapsed starts a fresh streak (counter resets) instead of immediately re-triggering the lockout
- [ ] A failure occurring while the window is still open still counts toward the active lockout (no behaviour change inside the window)
- [ ] The lockout remains a counter, never identity state; `Suspended` is untouched
- [ ] Unit tests pin the expiry boundary (in-window vs after-window failure)

## Read-list (in order)

1. The lockout counter interface `LockoutDecision` / `evaluate_failure` / `lockout_remaining_seconds` (MOD-001 lockout counter, pure logic, no I/O) - the "counter keeps growing past the threshold so once a lockout expires any failure immediately re-locks" rationale is the defect (~0.7K).
2. The verify path in the IAM facade that calls it - `IamFacade.verify_otp` failure write-back branch: reads the locked identity's `lockout_failed_attempts` + `lockout_until`, then `evaluate_failure(lockout_failed_attempts, now)` without passing `lockout_until`, so an expired window still sees counter >= threshold and instantly re-locks; `lockout_remaining_seconds` already returns `None` once the window lifts (inclusive boundary at `now == lockout_until`) (~2.5K).
3. `IamFacade.register_patient` (begin-or-resume, the login entry - no separate login route) and `IamFacade.resend_otp` via `evaluate_resend`: confirm neither path mutates the streak; `register_patient` does not touch the counter, `resend_otp` only refuses while locked (~2.0K).
4. The failure / `VerifyOtpResult` outcome shapes the PWA renders - `VerifyOtpResult.outcome` union (`verified | wrong_code | expired | spent | locked`), `lockout_remaining_seconds`, and the `useOtpFlow` `submitOtp` branch (`challenge: "locked"`, `lockoutRemaining`) - confirms no frontend change; the countdown already clears when remaining reaches 0 (~1.8K).
5. Spec #51 (PHASE-2-IAM-AUTH) Implementation Decision 4 (OTP challenge contract, the "ten consecutive failures ... 15-minute temporary phone lockout, implemented as a counter, never as identity state" promise) and User Stories 17/18 (~0.3K).
6. `docs/adr/0004-otp-challenge-and-brute-force-contract.md` decision 4 and consequence "the lockout is temporary and automatic; the patient retries after 15 minutes without operator help" (~0.6K).
7. Lockout boundary tests - `test_iam_lockout.py` (`test_failure_after_lockout_expired_relocks_immediately` pins the current wrong behavior and its expectation flips) and `test_iam_resend_lockout.py` (in-window behavior stays) (~2.2K).

## Do NOT read

Frontend beyond the outcome strings and `submitOtp` branch, dispatcher internals, `docs/archive/`, `phase0/`, session/refresh logic (T6/T7), SMS adapter (T4), audit module internals.

## Baseline verify

- `npm run test:unit:backend` (already verified green centrally: 494 passed on 2026-08-13)

## Done-verify

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Parent #75 finding cluster: "lockout not actually temporary" - the build violates ADR-0004 decision 4 and spec #51 §2.4, which promise a temporary, automatic lockout. The counter must also reset when the window elapses, not only on successful verification.
- The defect lives in the lockout counter's `evaluate_failure`: it never considers the elapsed `lockout_until`, so the streak is permanent once it reaches the threshold. The facade passes only the raw counter; the fix needs the window state (now vs `lockout_until`) either as an argument or a reset step before re-counting.
- In-window behavior is pinned by the facade guard: `lockout_remaining_seconds(lockout_until, now)` returns non-None while open and the identity row is `FOR UPDATE`-locked, so failures never reach the counter inside the window - keep that. The boundary is inclusive: at `now == lockout_until` the lockout has ended, so a failure at that instant starts a fresh streak.
- Keep it a counter: reset `lockout_failed_attempts` to 0 when the window lifts before re-counting; never write `status` or touch the `Suspended` path (`_reject_suspended` / operator-only, Phase 5).
- `test_failure_after_lockout_expired_relocks_immediately` currently documents the buggy behavior; flip it to assert a fresh streak (counter 1) and add the in-window counterpart (counter still grows while the window is open). The integration tests in `test_iam_resend_lockout.py` already prove success resets the counter and the window is 15 minutes.
