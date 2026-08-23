# Brief - T07 Per-role route groups & cookie-presence guards

**Ticket:** #198 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Routing structure and helpful guards: the single generic dashboard route group splits into per-role groups (patient / doctor / partner / operator), each wrapped by the shared AppShell; existing stub pages re-home into their groups. A new edge middleware performs cookie-presence checks only - no JWT parsing, per ADR-0005 - redirecting unauthenticated app-route hits to the group-correct entry point (patient wizard or staff login) while preserving a return-url so deep links never dead-end. Wrong-role/unauthenticated enforcement stays client-side UX; real authorization remains gateway RBAC.

E2E: the serial Playwright auth-loop suite hardcodes today's URLs and copy; update its route assertions in-ticket to keep CI green.

Acceptance criteria: see #198 body verbatim (groups under shared AppShell; redirect preserves return-url + completes post-auth; cookie-presence only; auth-loop green locally).

## Read-list (in order)

1. ADR-0005 - why middleware stays cookie-presence-only (~0.5K tokens)
2. UI blueprint §4.5 (post-login routing) + §3 guard patterns - entry-point mapping per role group (~1.5K)
3. Existing Next.js route middleware from Phase 2.5 (see brief `PHASE-2-5-T5-route-middleware.md`) - what exists to extend (~1K)
4. Current `(dashboard)` route-group layout + stub pages - what re-homes where (~1K)
5. E2E auth-loop spec (`tests/e2e/auth-loop.spec.ts`) - every hardcoded URL/copy assertion needing update (~2K)

## Do NOT read

- Split-auth prototype views (staff routing detail is ticket 10's), backend gateway internals, homepage prototype view, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests. E2E requires local backend (`npm run test:e2e` boots real frontend + mock-SMS backend) - run once pre-edit to capture your starting truth.

## Done-verify (acceptance criteria → commands)

- Baseline set + `npm run test:e2e` with updated auth-loop assertions
- New middleware unit coverage (cookie present → next(); absent → group-correct redirect with return-url param)
- Manual proof: signed-out hit to a deep app URL redirects, sign-in returns to original destination

## Handoff notes

- Return-url preservation must survive the patient OTP wizard flow end-to-end - assert it in the updated auth-loop spec.
- Staff login does not exist until ticket 10; the middleware's staff-group entry target should already point at `/staff/login` (404 until then is acceptable only if CI stays green - coordinate: land this before ticket 10 starts).
- Public carve-outs needed soon: `/staff/register` becomes public in ticket 11 - leave the matcher table easy to extend.
