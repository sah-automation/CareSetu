# Brief -- T8 Patient access-history view

**Ticket:** #283 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~4K tokens (budget 10K) -- within budget

## Scope

Replace the Phase 4 `Soon` placeholder on `/patient/record` (the `placeholder-access` block at record/page.tsx:244-255) with a real render of `GET /v1/audit/access-history`. Show who accessed the patient's record, when, and under which consent. Follow the existing record page's loading/error pattern.

## Read-list (in order)

1. `apps/frontend/src/app/(patient)/patient/record/page.tsx` -- 269 lines. Focus on: placeholder-access block (~line 244-255, currently `{/* Phase 4 - access audit */}` with `SoonBadge`), loading/error pattern (`LoadStatus`, `useCallback` + `useEffect` fetch), `ErrorBanner` with retry + dismiss. The page already fetches `fetchOwnRecord()` -- add a second fetch for access history.
2. `apps/frontend/src/lib/audit/api.ts` -- T1 output: `fetchAccessHistory(patientId)` function returning `AccessHistoryView`
3. `apps/frontend/src/lib/api-errors.ts` -- `ApiError`, `parseErrorEnvelope`, `extractTraceId`
4. `apps/frontend/src/app/(patient)/patient/record/page.test.tsx` -- existing tests to avoid breaking

## Do NOT read

- operator pages, partner pages, registration wizard, backend audit module internals, docs/archive/, prototype/.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions (existing record page tests must pass)
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- **T1 dependency**: `lib/audit/api.ts` must exist before this ticket starts.
- Backend response shape: `AccessHistoryView: { entries: AccessHistoryEntry[] }` where `AccessHistoryEntry: { actor_id, actor_type, scope, accessed_at, denied, denial_reason }`.
- The access history endpoint requires a `patient_id` query param (must equal the authenticated caller's subject ID). The frontend can get this from the session (`StoredSession.identity_id`) or from `/v1/me`.
- The `actor_type` field tells you who accessed: `"patient"` (owner read), `"partner"` (doctor/lab/chemist read), etc. Use this to show a human-readable label.
- `denied: true` entries show who was refused access and why (`denial_reason`). Highlight these differently (e.g., red badge or strikethrough).
- The `scope` field shows what record area was accessed (e.g., `"consultations"`, `"prescriptions"`, `"full_record"`).
- Keep the existing `data-testid="placeholder-access"` removal -- replace the entire placeholder block with the real data section.
- The page already has a loading/error pattern -- follow it for the access history fetch. You can run both fetches (record + access history) in parallel with `Promise.all`.
