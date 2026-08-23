# Brief - T5 Frontend - Next.js middleware for route protection

**Ticket:** #150 · **Parent:** #146 Phase 2.5 · **Refreshed:** 2026-08-17
**Reading surface:** ~3K tokens (budget 10K) - well within budget

## Scope

Create `middleware.ts` at the frontend root that intercepts all requests and performs route protection based on the httpOnly JWT cookie set by the backend. Unauthenticated users accessing protected routes get redirected to `/login`. Authenticated users visiting `/login` get redirected to their dashboard.

Acceptance criteria (verbatim):

- `middleware.ts` created at `apps/frontend/src/middleware.ts`
- Reads JWT from httpOnly cookie (named `caresetu.access_jwt` or similar)
- Protected routes (`/patient/*`, `/partner/*`, `/operator/*`): if no valid cookie -> `redirect(/login)`
- Login route (`/login`): if valid cookie present -> `redirect(/patient)` (single role for now)
- Choose-role route (`/choose-role`): if no valid cookie -> `redirect(/login)`
- Public routes (`/`, `/login` when not authed, static assets): pass through unchanged
- Middleware does NOT decode JWT claims - only checks cookie presence
- `next.config` configured to exclude middleware from static asset matching
- Unit tests pass: mock requests with/without cookie, verify redirect behavior for each route pattern

## Read-list (in order)

1. Next.js middleware docs - `middleware.ts` pattern, `NextRequest`/`NextResponse` API, cookie reading, redirect behavior, matcher config (~1.5K tokens)
2. `src/app/page.tsx` (5 lines) - current root page; confirms `/` is a public route (~0.1K tokens)
3. `src/app/(patient)/patient/page.tsx` (5 lines) - protected route; currently renders `PatientAuthWizard` (~0.1K tokens)
4. `src/app/(partner)/partner/page.tsx` (7 lines) - protected route; placeholder hello-world (~0.1K tokens)
5. `src/app/(operator)/operator/page.tsx` (7 lines) - protected route; placeholder hello-world (~0.1K tokens)

## Do NOT read

- Backend code, auth wizard component, AuthContext (not yet created), session.ts, api.ts, other modules.

## Baseline verify (must pass before the first edit)

- `npm run build` (frontend builds without middleware)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - existing + new middleware tests pass
- New test file covers: protected routes redirect without cookie, login redirects with cookie, public routes pass through, choose-role redirects without cookie

## Handoff notes

- The cookie name is `caresetu.access_jwt` (set by backend T1). The middleware reads this cookie but does NOT decode it - only checks presence. Decoding and role resolution happen in AuthContext (T3) and the login page (T6).
- For "valid cookie" in the middleware, check that the cookie exists and is non-empty. Do NOT attempt JWT signature verification in middleware (too expensive, no crypto API in Edge Runtime).
- The `next.config` matcher should exclude static assets (`_next/static/*`, `_next/image/*`, `favicon.ico`, etc.) to avoid unnecessary middleware execution.
- The middleware runs in the Edge Runtime - it cannot use Node.js APIs. Use `NextRequest.cookies.get()` to read the cookie.
- Route patterns: protected = `/patient/:path*`, `/partner/:path*`, `/operator/:path*`; public = `/`, `/login`, `/choose-role`, static assets.
