# Brief -- T7 Doctor landing page

**Ticket:** #279 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~2K tokens (budget 10K) -- within budget

## Scope

Replace the 5-line doctor page stub with a non-empty landing page for an activated doctor partner. Show a welcome with the doctor's name (from session or `/me`), a brief status summary, and next-steps placeholder content. Directory search is Phase 6 -- this ticket just ensures the `/doctor` page is not blank for an activated partner.

## Read-list (in order)

1. `apps/frontend/src/app/(doctor)/doctor/page.tsx` -- current 5-line stub (`return <PageHeader title="Welcome, Doctor" />`)
2. `apps/frontend/src/app/(doctor)/layout.tsx` -- AppShell with `role="doctor"` wrapper
3. `apps/frontend/src/lib/auth/session.ts` -- `StoredSession` shape (jwt, refresh_token, jti, scope, identity_id, phone); `readSession()` returns `StoredSession | null`
4. `apps/frontend/src/components/dashboard/types.ts` -- `Role` type, `ROLE_HOME` mapping (for context only, not editing)

## Do NOT read

- operator pages, patient pages, registration wizard, backend code, prototype/, docs/archive/, `lib/api-base.ts`, `lib/api-errors.ts`.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- The page is a server component currently. If it needs client-side session data, convert to `"use client"` and use `readSession()`. Alternatively, keep it simple with static placeholder content that doesn't need session data.
- The prototype `post-login-routing.html` shows a multi-role card pattern, but that's out of scope for this ticket. Just make the page non-empty.
- Blueprint section 4.2/4.3 reference for doctor landing content is minimal -- placeholder content (welcome + "Your profile is being verified" or "Next steps") is acceptable.
