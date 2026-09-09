# Brief -- T1 Frontend API clients (partner + operator + audit)

**Ticket:** #278 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~5K tokens (budget 10K) -- within budget

## Scope

Typed API clients in `lib/partner/api.ts`, `lib/operator/api.ts`, and `lib/audit/api.ts` reusing `authedFetch` (`lib/api-base.ts`) + shared `ErrorEnvelope` plumbing (`lib/api-errors.ts`). Covers all Phase 5 backend endpoints:

- Partner: `POST /v1/partner/register`, `POST /v1/partner/credentials`, `GET /v1/partner/me`, `GET /v1/partner/me/verification`, `GET /v1/partner/rejection-reason`, `POST /v1/partner/appeal`
- Operator: `POST /v1/auth/operator/login`, `POST /v1/auth/operator/mfa/enroll`, `GET /v1/partner/verification-queue`, `GET /v1/partner/verification/{id}`, `POST /v1/partner/verification/{id}/decision`
- Patient audit: `GET /v1/audit/access-history`

Each client module follows the `lib/record/api.ts` pattern: imports `API_BASE_URL` + `authedFetch` from `@/lib/api-base`, `ApiError` + `parseErrorEnvelope` + `extractTraceId` from `@/lib/api-errors`; exports typed result interfaces mirroring backend Pydantic models; throws `ApiError` with stable error codes; includes runtime type guards where shapes are returned from untrusted endpoints.

## Read-list (in order)

1. `apps/frontend/src/lib/api-base.ts` -- `API_BASE_URL`, `authedFetch(input, init?)` signature; 30 lines (~0.5K tokens)
2. `apps/frontend/src/lib/api-errors.ts` -- `ErrorEnvelope`, `ApiError`, `extractTraceId`, `parseErrorEnvelope`; 52 lines (~0.7K tokens)
3. `apps/frontend/src/lib/record/api.ts` -- pattern reference: how to import, type, wrap, throw; 60 lines (~0.8K tokens)
4. `apps/frontend/src/lib/consent/api.ts` -- secondary pattern reference: runtime type guards, `consentFetch<T>` helper; 196 lines (~2.5K tokens)
5. `apps/backend/modules/partner/facade.py` lines 150-347 -- response shapes: `RegisterPartnerResult`, `CredentialSubmissionResult`, `PartnerMeView`, `PartnerVerificationStatusView`, `RejectionReasonView`, `PartnerView`, `PartnerQueue`, `PartnerQueueItem`, `PartnerVerificationDetail`, `CredentialDetail`, `VerificationRound`, `AuditEventDetail`
6. `apps/backend/modules/partner/adapters/routes.py` lines 61-114 -- request shapes: `RegisterPartnerRequest`, `CredentialDocumentRequest`, `CredentialSubmissionRequest`, `OperatorDecisionRequest`
7. `apps/backend/modules/iam/session_facade.py` lines 48-68 -- `SessionResult` shape (jwt, jti, scope, identity_id, expires_in_seconds, refresh_token)
8. `apps/backend/modules/iam/mfa_facade.py` lines 48-61 -- `EnrollMfaResult` shape (identity_id, phone_e164, secret, provisioning_uri)
9. `apps/backend/modules/health/facade.py` lines 83-110 -- `AccessHistoryEntry`, `AccessHistoryView` shapes

## Do NOT read

- Any page components, prototype/, docs/archive/, backend event/dispatcher code, `lib/auth/api.ts` (patient OTP flow, not staff), `lib/auth/session.ts` (not needed for T1).

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

Note: as of 2026-09-03, frontend tests pass (138 tests across 11 suites) but exit with code 1 due to jsdom canvas warnings in `ProfileCompletionWizard.test.tsx` axe scans. These are pre-existing and unrelated to this ticket.

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck -w @caresetu/frontend` -- all new modules importable without type errors
- `npm run test -w @caresetu/frontend` -- no regressions
- `npm run lint` -- no new lint violations

## Handoff notes

- The `SessionResult` type already exists in `lib/auth/api.ts` (patient OTP flow). The operator login returns the same shape. The new `lib/operator/api.ts` should import/re-export `SessionResult` from `lib/auth/api.ts` rather than duplicating it, or define its own if the operator session has additional fields. Check the backend `SessionResult` -- it's identical for both patient and operator sessions.
- `saveSession(session, phone)` in `lib/auth/session.ts` expects a `SessionResult` and a phone string. The operator login will need to call this after receiving the session response.
- The operator login endpoint (`POST /v1/auth/operator/login`) returns the session as the response body AND sets an httpOnly cookie. The frontend needs the JWT from the body for `saveSession`.
- `POST /v1/auth/operator/login` returns 401 with `SESSION_MFA_REQUIRED` envelope when TOTP is wrong/missing. This is the MFA gate signal for T4.
- The `POST /v1/partner/credentials` endpoint requires the caller to be authenticated (partner scope). After registration (T2), the partner has a session and can submit credentials.
