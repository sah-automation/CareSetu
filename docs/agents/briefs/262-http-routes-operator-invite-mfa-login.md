# Brief -- 262 Phase-5 fix: HTTP routes for operator invite + MFA login (S9)

**Ticket:** #262 . **Parent:** #243 . **Refreshed:** 2026-09-01
**Reading surface:** ~13K tokens (budget 40K) -- within budget

## Scope

Expose the operator invite and the MFA-gated operator login as real HTTP routes. Today only the `create_operator_account` facade seam and a seed route exist - an operator invite ("grow the queue-running group") and an operator login have no API surface, so the operator flow's API contract (per the operator queue/roles spec) is incomplete.

### Acceptance criteria

- [ ] `POST` route(s) for operator invite (operator-invites-operator) behind the operator RBAC scope, calling `create_operator_account`.
- [ ] `POST` login route that runs the real MFA gate (depends on T4) and returns a session token on success, 401 on bad/absent second factor.
- [ ] Route-level tests (FastAPI TestClient) cover invite, successful MFA login, and refusal without the second factor.

## Read-list (in order)

1. `apps/backend/modules/iam/adapters/routes.py` (400 lines) -- the existing IAM route module where new routes go. Understand: request/response model pattern, `_error_response` helper, `register_error_handlers`, `_run_idempotent`, `_set_jwt_cookie`, the `IssueSessionRequest` body model, and how `request.app.state.iam_facade` is accessed. (~4K tokens)
2. `apps/backend/modules/partner/adapters/routes.py` (476 lines) -- how `require_operator` is used as a `Depends` guard on operator-scoped routes (lines 221-302). Reference for the invite route's RBAC pattern. (~1.5K tokens)
3. `apps/backend/modules/iam/facade.py` (295 lines) -- the `IamFacade` coordinator: `create_operator_account` (L150-164) and `issue_operator_session` (L194-205) are the two facade methods the new routes call. (~1.5K tokens)
4. `apps/backend/modules/iam/identity_facade.py` lines 86-97 + 260-320 -- `OperatorInvitedResult` model (identity_id, phone_e164) and `create_operator_account` implementation. (~0.6K tokens)
5. `apps/backend/modules/iam/session_facade.py` lines 160-260 -- `issue_operator_session` method: the MFA gate + TOTP verification + session mint. Understand what `SessionIssuanceError` is raised for. (~1K tokens)
6. `docs/standards/api-standards.md` (66 lines) -- REST conventions, error envelope (S2), validation (S3), idempotency (S5), RBAC (S6). (~0.5K tokens)
7. `apps/backend/app/gateway/rbac.py` (83 lines) -- `require_operator` dependency, `Principal` injection. (~0.3K tokens)
8. `tests/unit/test_iam_session_route.py` (268 lines) -- canonical TestClient pattern: `StubFacade`, `_client_with`, `_client_with_store`, request/response assertions. The new tests follow this exact pattern. (~2K tokens)
9. `apps/backend/app/gateway/principal.py` (33 lines) -- `Principal` model shape. (~0.2K tokens)

## Do NOT read

- `modules/health`, `modules/consent` internals
- `docs/archive/`
- `apps/backend/modules/iam/identity_facade.py` full file (only lines 86-97 and 260-320)
- `apps/backend/modules/iam/session_facade.py` full file (only lines 160-260)

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q` (1127 passed, 0 failures)

## Done-verify (acceptance criteria to commands)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_iam_operator_invite_route.py tests/unit/test_iam_operator_login_route.py -v` -- new route tests pass
- `npm run test:unit:backend` -- full unit suite passes
- `npm run typecheck` -- mypy + tsc clean

## Handoff notes

- **Blocked by T4:** The ticket says login route must call the genuine TOTP gate. T4 is the session facade's `issue_operator_session` which already exists (L160-260) with full TOTP verification. The route just calls it.
- **Existing facade methods:** `IamFacade.create_operator_account(phone, invited_by_identity_id)` and `IamFacade.issue_operator_session(phone, code)` are already implemented. The routes are thin adapters only.
- **Error mapping:** `SessionIssuanceError` is already registered in `register_error_handlers` (L395) and maps to 409 `SESSION_REFUSED`. The operator login route inherits this for bad MFA.
- **401 vs 409 decision (review-resolved):** the AC says 401 on bad/absent second factor. `issue_operator_session` raises `SessionIssuanceError` for both identity-state refusals (unknown/not-Active phone, no role -> 409) and MFA-factor failures. A new `OperatorMfaError(SessionIssuanceError)` is raised for the three factor-failure modes (MFA not verified, no enrolled secret, TOTP verification failed) and registered as 401 `SESSION_MFA_REQUIRED`. Identity-state stays 409 `SESSION_REFUSED`.
- **Idempotency:** The invite route is a mutation -- follow the `_run_idempotent` pattern from register/verify routes. The login route is not idempotent (each MFA attempt is stateful).
- **Cookie pattern:** The operator login route should set the JWT cookie like the patient session route does (L253-258 in routes.py).
- **Invite route returns:** `OperatorInvitedResult(identity_id, phone_e164)` -- a 201 response with this model.
- **Login route returns:** `SessionResult(jwt, jti, scope, identity_id, expires_in_seconds, refresh_token)` -- same shape as patient session, with `scope="operator"`.
