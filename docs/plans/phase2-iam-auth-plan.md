# Phase 2 Plan: Patient Identity & Phone-OTP Auth (PHASE-2-IAM-AUTH)

**Status:** ready for `/to-spec`
**Source:** `grill-with-docs` session (grilling + domain-modeling) on `docs/roadmap/implementation-roadmap.md` §2.2, `docs/architecture/internal-modules.md` MOD-001, `docs/prd/project-prd.md` FEAT-001, `docs/architecture/system-context.md` ACT-001/EXT-001, ADR-0002, ADR-0003.
**Upstream targets:** roadmap §2.2 (release readiness criteria), PRD FEAT-001, MOD-001 spec.

## 1. Goal

Deliver the patient identity core (`FEAT-001`): phone-OTP registration with duplicate resolution, session JWT issuance/validation, RBAC scope at the edge - so every later phase has a trustworthy caller identity. E2E loop: register → OTP (mocked SMS) → verify → authenticated session → protected route.

## 2. Resolved decisions

### 2.1 Unified begin-or-resume auth

`register_patient(phone)` is a single entry point that branches on identity existence:

- Phone not seen: create `[Unverified]` identity + send OTP (registration).
- Phone exists: auth trigger, OTP issued against the existing identity (login).

`patient.registered` fires only on first creation; `patient.verified` fires on every successful OTP. Matches FEAT-001 Scenario 2 and the single phone-entry PWA screen; no separate login route exists in the scope boundary.

### 2.2 Phone normalization (+91-only at launch)

- Server-side E.164 normalization to `+91XXXXXXXXXX`; anything else rejected at the gateway with a clear validation error.
- Country code derived from the normalized number, never trusted from the client.
- Launch scope bound to India (`ISSUE-004` expansion deferred); stored as `phone_e164` unique.

### 2.3 Duplicate resolution under concurrency

- The unique index on `phone_e164` is the source of truth.
- Second writer: `INSERT ... ON CONFLICT (phone_e164) DO NOTHING`, then re-read and resolve to the winner; still sends the OTP against the existing identity.
- No SELECT-then-INSERT guard, no advisory locks. Concurrent registrations always converge to exactly one identity.

### 2.4 OTP challenge contract

- Single-use; 5-min TTL; hashed at rest, never logged.
- 5-attempt budget per challenge; wrong guesses decrement the budget but do not kill the OTP; challenge `spent` at 0 → "request a new code".
- Latest-wins resend: a resend invalidates the pending challenge and issues a fresh one.
- Resend cooldown ≥ 60 s per phone, measured from last issuance.
- Brute-force: 10 consecutive failures across challenges → 15-min temporary phone lockout (a counter, never an identity state).
- `Suspended` is an identity status reachable only via `set_actor_status` (operator, Phase 5); the lockout and `Suspended` are distinct.

### 2.5 Sessions

- Access JWT ~15-min TTL carrying `jti`, expiry, scope claim.
- Opaque refresh token, server-side in `iam.sessions`, ~30-day sliding, rotated on every refresh.
- Refresh path independent of SMS (`NFR-004`).

### 2.6 Events (Phase 2 emits; MOD-011 consumes in Phase 4 per ADR-0002)

- Published into `iam_outbox` in the same transaction as the state change: `patient.registered`, `patient.verified`, `patient.auth_failed`, `otp.sent`, `otp.failed`.
- Event names follow the registry in `internal-modules.md` §4.2 (dot-notation). The PRD's legacy snake_case telemetry names are superseded - registry is canonical.

## 3. Scope boundary (API surface)

Backend: `register_patient(phone)`, `verify_otp(phone, otp)`, `resend_otp(phone)`, `issue_session`, `refresh_session`, `validate_token(jwt) → scope` + RBAC scope resolver. SMS via `EXT-001` adapter (mock in CI). Nothing about records/consent (Phase 3).

Data (migration `v1.0__init_iam.sql`): `identities` (phone_e164 unique, status Unverified/Active/Suspended), `otp_challenges` (hashed, single-use, TTL 5 min, cooldown), `sessions` (jti, expiry, scope), `role_grants` (patient role), `iam_outbox`.

Frontend: Variant B (stepped wizard) is the chosen flow - fold it into the real patient auth routes (Phone → Verify → Done, countdown ring, resend cooldown, attempts-left, lockout state, hi/en toggle). Variants A and C eliminated.

## 4. Prototype consolidation (done)

- Deleted `variantA.tsx`, `variantA.module.css`, `variantC.tsx`, `variantC.module.css`.
- `OtpPrototype.tsx` renders Variant B only; `page.tsx` drops variant plumbing; `otpState.ts`/`shared.tsx` comments updated to resolved decisions.
- Verified: frontend unit tests pass, `tsc --noEmit` clean, eslint clean, pre-commit hooks pass.

## 5. Doc deltas (part of this spec)

- **CONTEXT.md glossary additions:** `identity` (one per phone, never duplicated), `OTP challenge` (single-use, 5-min TTL, latest-wins resend), `phone lockout` (15-min temporary counter, distinct from `Suspended`), `duplicate resolution` (unique constraint as arbiter), `E.164 phone` (+91 launch scope), plus `_Avoid_` note for legacy snake_case event names.
- **New ADR-0004 - "OTP challenge & brute-force contract".** Hard to reverse (security posture later phases inherit); surprising without context (latest-wins resend, lockout ≠ Suspended); real trade-off (temporary lockout vs identity suspension vs backoff, bounded by SMS cost `NFR-001`).
- **`internal-modules.md` MOD-001 §1/§2/§3:** add lockout counters, latest-wins resend, 5-attempt budget, +91 normalization, session TTLs, event list.

## 6. Release readiness criteria (from roadmap §2.2)

E2E register → OTP (mocked SMS) → verify → authenticated session → protected route; duplicate re-registration resolves to existing identity; OTP single-use, 5-min TTL, ≥ 60 s resend cooldown; `validate_token` p95 < 100 ms; `patient.auth_failed` and access-denial attempts emitted as audit events.

## 7. Out of scope

- Partner credentials/operator MFA (Phase 5).
- Stronger-than-OTP identity (`GAP-001` kept open, OTP baseline).
- Record/consent behavior (Phase 3).
- `iam` schema is owned by MOD-001 only (ADR-0003); no cross-schema reads.
