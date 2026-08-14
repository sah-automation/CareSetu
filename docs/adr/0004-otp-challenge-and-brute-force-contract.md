# ADR-0004: OTP challenge & brute-force contract

**Status:** accepted
**Date:** 2026-08-13
**Decides:** The security posture for phone-OTP verification and the brute-force defense around it - single-use challenges, TTL and attempt budget, latest-wins resend, cooldown, and temporary lockout.
**Traceability:** `FEAT-001`, `NFR-SEC-002`, `NFR-SEC-004`, `EXT-001`, `MOD-001` §3.1, `GAP-001` (baseline), `PHASE-2-IAM-AUTH` (issue #51).

## Context

Patient identity on CareSetu rests on phone-OTP verification (`GAP-001` baseline, `FEAT-001`). A phone number is a weak authenticator: codes transit SMS, can be guessed, and a shared family phone can be spammed with resends. Every downstream phase and the audit trail (MOD-011) depend on one settled contract for how a code is issued, spent, and defended. Without it, brute-force attacks and replays erode the identity foundation the whole platform trusts.

## Decision

1. **Single-use, short-lived, hashed.** An OTP is a single-use 6-digit code valid for 5 minutes, hashed at rest, and never logged. A code verifies once and is spent forever; an expired or spent code can never verify an identity.
2. **5-attempt budget per challenge.** Each challenge carries a 5-attempt budget. A wrong guess decrements the budget but does not kill the code, so a typo does not force a re-issue; the challenge is spent when the budget reaches 0, with a "request a new code" response. A fresh challenge resets the budget.
3. **Latest-wins resend with cooldown.** Resending invalidates the pending challenge and issues a fresh one (latest-wins). The resend cooldown is at least 60 seconds per phone measured from the last issuance, so a shared family phone cannot spam itself.
4. **Lockout is a counter, never identity state.** Ten consecutive verification failures across challenges trigger a 15-minute temporary phone lockout, implemented as the `lockout_failed_attempts` + `lockout_until` counter columns on `iam_identities` - never as the identity lifecycle status - enforced on `verify_otp`, `resend_otp`, and the existing-phone login branch of `register_patient` (PHASE-2 REM T3, so a locked phone cannot be poked back into the OTP flow through the begin-or-resume entry). The counter resets on a successful verification or on the next failure once the window has fully elapsed, so a failure after the lockout lifts starts a fresh streak rather than re-locking. **The streak counts SMS-cost failures only (PHASE-2 REM FIX 2, #102):** only attempts against a challenge that was actually issued - `wrong_code`, `spent`, `expired`, `replay` - increment it, because only they incurred an SMS cost. `no_challenge`, `suspended`, and `locked` rejections never touch the counter: a `no_challenge` verify had no SMS sent for it, and the `suspended` and `locked` guards are not attempts. This is structural, not incidental - every wrong-guess failure flows through `_record_failed_attempt` while the no-counter rejections route through `_reject`. Inside the window a locked phone is refused outright by the `verify_otp` `FOR UPDATE` guard, so the lockout never extends from an in-window attempt: the counter cannot grow and `lockout_until` is never pushed out, keeping the lockout genuinely temporary.
5. **Lockout is distinct from suspension.** The `Suspended` identity status is reachable only via the operator status change interface (Phase 5); the temporary lockout never collapses into it.
6. **Auth events flow through the outbox.** Every challenge outcome publishes into the module outbox in the same transaction (ADR-0002): `patient.registered` (first creation only), `patient.verified` (every success), `patient.auth_failed`, `otp.sent`, `otp.failed`. Separately from challenge outcomes, a refusal on a protected route with an authenticated caller (403, insufficient scope or missing role) publishes `patient.auth_failed` (reason `access_denied`) in its own transaction so the denial is auditable; anonymous denials (401) have no identity to attribute and stay log-only - a documented boundary (PHASE-2 REM T7 #87).

## Considered options

- **No attempt budget, delay between tries:** rejected - delays are bypassable through parallel requests and offer no durable audit signal.
- **Kill-on-first-error:** rejected - a typo would force a full re-issue and punish legitimate users.
- **Lockout as identity status:** rejected - collapses the temporary counter into the `Suspended` lifecycle and forces operator intervention for what is an automatic, time-boxed defense.
- **Longer OTP TTL:** rejected - a 5-minute window bounds the replay risk of a code that transits SMS.
- **Redis-only counters:** considered - SQL counters are the fallback so the contract holds without Redis, matching `MOD-001` §3.1.

## Consequences

- OTP and auth endpoints are rate-limited at the gateway (`NFR-SEC-004`) on top of the per-phone contract.
- Every challenge state change is auditable through the outbox events consumed by `MOD-011` (Phase 4).
- The lockout is temporary and automatic; the patient retries after 15 minutes without operator help, and the UI tells them how many attempts remain.
- The contract is the reference behaviour for the EXT-001 mock in CI and for the frontend auth wizard's `useOtpFlow`.
