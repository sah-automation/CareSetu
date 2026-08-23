# Brief - REFAC-1 Extract SessionFacade from IAM facade

**Ticket:** #166 · **Parent:** ADR-0006 · **Refreshed:** 2026-08-19
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Extract a `SessionFacade` class from the current `IamFacade` (1,159 lines). The new sub-facade owns `issue_session`, `validate_token`, `refresh_session` and their result models (`SessionResult`, `ValidatedAccessToken`). The coordinator `IamFacade` delegates to it. All existing tests pass unchanged.

Acceptance criteria:

- `modules/iam/session_facade.py` exists with `SessionFacade` class
- `SessionFacade` has methods: `issue_session`, `validate_token`, `refresh_session`
- `SessionResult` and `ValidatedAccessToken` moved to `session_facade.py`
- `IamFacade` delegates session methods to `SessionFacade`
- `IamFacade` re-exports `SessionResult` and `ValidatedAccessToken` (backward compat)
- All unit tests pass
- Typecheck clean
- Boundary checker passes

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the ADR governing this refactoring (~1.5K tokens)
2. `modules/iam/facade.py` lines 143-175 - `SessionResult` and `ValidatedAccessToken` models (~0.3K tokens)
3. `modules/iam/facade.py` lines 715-890 - `issue_session`, `validate_token`, `refresh_session` methods (~1.8K tokens)
4. `modules/iam/facade.py` lines 235-252 - `IamFacade.__init__` constructor (engine, sms_adapter, clock, signing keys) (~0.3K tokens)
5. `modules/iam/domain/jwt.py` - `issue_token`, `verify_token`, `ACCESS_TOKEN_TTL_SECONDS` (~1K tokens)
6. `modules/iam/domain/refresh.py` - `generate_refresh_token`, `verify_refresh_token`, `REFRESH_TOKEN_TTL_SECONDS` (~0.8K tokens)
7. `modules/iam/schema/models.py` - `iam_sessions`, `iam_role_grants` tables (~0.5K tokens)
8. `modules/iam/domain/exceptions.py` - `SessionIssuanceError`, `RefreshTokenExpiredError`, `RefreshTokenRevokedError`, `RefreshTokenUnknownError`, `AccessTokenExpiredError`, `AccessTokenMalformedError`, `AccessTokenSignatureError` (~0.5K tokens)
9. `modules/iam/adapters/routes.py` lines 39-45 - current imports from facade (backward compat surface) (~0.2K tokens)

Total: ~6.9K tokens

## Do NOT read

- `modules/iam/adapters/sms.py` - not touched by this ticket
- `modules/iam/domain/otp.py`, `domain/lockout.py`, `domain/verify.py`, `domain/resend.py` - not touched
- `app/main.py` - not touched (coordinator constructor stays identical)
- Any test files (run them for verification only)
- Other modules, frontend

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (654 passed)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all 654 pass)
- `npm run typecheck` (clean)
- `npm run lint` (boundary checker passes)
- `wc -l apps/backend/modules/iam/session_facade.py` (new file exists)
- `wc -l apps/backend/modules/iam/facade.py` (reduced from 1159)

## Handoff notes

- This is the first ticket in the REFAC chain. No prior handoffs.
- The `SessionFacade` takes `engine`, `clock`, `access_token_signing_key`, `access_token_ttl_seconds`, `refresh_token_ttl_seconds` in its constructor. It does NOT take `sms_adapter` - session logic has no SMS dependency.
- The coordinator `IamFacade` keeps its existing constructor signature. Internally it creates `SessionFacade` and delegates `issue_session`, `validate_token`, `refresh_session` to it.
- `IdentityGuardState` and `_lock_identity_row` stay in `facade.py` for now - they move to `domain/shared.py` in REFAC-2.
- The `_lock_identity_by_id` helper is used by `refresh_session` (line ~800). It needs to move to `SessionFacade` or be accessible from it. Since `_lock_identity_by_id` is also used by `emit_access_denied` (stays on coordinator), the simplest approach is to keep it as a module-level function in `facade.py` that both the coordinator and `SessionFacade` import.
