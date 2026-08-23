# ADR-0005: Cookie + localStorage dual JWT storage

**Status:** accepted (amended 2026-08-23 - see Amendment below)
**Date:** 2026-08-17
**Decides:** How the JWT is stored on the frontend to satisfy both Next.js middleware (server-side route protection) and the API client (client-side Authorization header).
**Traceability:** `PHASE-2.5-APP-SHELL` (issue #146), `MOD-001`, `FEAT-001`.

## Context

Next.js middleware runs on the server/edge and cannot access localStorage. Route protection requires checking the JWT on every navigation to redirect unauthenticated users away from protected routes. The existing API client (`src/lib/auth/api.ts`) reads the JWT from localStorage to set the `Authorization` header on outbound requests. A single storage location cannot serve both consumers: httpOnly cookies are invisible to JavaScript (middleware can read them, API client cannot), while localStorage is invisible to middleware (API client can read it, middleware cannot).

## Decision

Store the JWT in **both** locations simultaneously:

1. **httpOnly cookie** - set by the backend's `POST /v1/auth/session` endpoint via `Set-Cookie` header. Attributes: `httpOnly=true`, `secure=true` (production), `sameSite=strict`, `path=/`, `maxAge` matching JWT TTL (~15 min). Read by Next.js middleware on every request. Not accessible to JavaScript.

2. **localStorage** - written by the frontend's `saveSession()` on the same code path that processes the session response. Contains JWT + refresh_token + session metadata. Read by `src/lib/auth/api.ts` for the `Authorization` header and by `AuthContext` for session state.

The backend sets the cookie. The frontend writes localStorage. Both happen from the same session issuance response. The middleware reads the cookie. The API client reads localStorage. They never cross.

## Considered options

- **Cookie only (httpOnly):** Rejected - the API client would need to read the cookie via `document.cookie`, but httpOnly cookies are invisible to JavaScript. A non-httpOnly cookie would work but weakens security (XSS can exfiltrate it). A backend proxy that injects the `Authorization` header would add complexity and latency.

- **localStorage only:** Rejected - Next.js middleware cannot access localStorage. Route protection would require a client-side guard component, which flashes wrong content on load and provides no server-side protection.

- **Session cookie + separate access token cookie:** Considered - a session cookie (non-JWT, opaque) for middleware and a separate non-httpOnly access token cookie for the API client. Cleaner separation but two cookies, two expiry windows, and the non-httpOnly cookie has the same XSS exposure as localStorage.

## Consequences

- The JWT exists in two places with the same TTL. If one is cleared (e.g., user clears localStorage), the other persists until its own expiry. The AuthContext validates via `/v1/me` on mount, so a stale localStorage entry is caught and refreshed.

- The backend must set the `Set-Cookie` header on session issuance and refresh. This is an additive change to `POST /v1/auth/session` and `POST /v1/auth/refresh` - the response body is unchanged.

- The middleware only checks cookie presence, not JWT claims. Role-based routing logic lives in the AuthContext (client-side). This keeps the middleware simple and avoids JWT parsing on the edge.

- Future risk: if the JWT TTL is changed, both the cookie `maxAge` and the JWT `exp` claim must stay in sync. This is already a single-source concern (the backend's JWT signing logic sets both).

## Amendment (2026-08-23): client-written presence-hint cookie for the edge guard

**Context of the change:** the live demo deploys the frontend and backend on
separate sites (Vercel `<app>.vercel.app`, Render `<api>.onrender.com`). The
backend's `SameSite=Strict` `Set-Cookie` is dropped outright by browsers on
cross-site responses - and even if stored, it would be scoped to the API
origin, invisible to the Next.js proxy running at the frontend origin. The
PHASE-2.6 cookie-presence route guard therefore never saw a session on the
live deployment: every navigation to `/patient` bounced to `/login` with a
307 (first observed after PR #190). The same design works unchanged on
same-site topologies (local dev `localhost:3000/8000`, staging Caddy edge),
which is why all pre-deploy gates passed.

**Amended decision:** `saveSession()` additionally writes a secret-free,
first-party presence-hint cookie `caresetu_authed=1` (`Path=/`,
`SameSite=Lax`, `Secure` on https) via `document.cookie`, and
`clearSession()` expires it; `src/proxy.ts` checks that hint instead of the
backend-issued cookie. Attributes of the amended hint:

- **Value is `"1"`** - no token material, so nothing new to exfiltrate.
- **Fixed long window (30 days), not the JWT TTL** - the refresh path
  (`POST /v1/auth/refresh`) rotates tokens without a TTL payload, so a
  TTL-bound hint would out-live its renewal signal. A lapsed or stale hint
  costs at most one client-side redirect, because real authentication is
  still enforced by gateway RBAC and AuthContext's `/v1/me` validation.

**Unchanged:** localStorage remains the JWT source for the API client; the
backend keeps setting its httpOnly cookie (harmless on split deployments,
still useful if a same-site topology returns); the guard still never parses
JWT claims at the edge.
