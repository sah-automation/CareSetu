# Brief -- T5 Operator verification queue list

**Ticket:** #284 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~3K tokens (budget 10K) -- within budget

## Scope

Replace the 5-line operator page stub with a real verification queue list. Fetches `GET /v1/partner/verification-queue`, renders a table/list of `[Under Verification]` submissions with partner name, type, registration age, and status badge. Includes sorting by registration age. Click-through to detail view at `/operator/verification/[id]`. Operator-only guard already enforced by proxy matcher.

## Read-list (in order)

1. `apps/frontend/src/app/(operator)/operator/page.tsx` -- 5-line stub: `return <PageHeader title="Welcome, Operator" />`
2. `apps/frontend/src/app/(operator)/layout.tsx` -- AppShell with `role="operator"` wrapper
3. `apps/frontend/src/lib/operator/api.ts` -- T1 output: `fetchVerificationQueue(params?)` function
4. `apps/frontend/src/app/(patient)/patient/record/page.tsx` -- loading/error pattern reference: `LoadStatus`, `useCallback` + `useEffect`, `ErrorBanner`
5. `apps/frontend/src/components/dashboard/types.ts` -- `Role` type context (for understanding `operator` role)

## Do NOT read

- decision logic, partner pages, registration wizard, backend dispatcher, docs/archive/, prototype/.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- **T4 dependency**: operator session must be established for authenticated fetch. T4 completes the login flow; this ticket builds on that session.
- Backend response shape: `PartnerQueue: { items: PartnerQueueItem[] }` where `PartnerQueueItem: { partner_id, identity_id, partner_type, status, practice_name, practice_address, created_at, round, audit_link? }`.
- Default query params: `status="Under Verification"`, `sort_by="registration_age"` (oldest first, KPI-004).
- The page should show: partner type badge (doctor/lab/chemist), practice name (or phone if null), practice address, registration age (calculated from `created_at`), current round, and a link/button to `/operator/verification/{partner_id}`.
- Convert the server component to `"use client"` for data fetching.
- Follow the record/page.tsx pattern: loading skeleton, error banner with retry, empty state for zero items.
- Sorting: allow sorting by `registration_age` (default), `partner_type`, `status`. Use the same sort params the backend accepts.
