# Brief - REFAC-3 Extract OtpFacade from IAM facade

**Ticket:** #168 · **Parent:** ADR-0006 · **Refreshed:** 2026-08-19
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Extract an `OtpFacade` class from the current `IamFacade`. The new sub-facade owns `verify_otp`, `resend_otp` and their result models (`VerifyOtpResult`, `ResendOtpResult`). Uses `OtpSender` port (from REFAC-2) instead of adapter types. Imports shared helpers from `domain/shared.py`. The coordinator delegates to it.

Acceptance criteria:

- `modules/iam/otp_facade.py` exists with `OtpFacade` class
- `OtpFacade` has methods: `verify_otp`, `resend_otp`
- `VerifyOtpResult` and `ResendOtpResult` moved to `otp_facade.py`
- `OtpFacade` accepts `OtpSender` port in constructor, not `SmsAdapter`
- `OtpFacade` imports lockout/challenge helpers from `domain/shared.py`
- `IamFacade` delegates OTP methods to `OtpFacade`
- `IamFacade` re-exports `VerifyOtpResult` and `ResendOtpResult` (backward compat)
- All unit tests pass
- Typecheck clean
- Boundary checker passes

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the ADR governing this refactoring (~1.5K tokens)
2. `modules/iam/facade.py` lines 106-142 - `VerifyOtpResult` and `ResendOtpResult` models (~0.4K tokens)
3. `modules/iam/facade.py` lines 350-680 - `verify_otp` and `resend_otp` methods (~2.5K tokens)
4. `modules/iam/domain/shared.py` (from REFAC-2) - `_lock_identity`, `_invalidate_pending_challenges`, `_issue_challenge`, `IdentityGuardState` (~0.6K tokens)
5. `modules/iam/domain/verify.py` - `evaluate_attempt`, `failure_write_back`, `CHALLENGE_*` constants (~0.5K tokens)
6. `modules/iam/domain/resend.py` - `evaluate_resend` (~0.3K tokens)
7. `modules/iam/domain/otp.py` - `MAX_ATTEMPTS`, `OTP_TTL_SECONDS`, `RESEND_COOLDOWN_SECONDS`, `generate_otp`, `hash_otp` (~0.4K tokens)
8. `modules/iam/domain/lockout.py` - `evaluate_failure`, `lockout_remaining_seconds` (~0.3K tokens)
9. `modules/iam/domain/events.py` - `patient_verified_envelope`, `otp_sent_envelope`, `otp_failed_envelope`, `patient_auth_failed_envelope` (~0.5K tokens)
10. `modules/iam/schema/models.py` - `iam_identities`, `iam_otp_challenges` tables (~0.5K tokens)
11. `modules/iam/outbox.py` - `IAM_OUTBOX_TABLE` (~0.1K tokens)
12. `modules/iam/adapters/routes.py` lines 39-45 - current imports (backward compat surface) (~0.2K tokens)

Total: ~7.8K tokens

## Do NOT read

- `modules/iam/domain/jwt.py`, `domain/refresh.py` - not touched
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
- `wc -l apps/backend/modules/iam/otp_facade.py` (new file exists)
- `wc -l apps/backend/modules/iam/facade.py` (reduced further)

## Handoff notes

- REFAC-1 and REFAC-2 must be complete first.
- After REFAC-1, `SessionFacade` exists and the coordinator delegates session methods.
- After REFAC-2, `domain/shared.py` has `IdentityGuardState`, `_lock_identity_row`, `_invalidate_pending_challenges`, `_issue_challenge`. The `OtpSender` port is defined.
- `OtpFacade` takes `engine`, `clock`, `otp_sender: OtpSender` in its constructor. No `sms_adapter`.
- `verify_otp` uses: `_lock_identity` (from shared), `evaluate_attempt` (from domain/verify), `failure_write_back` (from domain/verify), `_grant_patient_role` (from facade - this is a small helper, consider keeping it in facade or moving to shared), `issue_session` (delegates to SessionFacade via coordinator), events (from domain/events), outbox write.
- `resend_otp` uses: `_lock_identity` (from shared), `evaluate_resend` (from domain/resend), `_invalidate_pending_challenges` (from shared), `_issue_challenge` (from shared), `evaluate_failure` (from domain/lockout), `lockout_remaining_seconds` (from domain/lockout), events, outbox write, `otp_sender`.
- The coordinator creates `OtpFacade` in its `__init__` and delegates `verify_otp` and `resend_otp`.
- `_grant_patient_role` is a small static helper (inserts into `iam_role_grants`). It's used by `verify_otp`. Move it to `domain/shared.py` or keep it in `otp_facade.py` - either works since it's a single INSERT.
