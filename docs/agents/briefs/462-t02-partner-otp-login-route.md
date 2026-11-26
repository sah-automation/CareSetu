# Brief - 462 F014-T02 Backend: partner OTP login route (POST /v1/auth/partner/login)

**Ticket:** #462 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~8.5K tokens (budget 10K) - within budget

## Scope

A returning partner starts login: they enter their phone on the staff login page and get an SMS one-time code. The backend route `POST /v1/auth/partner/login` issues the challenge **only** for a phone that already has a partner profile (doctor/lab/chemist). A phone with no partner account - including a patient-only phone - gets a polite refusal pointing to registration, and **no identity is ever created** by this route. Cooldown, lockout and suspended refusals behave exactly like the patient OTP surface, and the live demo read-back shows the code so the loop is testable without a real SMS provider.

Acceptance criteria (verbatim from ticket):

- [ ] `POST /v1/auth/partner/login` with a phone that has a partner profile issues a fresh OTP challenge through the existing OTP machine: latest-wins resend semantics, ≥60 s cooldown, 5-attempt budget, 5-minute TTL, hashed at rest, never logged, `otp.sent` (not a new event name).
- [ ] The same route with no partner profile for the phone (including an existing patient-only phone) refuses with a clear "no account - register as a doctor/lab/chemist" outcome, without creating an identity and without sending an SMS.
- [ ] Cooldown / brute-force lockout / suspended refusals are honored exactly as on the patient surface: `cooldown`, `locked` (with countdown), `suspended`, and the phone lockout counter rules of ADR-0004 (SMS-cost failures only).
- [ ] Phone normalization to E.164 is server-side with the country code never trusted from the client.
- [ ] Route-seam tests cover: sent, no-account refusal (no identity row created), cooldown, locked, suspended.
- [ ] The demo read-back `GET /v1/auth/dev/otp?phone=...` returns the partner challenge code in dev/test/demo, matching the patient surface.

**Blocked by:** None - can start immediately.

## Read-list (in order)

1. The iam auth router `apps/backend/modules/iam/adapters/routes.py` (prefix `/v1/auth`, `APIRouter`) - the existing `register_patient` (issues OTP), `resend_otp`, `issue_partner_session` routes, the request-model/error-handler style, and the `run_idempotent` mutation wrapper every route uses. This is where the new `/partner/login` route is added. (~3K slices; ~5.8K full file)
2. The OTP issuance primitives in `apps/backend/modules/iam/domain/shared.py`: `_issue_challenge` (writes hashed OTP + `otp.sent` in the same transaction), `_reissue_otp_challenge` (latest-wins resend), `_lock_identity_row` (FOR UPDATE), `_latest_cooldown_until`; and the constants in `apps/backend/modules/iam/domain/otp.py` (`OTP_LENGTH=6`, `OTP_TTL_SECONDS=300`, `RESEND_COOLDOWN_SECONDS=60`, `MAX_ATTEMPTS=5`) + `domain/lockout.py` (`LOCKOUT_THRESHOLD=10`, `LOCKOUT_SECONDS=900`). (~2.5K)
3. The composition seam `apps/backend/modules/partner/registration_facade.py`: `resolve_partner_id_by_identity(identity_id) -> int | None` (non-throwing) - the "does a partner profile exist for this phone" answer that gates the route, read at the module boundary (iam never imports the partner schema). (~0.5K)
4. `apps/backend/modules/iam/otp_facade.py` `resend_otp`/`verify_otp` slices - the behavioral reference for cooldown/lockout/suspended refusal shapes to mirror (NOT the patient side effects). (~1.5K)
5. Route-seam test style: `tests/unit/test_iam_resend_route.py`, `test_iam_register_route.py`, `test_iam_verify_route.py` - stubbed-facade (`app.state.iam_facade`) + `fastapi.testclient.TestClient` pattern to extend. Also `tests/unit/test_iam_lockout.py` for the lockout decision surface. (~2K)
6. The dev read-back `GET /v1/auth/dev/otp` in `apps/backend/app/main.py` + `MockSmsAdapter` (`modules/iam/adapters/sms.py`) - confirm a partner challenge flows through the same mock read-back (likely no change needed; verify). (~0.3K)

## Do NOT read

- Partner credential / verification internals (prefilter, rejection, rounds), operator MFA/TOTP, frontend code, `docs/archive/`, any module beyond the iam route/facade/domain slices named above.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (2184 passed on 2026-09-17), `npm run lint`, `npm run typecheck`, `npm run migration-check` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new route tests for `/v1/auth/partner/login` cover sent / no-account-refusal / cooldown / locked / suspended, and assert no identity is created on refusal.
- `npm run lint`, `npm run typecheck`, `npm run migration-check` green (no schema change in this ticket).
- No new event name: `grep otp.` on the new code shows only `otp.sent`.

## Handoff notes

- Naming drift vs the parent spec: the OTP constants are `OTP_TTL_SECONDS`/`RESEND_COOLDOWN_SECONDS`/`MAX_ATTEMPTS` (not `TTL`/`COOLDOWN`); the lockout config is `LOCKOUT_THRESHOLD`/`LOCKOUT_SECONDS`; there is no `SMS_COST` constant - the "SMS-cost failures only" lockout rule is structural (see `otp_facade` comments near `_record_failure`/`_record_failed_attempt`).
- Event envelope reuse: `otp_sent_envelope` in `apps/backend/modules/iam/domain/events.py`. Never invent a new event name (the legacy snake_case event-name gate is part of lint).
- Module isolation (ADR-0003 / READ the module-boundary lint gate): the route resolves partner existence ONLY via `resolve_partner_id_by_identity`, never by SQL or import into the partner schema.
- The "no account" refusal must not create an identity and must not send SMS - it is a pure `no_account` outcome envelope, not a registration.
- The demo read-back AC should already pass without code (MockSmsAdapter is phone-keyed); if a test proves otherwise, fix, but do not build a new adapter.
- This ticket creates no database column; the phone-verified marker arrives in #463.
