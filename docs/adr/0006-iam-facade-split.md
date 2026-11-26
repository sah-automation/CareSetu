# ADR-0006: Split the IAM facade into identity, OTP, and session sub-facades

**Status:** accepted
**Date:** 2026-08-19
**Decides:** Internal structure of the MOD-001 facade as it grows beyond a single class.
**Traceability:** `internal-modules.md` §3.1, `coding-standards.md` §2, architecture review 2026-08-19.

## Context

The `IamFacade` class in `modules/iam/facade.py` has grown to 1,159 lines with 7 public methods and 15 private helpers. It handles registration, OTP challenge lifecycle, lockout evaluation, session JWT issuance, token validation, refresh rotation, and access-denial audit. The interface is growing with each phase. Tests must construct the full facade with all its dependencies to exercise any one concern. The deletion test passes (complexity reappears across routes), but the facade's breadth means no single test exercises one concern in isolation.

## Decision

1. **Three sub-facades behind a thin coordinator.** `IdentityFacade` (register, resolve, lockout), `OtpFacade` (issue, verify, resend), `SessionFacade` (mint, validate, refresh). The top-level `IamFacade` becomes a ~50-line coordinator that delegates.

2. **Same public surface.** `IamFacade` keeps its current constructor signature and method names. Routes, `app.main`, and existing tests need zero changes. The split is purely internal.

3. **Result models live with their sub-facade.** `RegisterPatientResult` with `IdentityFacade`, `VerifyOtpResult`/`ResendOtpResult` with `OtpFacade`, `SessionResult`/`ValidatedAccessToken` with `SessionFacade`. The coordinator re-exports them so the import path `from modules.iam.facade import ...` is unchanged.

4. **Shared internals in `domain/shared.py`.** `IdentityGuardState`, `_lock_identity_row`, `_invalidate_pending_challenges`, and `_issue_challenge` live in a shared internal module. Both `IdentityFacade` and `OtpFacade` import from it. This avoids circular imports between sub-facades.

5. **SMS delivery owned by coordinator.** The `SmsDeliveryQueue` stays on the coordinator. Sub-facades receive a simple `OtpSender = Callable[[str, str], Awaitable[None]]` port. They never touch adapter types. The `_emit_delivery_failed` callback stays on the coordinator.

6. **`emit_access_denied` stays on the coordinator.** It bridges session context and outbox writes, both coordinator concerns. No delegation needed.

7. **Domain files stay as-is.** The split is at the facade layer only. Domain files (`otp.py`, `verify.py`, `lockout.py`, etc.) are already well-factored by concern.

8. **Incremental implementation.** `SessionFacade` first (simplest, no SMS, no shared lockout), then `OtpFacade` (needs `OtpSender` port and `domain/shared.py`), then `IdentityFacade` (most complex, uses shared helpers most heavily).

## Considered options

- **Single facade with more methods:** rejected - the facade is already 1,159 lines and growing with each phase; adding more responsibility without splitting makes it untestable in isolation.
- **Flatten to sub-facades with no coordinator:** rejected - routes would need to know which sub-facade to call, `app.main` would store three objects, and every test changes.
- **Reorganize domain files into subdirectories:** rejected - domain files are already deep modules; reorganizing them adds churn without leverage.

## Consequences

- Each sub-facade is independently testable with fewer mocks. OTP tests never construct a JWT; session tests never touch the SMS adapter.
- The coordinator is a thin delegation layer that can be tested with a simple mock.
- Adding a new method to one concern (e.g., a new OTP operation) only touches one sub-facade.
- The `domain/shared.py` module is internal (not part of the public facade surface) and carries the shared SQL helpers that both identity and OTP operations need.
- The `OtpSender` port in the coordinator already shields sub-facades from the SMS adapter, partially achieving the dependency inversion from Candidate 3 of the architecture review. Full SMS protocol inversion (moving `SmsAdapter` to `domain/ports.py`) is deferred.
