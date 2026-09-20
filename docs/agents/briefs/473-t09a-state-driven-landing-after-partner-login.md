# Brief - 473 F014-T09a Frontend: state-driven landing after partner login

**Ticket:** #473 - **Parent:** #469 - **Refreshed:** 2026-09-18
**Reading surface:** ~7.5K tokens (budget 10K) - within budget

## Scope

After a partner completes login they land on the screen that matches their own status instead of a generic staff home: a `[Registered]` / `[Under Verification]` partner lands on the waiting screen, a `[Rejected]` partner on the rejection-reason screen, an `[Active]` partner on the partner home. The landing seam (`postLoginTarget`) already knows `partnerState`; this ticket derives that state from the partner's own fetched status after login and feeds it in at every landing call site - the fresh-login path and the already-signed-in `/staff/login` visitor path. The waiting screen's status polling and the rejected screen's appeal flow keep working as the landing targets (regression, not new work).

Acceptance criteria (verbatim from ticket):

- [ ] After partner login the landing is state-driven: `[Under Verification]` / `[Registered]` -> waiting screen, `[Rejected]` -> rejection-reason screen, `[Active]` -> partner home.
- [ ] An already-signed-in partner visiting `/staff/login` routes by the same partner-state rule, not by role alone.
- [ ] The waiting screen's status polling keeps working (session renewal keeps the partner seated); the rejected screen still offers appeal.
- [ ] Routing unit tests cover the full status -> landing matrix including the already-signed-in path.

**Blocked by:** #467 (frontend partner login form) - the login flow that mints the session this landing reacts to.

## Read-list (in order)

1. `postLoginTarget` in `lib/auth/staff-routing.ts` (input includes `partnerState?: PartnerStatusState`; `PARTNER_PENDING_ROUTE`, `PARTNER_REJECTED_ROUTE`, `ROLE_HOME`; staff branch already returns the status route before any role/return rule) + `sanitizeReturnTarget` in `lib/auth/return-url.ts` - the routing seam. (~1.5K)
2. The landing call sites: `landAfterLogin` in `components/auth/staff/StaffLoginForm.tsx` (currently calls `postLoginTarget({ surface: "staff", roles })` with no `partnerState`) and the already-signed-in routing effect in `app/staff/login/page.tsx` (routes by roles/return only today); plus their tests `StaffLoginForm.test.tsx` and `app/staff/login/page.test.tsx`. (~2K)
3. The partner status vocabulary + status read: `fetchPartnerMe` / `PartnerMeView` / `PartnerStatus` (`Registered`, `Under Verification`, `Active`, `Rejected`) in `lib/partner/api.ts`; check `AuthContext.tsx` `fetchMe`/refresh only where it can supply partner status for the already-signed-in path, otherwise fall back to `fetchPartnerMe`. (~1.5K)
4. The landing targets as regression reference only - the waiting screen (`partner/status/pending` page, polls at `STATUS_POLL_INTERVAL_MS`, self-redirects on `Active`/`Rejected`) and the rejected screen (`partner/status/rejected` page, appeal CTA -> pending). Do not change them. (~1.5K)
5. `lib/auth/staff-routing.test.ts` - existing matrix cases pin the `partnerState` override for pending/rejected with roles only; extend, don't duplicate. (~1K)

## Do NOT read

- Backend code, operator console, credential internals, `docs/archive/`, patient surfaces, the edge proxy (owned by T09b), the partner home page beyond its existence as the Active landing target.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (964 passed 2026-09-18), `npm run lint`, `npm run typecheck` - all green this session.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - routing tests cover the full status matrix (registered/under-verification -> pending, rejected -> rejected, active -> partner home) and the already-signed-in `/staff/login` routing effect; `StaffLoginForm` landing test asserts a partner session lands by status.
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- `partnerState` vocabulary maps: `[Registered]` / `[Under Verification]` -> `"pending"`, `[Rejected]` -> `"rejected"`, `[Active]` -> no `partnerState` (normal role routing lands on the partner home).
- The operator branch of the staff login form and the registration wizard (`ProviderRegisterWizard` hardcodes `partnerState: "pending"`) are out of scope unless the AC forces it; the fresh-login partner path is the login form's partner OTP flow.
- Suspended is NOT a `partnerState` today; the spec's suspended cut-off is a contact-support-only surface. If the status read reports suspended, land on the contact-support surface, not half-working pages - flag back to #460 if it needs a new route.
- Do not break the waiting screen's poll (that + session renewal #465 seats a partner under verification).
