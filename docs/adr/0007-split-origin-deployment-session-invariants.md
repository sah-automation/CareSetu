# ADR-0007: Split-origin deployment topology and session-transport invariants

**Status:** accepted
**Date:** 2026-08-23
**Decides:** The durable rules that keep authentication and credentialed calls working in production, where the frontend and backend are different sites (Vercel + Render), even though local development shares localhost.
**Traceability:** `PHASE-2.5-APP-SHELL` (#146), `PHASE-2.6-PUBLIC-FACE-CHASSIS` (#191), `MOD-001`, `NFR-002`; extends the operational context of `ADR-0005`. Incident record: #119 (DEPLOY-1 CORS), #159 (307 redirect loop), #208 (presence-hint cookie).

## Context

Local development runs the frontend (`localhost:3000`) and backend (`localhost:8000`) on one host. Cookies are first-party across ports, so every session-transport design works locally. Production is split-origin **by design**: Vercel serves `<app>.vercel.app`, Render serves `<api>.onrender.com` (free-tier demo; a same-origin VM path remains documented in the deployment plan). Browsers apply cross-site cookie rules between those two sites, so several locally-green designs fail only after deploy - which is exactly when they are hardest to attribute. This has caused three production incidents:

1. **#119 era (CORS):** hardcoded `localhost:3000` origins blocked credentialed browser calls from the Vercel origin. Fixed by env-driven `CORS_ALLOWED_ORIGINS` + `allow_credentials=True` (DEPLOY-1).
2. **#159 (307 redirect loop):** three compounding causes - the `middleware.ts` → `proxy.ts` rename left dead code that Next.js never loaded; a stale Vercel `.next` build cache kept serving the old middleware artifact; `GATEWAY_JWT_VERIFY_ENABLED` was unset so `/v1/me` returned 401 and `AuthProvider` cleared every session.
3. **#208 (invisible session cookie):** the edge guard checked the backend-set `caresetu_session` cookie. Under split hosting that cookie can never exist on the frontend origin (the `SameSite=Strict` `Set-Cookie` is dropped on cross-site responses, and even a stored one stays scoped to the API origin). Every navigation to `/patient` bounced to `/login` with a 307 after OTP login.

All three were invisible locally because localhost ports share cookies. The rules below exist so no agent re-derives them the hard way.

## Decision - invariants

### Topology

1. **Production is split-origin.** Never assume same-origin cookies, same-site redirects, or relative API paths across the frontend/backend boundary. Any change touching session transport, cookies, CORS, middleware/proxy guards, or deploy config must be reasoned against the split topology explicitly AND verified by the live gates (`scripts/live_smoke.py`, workflow `live-verify.yml`) - green local unit/e2e runs prove nothing about deployed auth.
2. **Two legal topologies, both env-driven:** split free-tier now; single-VM same-origin Caddy edge later. Hardcode neither into code (deployment plan §8 carries the migration path).

### Cookies

3. The backend's `caresetu_session` cookie (`httpOnly`, `Secure` unless dev/test, `SameSite=Strict`, `Path=/`; set in `apps/backend/modules/iam/adapters/routes.py`) is **dropped cross-site and scoped to the API origin**. Nothing frontend-visible may depend on it. It stays set deliberately: harmless today, useful if a same-site topology returns.
4. The edge guard (`apps/frontend/src/proxy.ts`) reads **only** the first-party, client-written presence-hint cookie `caresetu_authed`, written/cleared by `saveSession()`/`clearSession()` in `apps/frontend/src/lib/auth/session.ts`. Never repoint the guard at `caresetu_session`; any new guard or programmatic bypass must use the same hint name.
5. Hint-cookie attributes are deliberate: value `"1"` (secret-free, nothing to exfiltrate); `Path=/`; `SameSite=Lax`; `Secure` on https; fixed 30-day window, **not** the JWT TTL (the refresh path rotates tokens without a TTL payload, so a TTL-bound hint would outlive its renewal signal). A stale hint costs at most one client-side redirect.
6. The guard never decodes JWT claims at the edge (`ADR-0005`). Real enforcement is gateway RBAC plus `AuthContext`'s `/v1/me` validation with Bearer-from-localStorage. Do not strengthen the hint into a token carrier; do not remove `/v1/me` validation.
7. The backend cookie's `secure` flag follows `APP_ENVIRONMENT` (on unless dev/test); production keeps `APP_ENVIRONMENT=production`.

### Fetch and CORS

8. Every credentialed frontend call to the API carries `credentials: "include"` (`src/lib/auth/api.ts` shared `post()`; `AuthContext` refresh). New fetch/axios wrappers for auth endpoints must include it or `Set-Cookie` and credentialed CORS responses silently break.
9. Backend CORS keeps `allow_credentials=True` with an exact-origin echo list (`_DEV_CORS_ORIGINS + cors_allowed_origins`, deduped) in `apps/backend/app/main.py`. Never switch to wildcard `*` (incompatible with credentials; Starlette echoes ACAO only for allowlisted origins).
10. `CORS_ALLOWED_ORIGINS` on Render must be the exact Vercel origin (scheme + host, no trailing slash), updated whenever the domain changes; it is `sync: false` in `render.yaml` - dashboard-managed, never committed. The live smoke's ACAO-echo assertion (including on the 401 envelope) is the regression gate for this value.

### Config, build, gateway

11. `NEXT_PUBLIC_API_BASE_URL` must be set on Vercel to the Render URL; `next.config.ts` fails the Vercel build loudly if it is absent when `VERCEL` is set. Never reintroduce a silent localhost fallback for production builds.
12. `NEXT_PUBLIC_*` vars are build-time inlined on Vercel: changing them requires a rebuild, and the live smoke asserts the backend URL plus demo strings appear in served JS chunks (guards stale-build/env-inlining bugs).
13. Edge-guard file naming follows what the framework actually loads (Next 16.3 loads `src/proxy.ts`; older convention was a file literally named `middleware.ts`). After ANY rename/move of the guard, verify against a cold build (`delete .next`) - Vercel's stale build cache serving an old artifact caused incident #159.
14. Gateway flags stay on in production: `GATEWAY_JWT_VERIFY_ENABLED=true` (otherwise `/v1/me` 401s and `AuthProvider` clears every session - the second half of incident #159) and `GATEWAY_RATE_LIMIT_ENABLED=true`.

### Tooling and process

15. Anything that bypasses the guard programmatically (page-budget/lighthouse scripts, e2e harnesses) must inject the **current** hint-cookie name, tied to `HINT_COOKIE` in `session.ts` as the source of truth - hardcoded drift here is how regressions recur.
16. Live gates tolerate availability blips (bounded retry for Render cold-start/deploy-swap transient 5xx, paced under the auth limiter) but treat 4xx, wrong outcomes, CORS-echo mismatch, and retry-window exhaustion as hard failures - a deploy in flight is not a regression, but broken CORS/auth is.
17. Render deploys only via the deploy hook after migrations (`autoDeploy: false` in `render.yaml`); Vercel builds may briefly race the migration, so the frontend tolerates a transient 500 envelope with bounded retry.
18. No CSRF layer exists **by design**: auth rides `SameSite=Strict` + Bearer headers, not ambient cookie auth. Do not "fix" the missing CSRF config or add `CSRF_TRUSTED_ORIGINS` assumptions without revisiting `ADR-0005` and this ADR.

## Consequences

- New work on auth/session/CORS/middleware starts from this file: `CONTEXT.md`'s build-session protocol and the API standard route here before edits.
- If the topology ever consolidates to a same-origin VM, revisit rules 3-5 (the hint cookie becomes redundant but harmless) and rule 10 (origins collapse to one); rules 8-9 remain correct either way.
- Incident archaeology lives here so it is not rediscovered in production: #119, #142, #159, #208; cookie mechanics in the `ADR-0005` amendment.
