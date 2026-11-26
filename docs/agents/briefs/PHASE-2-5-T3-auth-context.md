# Brief - T3 Frontend - AuthContext provider with session validation

**Ticket:** #151 · **Parent:** #146 Phase 2.5 · **Refreshed:** 2026-08-17
**Reading surface:** ~3.5K tokens (budget 10K) - well within budget

## Scope

A React `AuthProvider` context that wraps the dashboard routes and manages session state. On mount: validates the session against `GET /v1/me`, auto-refreshes expired JWTs using the refresh token, and populates user/roles/selectedRole. Provides `logout()`, `switchRole()`, `isAuthenticated`, and `isLoading` to all child components. Redirects to `/login` when session is invalid.

Acceptance criteria (verbatim):

- `AuthProvider` component created and exported from `src/lib/auth/`
- On mount, reads session from localStorage (jwt, refresh_token, scope, identity_id, phone)
- Calls `GET /v1/me` with JWT to validate session and fetch roles
- If JWT expired but refresh_token valid: calls refresh endpoint, updates localStorage and cookie
- If refresh fails: clears session, redirects to `/login`
- Context exposes: `user` (id, phone, roles array), `selectedRole`, `switchRole(role)`, `logout()`, `isAuthenticated`, `isLoading`
- `logout()` clears localStorage, clears cookie, redirects to `/`
- `isLoading` is `true` during initial validation, `false` after
- Unit tests pass: mock `/v1/me` and refresh endpoints, test all state transitions

## Read-list (in order)

1. `src/lib/auth/session.ts` (50 lines) - `saveSession`, `readSession`, `clearSession` functions; the localStorage key names (`caresetu.access_jwt`, `caresetu.refresh_token`, `caresetu.session`) and the `StoredSession` shape (~0.5K tokens)
2. `src/lib/auth/api.ts` (138 lines) - all exported functions: `registerPhone`, `verifyOtp`, `resendOtp`, `issueSession`, `fetchDemoOtp`; the `AuthApiError` class and return types (~1.5K tokens)
3. `src/components/auth/otp/otpState.ts` (read only the `StoredSession` type and `OtpState` interface) - the session data shape that AuthContext must be compatible with (~1K tokens)
4. `src/app/page.tsx` (5 lines) - current redirect behavior; AuthContext logout will redirect here (~0.1K tokens)

## Do NOT read

- `PatientAuthWizard.tsx` (full component - 330 lines), backend code, other modules, dashboard components, PRD, roadmap.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (2 test files pass with 8 tests; 2 pre-existing failures unrelated to this work)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - existing + new AuthContext tests pass
- New test file covers: session validation on mount, auto-refresh on expired JWT, redirect to login on invalid session, role population, logout clears state

## Handoff notes

- The `GET /v1/me` endpoint does not exist yet in the backend. The AuthContext should be written to call it but handle 404/500 gracefully (treat as invalid session, redirect to login). The endpoint will be added in a later phase.
- The refresh endpoint (`POST /v1/auth/refresh`) also does not have an HTTP route yet (backend T1 adds the cookie, but the refresh HTTP route is separate). AuthContext refresh logic should call the endpoint but handle failure gracefully.
- `StoredSession` shape from `session.ts`: `{ jwt: string, refresh_token: string, scope: string, identity_id: string, phone: string }`. AuthContext reads this on mount.
- The cookie to clear on logout is `caresetu.access_jwt` (set by backend T1). Use `document.cookie` to clear it since it's httpOnly and JS can't read it, but can set it to expired.
- Do NOT create the `GET /v1/me` endpoint - that is out of scope for this ticket.
