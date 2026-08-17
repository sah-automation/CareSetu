# Brief — T5 Frontend: Next.js middleware for route protection

**Ticket:** #150 · **Parent:** #146 · **Refreshed:** 2026-08-17
**Reading surface:** ~3K tokens (budget 10K) — within budget

## Scope

Create `middleware.ts` at the frontend root that intercepts all requests and performs route protection based on the httpOnly JWT cookie set by the backend. Unauthenticated users accessing protected routes get redirected to `/login`. Authenticated users visiting `/login` get redirected to their dashboard.

### Acceptance criteria

- `middleware.ts` created at `apps/frontend/src/middleware.ts`
- Reads JWT from httpOnly cookie named `caresetu_session`
- Protected routes (`/patient/*`, `/partner/*`, `/operator/*`): if no valid cookie → `redirect(/login)`
- Login route (`/login`): if valid cookie present → `redirect(/patient)` (single role for now)
- Choose-role route (`/choose-role`): if no valid cookie → `redirect(/login)`
- Public routes (`/`, static assets): pass through unchanged
- Middleware does NOT decode JWT claims — only checks cookie presence
- `next.config` configured to exclude middleware from static asset matching
- Unit tests pass: mock requests with/without cookie, verify redirect behavior for each route pattern

## Read-list (in order)

1. `apps/frontend/src/app/` route structure — current routes and layout (~0.5K tokens)
2. `apps/frontend/next.config.ts` — current config, add matcher (~0.3K tokens)
3. `apps/frontend/vitest.config.ts` — test setup for middleware tests (~0.2K tokens)
4. `apps/backend/modules/iam/adapters/routes.py:99` — `_JWT_COOKIE_NAME = "caresetu_session"` cookie name confirmation (~0.1K tokens)
5. `apps/frontend/src/lib/auth/session.ts` — existing auth constants for reference (~0.1K tokens)

## Do NOT read

- Backend auth logic beyond cookie name
- `PatientAuthWizard` component internals
- AuthContext (not yet created)
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run build` in `apps/frontend/` — should build without middleware

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` — middleware unit tests pass
- `npm run typecheck` — no type errors

## Handoff notes

- Cookie name is `caresetu_session` (httpOnly, samesite=strict, path=/)
- `/` already redirects to `/patient` via `page.tsx` — middleware should let it pass through
- `/login` and `/choose-role` routes don't exist yet — middleware should handle them gracefully (no redirect loop)
- Next.js 16.3.0 — Edge runtime middleware, uses `NextRequest`/`NextResponse`
