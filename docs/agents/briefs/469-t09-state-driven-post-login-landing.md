# Brief - 469 F014-T09 Frontend: state-driven post-login landing for partners

**Ticket:** #469 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

After a partner logs in they land on the screen that matches their state - waiting goes to the waiting screen, rejected goes to the reason screen, active goes to the partner home - and direct URL hits to the partner home behave the same way (sign in first, then land by state). A partner under verification can sit on their status screen because the session stays renewed, and a rejected partner reaches reason + appeal + resubmission. The routing seam already knows `partnerState`; this ticket drives it from the partner's own status after login (and covers direct deep links), so no partner is ever stranded except the deliberate suspended contact-support cut-off.

Acceptance criteria (verbatim from ticket):

- [ ] After partner login the landing is state-driven: `[Under Verification]` / `[Registered]` → waiting screen, `[Rejected]` → rejection-reason screen, `[Active]` → partner home.
- [ ] Direct URL hits to the partner home with no session redirect to login with a return target, and after sign-in still land by state (the return target does not force the wrong screen for a waiting/rejected partner).
- [ ] The waiting screen's status polling keeps working (session renewal keeps the partner seated); the rejected screen still offers appeal.
- [ ] Routing helper unit tests cover the state-driven matrix including the direct-hit path.

**Blocked by:** #467 (frontend partner login form) - the login flow that feeds this landing does not exist before it.

## Read-list (in order)

1. `apps/frontend/src/lib/auth/staff-routing.ts` (`postLoginTarget({ surface, roles, partnerState, returnTarget })`, `PARTNER_PENDING_ROUTE`, `PARTNER_REJECTED_ROUTE`, `ROLE_HOME`, `returnAllowed`) + `apps/frontend/src/lib/auth/return-url.ts` (`sanitizeReturnTarget`) - the routing seam; its staff branch already prefers `partnerState` over the return target, which is the matrix to verify/extend. (~1.5K)
2. The edge proxy `apps/frontend/src/proxy.ts` (Next 16 `proxy` convention; `config.matcher` on `/partner/:path*`) + its test - the unauthenticated deep-link 307 → `/staff/login?return=...` path that must round-trip ("sign in first, then land by state"). (~2K)
3. The partner status screens: `apps/frontend/src/app/(partner)/partner/status/pending/page.tsx` (polling at `STATUS_POLL_INTERVAL_MS`, self-redirects to `/partner` on Active / rejected screen on Rejected) and `.../status/rejected/page.tsx` (appeal CTA → `POST /v1/partner/appeal` → pending), plus the partner home stub `apps/frontend/src/app/(partner)/partner/page.tsx` and the `(partner)` AppShell layout. (~2.5K)
4. How `partnerState` is produced after login: read the `postLoginTarget` call sites in `StaffLoginForm`/`ProviderRegisterWizard` and `apps/frontend/src/lib/partner/api.ts` (`fetchPartnerMe`, `fetchPartnerVerification`) - the status source the landing is driven from; `AuthContext.tsx` (`fetchMe`/refresh cycle) only where it intersects the landing. (~1.5K)
5. Routing/proxy test prior art: `staff-routing.test.ts`, `return-url.test.ts`, `proxy.test.ts`, plus pending/rejected page tests and `app/staff/roles/page.test.tsx`. (~1.5K)

## Do NOT read

- Backend code, operator console, credential internals, `docs/archive/`, patient surfaces beyond incidental routing touches.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (936 passed on 2026-09-17), `npm run lint`, `npm run typecheck` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - routing helper tests cover the full matrix: registered/under-verification → pending, rejected → rejected, active → partner home, and the deep-link direct-hit path (no session → login with sanitized return; post-sign-in still lands by state).
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- `partnerState` currently travels as a literal at call sites (`"pending"`, `"rejected"`); this ticket must derive it after login from the partner's own status (`fetchPartnerMe`/status), not hardcode it. The `postLoginTarget` staff branch already prefers `partnerState` over `returnTarget` - keep that (the AC forbids the return target overriding the state landing for waiting/rejected partners).
- `partnerState` vocabulary maps: `[Registered]`/`[Under Verification]` → `"pending"`, `[Rejected]` → `"rejected"`, `[Active]` → partner home (no dedicated tenant needed).
- Suspended is NOT a `partnerState` today; the spec's suspended cut-off is a contact-support-only surface. If the status read (via `partner_role_status`/identity status on the frontend's `fetchMe`) reports suspended, the landing must show the contact-support surface, not half-working pages - keep that within this ticket's scope or explicitly flag it back to #460 if it needs a new route.
- The waiting screen polls status (`STATUS_POLL_INTERVAL_MS`) and self-redirects on state change - that polling + session renewal (#465) is exactly what seats a partner under verification; do not break the poll in this change.
- The proxy is `src/proxy.ts` (there is no `middleware.ts`). Direct-hit tests build a `NextRequest` directly (see `proxy.test.ts`).
