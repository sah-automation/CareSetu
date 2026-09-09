# Brief - 01 Add InvalidOperatorCodeError exception and route handler

**Ticket:** #295 . **Parent:** #294 . **Refreshed:** 2026-09-04
**Reading surface:** ~0.6K tokens (budget 10K) - within budget

## Scope

When an operator submits a wrong TOTP code, the backend returns HTTP 401 with error code `INVALID_OPERATOR_CODE` instead of `SESSION_MFA_REQUIRED`. The existing `SESSION_MFA_REQUIRED` path is preserved for MFA enrollment missing.

Currently `session_facade.py` raises `OperatorMfaError` for three distinct cases: MFA not enrolled, no TOTP secret, and wrong TOTP code. The route handler maps all of them to `SESSION_MFA_REQUIRED`. This ticket separates the wrong-code case into its own exception and error code.

### Acceptance criteria

- [ ] `POST /v1/auth/operator/login` with wrong TOTP returns `{"code": "INVALID_OPERATOR_CODE"}` (not `SESSION_MFA_REQUIRED`)
- [ ] `POST /v1/auth/operator/login` with missing MFA enrollment still returns `{"code": "SESSION_MFA_REQUIRED"}`
- [ ] `npm run test:unit:backend` passes
- [ ] `npm run lint` and `npm run typecheck` pass

## Read-list (in order)

1. `apps/backend/modules/iam/domain/exceptions.py` - existing exception hierarchy; add `InvalidOperatorCodeError(IamError)` after `OperatorMfaError` (~115 lines, focus on line 50-60 pattern)
2. `apps/backend/modules/iam/session_facade.py` - lines 240-246: change the TOTP verification `except` block to raise the new exception instead of `OperatorMfaError`; add import at top
3. `apps/backend/modules/iam/adapters/routes.py` - lines 32-41 (imports), 418-425 (handler pattern from `_operator_mfa_failed`), 483-491 (handler registration order)

## Do NOT read

- Frontend files (`apps/frontend/`)
- Unrelated backend modules
- Archives (`docs/archive/`)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run lint`
- `npm run typecheck`

## Done-verify (acceptance criteria mapped to commands)

- `npm run test:unit:backend` - existing tests still pass
- `npm run lint` - no lint violations
- `npm run typecheck` - mypy strict passes
- Manual: wrong TOTP returns `INVALID_OPERATOR_CODE`, missing enrollment returns `SESSION_MFA_REQUIRED`

## Handoff notes

- `OperatorMfaError` inherits from `SessionIssuanceError` (not directly from `IamError`). The new `InvalidOperatorCodeError` should inherit from `IamError` directly - it is an auth failure, not a session issuance refusal.
- The route handler `_operator_mfa_failed` passes `str(exc)` as the user-facing message (line 422). The new handler should use a hardcoded safe message, not the raw exception text.
- Handler registration order matters: the new handler must be registered before the catch-all `IamError` handler (line 490). Starlette picks the most specific match, but registering earlier is defensive.
- The `SESSION_MFA_REQUIRED` code is still needed for the MFA-not-enrolled case (lines 214-218 and 235-239 of `session_facade.py`). Do not remove it.
