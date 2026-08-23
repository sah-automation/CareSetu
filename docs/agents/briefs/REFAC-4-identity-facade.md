# Brief - REFAC-4 Extract IdentityFacade from IAM facade

**Ticket:** #169 · **Parent:** ADR-0006 · **Refreshed:** 2026-08-19
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Extract an `IdentityFacade` class from the current `IamFacade`. The new sub-facade owns `register_patient` and its result model (`RegisterPatientResult`). Uses `OtpSender` port for SMS delivery. Imports shared helpers from `domain/shared.py`. After this, `IamFacade` is a thin ~50-line coordinator that delegates to all three sub-facades.

Acceptance criteria:

- `modules/iam/identity_facade.py` exists with `IdentityFacade` class
- `IdentityFacade` has method: `register_patient`
- `RegisterPatientResult` moved to `identity_facade.py`
- `IdentityFacade` accepts `OtpSender` port in constructor
- `IdentityFacade` imports lockout/challenge helpers from `domain/shared.py`
- `IamFacade` delegates `register_patient` to `IdentityFacade`
- `IamFacade` re-exports `RegisterPatientResult` (backward compat)
- `IamFacade` is now a thin coordinator (~50 lines) with: constructor, `emit_access_denied`, and delegation methods
- All unit tests pass
- Typecheck clean
- Boundary checker passes

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the ADR governing this refactoring (~1.5K tokens)
2. `modules/iam/facade.py` lines 81-105 - `RegisterPatientResult` model (~0.3K tokens)
3. `modules/iam/facade.py` lines 254-348 - `register_patient` method (~1K tokens)
4. `modules/iam/domain/shared.py` (from REFAC-2) - `_lock_identity`, `_invalidate_pending_challenges`, `_issue_challenge`, `IdentityGuardState` (~0.6K tokens)
5. `modules/iam/domain/phone.py` - `normalize_phone` (~0.2K tokens)
6. `modules/iam/domain/lockout.py` - `evaluate_failure`, `lockout_remaining_seconds` (~0.3K tokens)
7. `modules/iam/domain/otp.py` - `MAX_ATTEMPTS`, `OTP_TTL_SECONDS`, `RESEND_COOLDOWN_SECONDS`, `generate_otp`, `hash_otp` (~0.4K tokens)
8. `modules/iam/domain/resend.py` - `evaluate_resend` (~0.3K tokens)
9. `modules/iam/domain/events.py` - `patient_registered_envelope`, `otp_sent_envelope` (~0.3K tokens)
10. `modules/iam/schema/models.py` - `iam_identities` table (~0.3K tokens)
11. `modules/iam/outbox.py` - `IAM_OUTBOX_TABLE` (~0.1K tokens)
12. `modules/iam/facade.py` current state after REFAC-3 - the coordinator shell (~0.5K tokens)
13. `modules/iam/adapters/routes.py` lines 39-45 - current imports (backward compat surface) (~0.2K tokens)

Total: ~6.0K tokens

## Do NOT read

- `modules/iam/domain/jwt.py`, `domain/refresh.py` - not touched
- `modules/iam/domain/verify.py` - not touched (OTP logic is in otp_facade)
- `modules/iam/adapters/sms.py` - not touched (OtpSender port is the interface)
- `app/main.py` - not touched
- Any test files (run them for verification only)
- Other modules, frontend

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (654 passed)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all 654 pass)
- `npm run typecheck` (clean)
- `npm run lint` (boundary checker passes)
- `wc -l apps/backend/modules/iam/identity_facade.py` (new file exists)
- `wc -l apps/backend/modules/iam/facade.py` (~50 lines or less)

## Handoff notes

- REFAC-1, REFAC-2, and REFAC-3 must be complete first.
- After REFAC-1, `SessionFacade` exists in `session_facade.py`.
- After REFAC-2, `domain/shared.py` has shared helpers and `OtpSender` port.
- After REFAC-3, `OtpFacade` exists in `otp_facade.py` with `verify_otp` and `resend_otp`.
- `IdentityFacade` takes `engine`, `clock`, `otp_sender: OtpSender` in its constructor.
- `register_patient` uses: `normalize_phone` (from domain/phone), `_lock_identity` (from shared), `evaluate_resend` (from domain/resend), `_invalidate_pending_challenges` (from shared), `_issue_challenge` (from shared), `evaluate_failure` (from domain/lockout), events, outbox write, `otp_sender`.
- After this ticket, `facade.py` is a thin coordinator: constructor creates all three sub-facades, `emit_access_denied` stays directly, and 7 delegation methods forward to sub-facades. Re-export all result models.
- The coordinator's `__init__` signature must remain identical to today's `IamFacade.__init__` for backward compatibility with `app/main.py` and all tests.
