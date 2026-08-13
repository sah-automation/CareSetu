# Brief - T3 Register/login honours the resend cooldown & lockout

**Ticket:** #76 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~8K tokens (budget ~10K) - within budget

## Scope (verbatim)

The anti-spam contract holds on both entry paths. Entering a mobile number on the register endpoint is the single begin-or-resume entry; when the number is already registered, the login path now enforces the same resend cooldown and brute-force lockout as the resend endpoint - so an attacker cannot defeat the 60-second cooldown by calling register repeatedly, and a locked phone cannot be poked back into the OTP flow. When refused, no fresh challenge is issued and no SMS is sent; the PWA shows the matching countdown/refusal state instead of a new code.

Acceptance criteria:

- [ ] Registering an existing phone inside the 60s cooldown returns the actual remaining cooldown and issues no challenge and sends no SMS
- [ ] Registering an existing phone inside a lockout (or that is Suspended) is refused with the matching state, no SMS
- [ ] First-time registration and out-of-cooldown login behave exactly as before (challenge issued + SMS sent)
- [ ] The PWA renders the cooldown/locked refusal states from the register response (not only from verify/resend)
- [ ] Unit tests (facade + frontend state) cover the cooldown boundary, lockout, and suspended refusals on register

## Read-list (in order, token estimates)

1. Spec #51 §2.1 (unified begin-or-resume auth) + §2.4 (OTP challenge contract: latest-wins resend, >=60 s per-phone cooldown from last issuance, lockout counter, Suspended distinct) + §2.6 events, and the facade-frontend Testing Decisions seams (~1.5K).
2. ADR-0004 - the security contract: lockout enforced on verify and resend, never identity state; now must extend to the register login branch (~0.5K).
3. The facade result models `RegisterPatientResult`, `VerifyOtpResult`, `ResendOtpResult` - note `RegisterPatientResult` has no outcome/refusal fields today; `ResendOtpResult` carries the refused-state shape to mirror (~0.4K).
4. `IamFacade.register_patient` - the begin-or-resume entry: INSERT ON CONFLICT DO NOTHING, then unconditional challenge insert + `otp.sent` outbox + SMS; the gap is that the `is_existing` branch never consults cooldown/lockout (~1.2K).
5. `IamFacade.resend_otp` - the gate to mirror: `_lock_identity` row-lock, `_latest_cooldown_until`, `evaluate_resend` precedence (suspended > locked > cooldown > sent), refuse returns without challenge insert or SMS; the pure `evaluate_resend` decision in `domain/resend.py` and `lockout_remaining_seconds` in `domain/lockout.py` (~1.2K).
6. Identity row-lock and cooldown helpers: `_lock_identity_row` (FOR UPDATE returning id/status/lockout_failed_attempts/lockout_until), `_lock_identity`, `_latest_cooldown_until` (latest challenge's cooldown_until per identity), `_reject_suspended`/`_reject_locked` patterns (~0.8K).
7. HTTP adapter shapes: `routes.py` `/register`/`/verify`/`/resend` handlers and the request/response models they serialize (~0.7K).
8. PWA flow state: `otpState.ts` `submitPhone` (unconditional transition to otp stage, seeds cooldown/expiry from `RegisterResult`), `resendOtp` refusal handling (cooldown/locked/suspended -> countdown or spent + error strings) as the rendering pattern to reuse for register refusals, plus the `OtpState` fields and `api.ts` `RegisterResult`/`ResendResult` shapes (~1.5K).
9. `PatientAuthWizard.tsx` cooldown/lockout rendering: `OtpStep` disables resend + shows `t.resendIn`/`t.lockout` from `cooldownRemaining`/`lockoutRemaining`/`challenge === "locked"` (~0.5K).

## Do NOT read

- Session/refresh logic (`issue_session`, `refresh_session`, `_mint_session_row`, token rotation), dispatcher internals, gateway JWT/RBAC middleware, outbox writer internals, `docs/archive/`, `phase0/`.

## Baseline verify (from ticket; backend+frontend unit suites already verified green centrally: backend 494 passed on 2026-08-13)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`

## Done-verify (from ticket)

- `npm run test:unit:backend` (facade cooldown boundary, lockout, suspended refusals on register)
- `npm run test:unit:frontend` (PWA refusal states from the register response)
- `npm run typecheck`
- `npm run lint`

## Handoff notes (from parent #75 findings + ADR-0004 + register/login gap vs resend path)

- The gap is one-sided: `resend_otp` already refuses cooldown/locked/suspended with no challenge and no SMS, but `register_patient` issues a challenge and sends SMS unconditionally on the login branch - exactly the hole the attacker exploits to defeat the 60s cooldown and to re-arm a locked phone. Mirror the resend gate, do not invent a new one.
- Precedence must match `evaluate_resend`: Suspended beats the counters, lockout beats cooldown, cooldown measured from the latest challenge's `cooldown_until` per identity (`_latest_cooldown_until`), resend exactly at `cooldown_until` allowed. Never create the OTP challenge (no `otp.sent`, no row) and never call the EXT-001 SMS adapter when refused.
- Refusal response shape: `RegisterPatientResult` has no outcome field today, so a refusal needs a discriminated shape (e.g. add outcome/`cooldown_remaining_seconds`/`lockout_remaining_seconds` alongside the existing fields, mirroring `ResendOtpResult` but with `no_identity` impossible on this path) - it is the single begin-or-resume entry, so first-time registration must still return the full register shape.
- Result-shape naming and the `suspended`/`locked` strings in `RegisterResult` must be updated in `api.ts` in lockstep with the facade model so `useOtpFlow` can branch; `submitPhone` currently only reads `is_existing`/`attempts_left`/`cooldown_remaining_seconds`/`expires_in_seconds` and transitions to the otp stage unconditionally - it must now render refusal (cooldown stays on the phone step with the matching countdown/`lockout` message; locked sets `challenge: "locked"`, suspended shows `t.suspendedNotice`).
- ADR-0004 §4 says lockout is enforced on `verify_otp` and `resend_otp`; extending it to the register login branch is the remediation and does not change the decision, only its coverage. Lockout remains a counter, never identity state; `Suspended` stays operator-only.
- First-time registration and out-of-cooldown login must be byte-identical to today (challenge issued, `otp.sent`, SMS sent, full challenge fields) so the regression is confined to the refusal branch.
