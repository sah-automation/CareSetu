# Brief - 298 Fix partner registration 409 error

**Ticket:** #298 · **Parent:** partner registration 409 fix plan · **Refreshed:** 2026-09-04
**Reading surface:** ~8K tokens novel (budget 10K) - within budget, backend facade + route + frontend wiring + tests

## Scope

Add `POST /v1/auth/partner/session` backend endpoint that mints a partner-scoped JWT for registered (pre-activation) partners, wire `ProviderRegisterWizard` to call it, fix `AuthApiError` masking so real backend errors surface, and add tests. The partner registration loop works end-to-end.

- [ ] Backend: `SessionFacade.issue_partner_session` mints partner-scoped JWT for registered partners
- [ ] Backend: `POST /v1/auth/partner/session` route returns 200 + Set-Cookie on success
- [ ] Backend: 409 SESSION_REFUSED for unknown phone or patient-only phone
- [ ] Frontend: `issuePartnerSession` function added to `lib/auth/api.ts`
- [ ] Frontend: `ProviderRegisterWizard` calls `issuePartnerSession` instead of `issueSession`
- [ ] Frontend: `AuthApiError` surfaces real backend text (not generic error)
- [ ] Frontend: `AuthApiError` carries `traceId` from envelope
- [ ] Backend tests: `issue_partner_session` facade and route tests pass
- [ ] Frontend tests: wizard mocks updated, `AuthApiError` surface test added
- [ ] `npm run test:unit:backend` and `npm run test:unit:frontend` pass
- [ ] `npm run lint` and `npm run typecheck` pass

## Read-list (in order)

1. **`modules/iam/session_facade.py`** - `issue_session` (lines 106-161) and `issue_operator_session` methods, `_lock_identity_by_phone`, `_mint_session_row`, `_PATIENT_ROLE`, `_OPERATOR_ROLE` constants. Understand the pattern for minting sessions with different scopes.
2. **`modules/iam/facade.py`** - `IamFacade` delegation pattern, how `issue_session` and `issue_operator_session` are delegated.
3. **`modules/iam/adapters/routes.py`** - existing `issue_session` route (lines 216-249), `_set_jwt_cookie`, `_session_refused` handler (lines 409-416), `IssueSessionRequest` model. Understand the route pattern and error mapping.
4. **Composition root** - where `IamFacade`/`SessionFacade` are wired (likely `app/main.py`). Understand how to inject the `resolve_partner_by_phone` seam.
5. **`apps/frontend/src/lib/auth/api.ts`** - `issueSession` function (line 129), `AuthApiError` class (lines 63-73), `post` helper. Understand the API client pattern and error classes.
6. **`apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx`** - `handleSubmitPartner` (lines 937-980), error catch block (lines 971-980), imports. Understand the current flow and error handling.
7. **`apps/frontend/src/components/auth/staff/ProviderRegisterWizard.test.tsx`** - existing mocks (vi.mock), "calls registerPartner then issueSession" test (line 458). Understand the test patterns.
8. **Backend test files** - `tests/unit/test_iam_session_route.py` (if exists), or other session route tests. Understand the test patterns for route testing.

## Do NOT read

- `docs/plans/phase5-frontend-gap-plan.md`, `docs/archive/`
- Other frontend API clients, partner/audit modules in full
- i18n dictionaries (unless adding new error copy)
- The prior uncommitted changes (already reconciled in #297)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new `issue_partner_session` facade and route tests green
- `npm run test:unit:frontend` - wizard suite green, `AuthApiError` surface test passes
- `npm run lint` - clean
- `npm run typecheck` - no new type errors
- Manual: complete partner wizard -> lands on `/partner/status/pending` (was previously stuck at 409 generic error)

## Key decisions to reconcile

- **Partner session gating:** Gate on partner-profile existence (not identity `Active` status or role grant), because a fresh registrant has neither. The `resolve_partner_by_phone` seam crosses the facade boundary via dependency inversion (no cross-schema import).
- **Security:** Granting a freshly-registered partner the `partner` scope exposes exactly the self-service surface a pending partner needs (submit credentials, read own status, appeal) and nothing more. All `require_partner` routes are partner self-service only.
- **`AuthApiError` traceId:** Add `readonly traceId: string` to `AuthApiError` and set it from `envelope.trace_id` in the constructor. This makes Bug B's fix clean and improves operator-login error display too.
- **Session ordering:** The prior uncommitted fix moved session issuance before `submitCredentials` - this is correct (credentials need a JWT first). The plan's final sequence already places `issuePartnerSession` before `submitCredentials`.

## Handoff notes

- The backend `SessionFacade` needs a `resolve_partner_by_phone` seam injected at construction. Wire this through the composition root (`app/main.py`) so the session facade can resolve a partner profile by phone through the partner module's `PartnerFacade` (dependency inversion).
- The frontend `issuePartnerSession` function should reuse the existing `post` helper and `SessionResult` type.
- The error catch in `ProviderRegisterWizard` must check `err instanceof ApiError || err instanceof AuthApiError` to surface real backend text.
- Read `docs/adr/0007-split-origin-deployment-session-invariants.md` before finalizing cookie handling on the new route.
- Commit only this ticket's files; the reconciliation changes from #297 are already committed.
