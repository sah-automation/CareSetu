# Brief -- T3 Partner self-service status screens

**Ticket:** #281 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~4K tokens (budget 10K) -- within budget

## Scope

Replace the skeleton placeholders on the partner status screens with real data from the backend. Pending screen reads `GET /v1/partner/me` + `GET /v1/partner/me/verification` to show verification round state, submitted-at timestamp, and partner identity. Rejected screen reads `/me` + `GET /v1/partner/rejection-reason` to show the specific rejection reason and a working appeal CTA wired to `POST /v1/partner/appeal`. Both screens include polling/refresh to reflect operator decisions.

## Read-list (in order)

1. `apps/frontend/src/app/(partner)/partner/status/pending/page.tsx` -- 74 lines, current skeleton with `t.detailPlaceholder` values. Keep the card layout, replace placeholder values with real data.
2. `apps/frontend/src/app/(partner)/partner/status/rejected/page.tsx` -- 81 lines, current skeleton with `t.reasonPlaceholder` and stub resubmit CTA. Replace with real reason + working appeal.
3. `apps/frontend/src/lib/partner/api.ts` -- T1 output: `fetchPartnerMe()`, `fetchPartnerVerification()`, `fetchRejectionReason()`, `fileAppeal()` functions
4. `apps/frontend/src/lib/api-errors.ts` -- `ApiError`, `parseErrorEnvelope`, `extractTraceId` for error handling
5. `apps/frontend/src/app/(patient)/patient/record/page.tsx` -- loading/error pattern reference: `LoadStatus = "loading" | "ready" | "error"`, `useCallback` + `useEffect` fetch pattern, `ErrorBanner` with retry + dismiss

## Do NOT read

- operator pages, registration wizard, backend event code, docs/archive/, prototype/, `lib/auth/session.ts`.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions (existing `page.test.tsx` tests must still pass)
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- **T1 dependency**: `lib/partner/api.ts` must exist before this ticket starts.
- Pending screen response shapes:
  - `PartnerMeView`: `{ partner_id, status, partner_type, round, created_at }`
  - `PartnerVerificationStatusView`: `{ partner_id, round, status, decision, decision_reason, decided_at }`
- Rejected screen response shapes:
  - `PartnerMeView` (same as above)
  - `RejectionReasonView`: `{ partner_id, rejection_reason, round }`
- Appeal endpoint: `POST /v1/partner/appeal` returns `PartnerView: { partner_id, status, round }`
- The `status` field from `/me` is the lifecycle state string: `"Registered"`, `"Under Verification"`, `"Active"`, `"Rejected"`.
- Polling: use `setInterval` to re-fetch every N seconds (e.g. 10s) while status is `"Under Verification"`. Stop polling when status changes to `"Active"` or `"Rejected"`.
- The rejected screen's resubmit CTA currently reveals a stub notice. Replace with: call `fileAppeal()`, on success route to `/partner/status/pending` (the partner re-enters the queue).
- Keep the existing card layout and `data-testid` attributes for test stability.
