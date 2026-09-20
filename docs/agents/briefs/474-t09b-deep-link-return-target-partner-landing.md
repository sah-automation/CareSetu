# Brief - 474 F014-T09b Frontend: deep-link return target for the partner landing

**Ticket:** #474 - **Parent:** #469 - **Refreshed:** 2026-09-18
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A partner (or staff member) who hits a staff-group deep link - e.g. the partner home - with no session arrives at `/staff/login` carrying a return target (the edge proxy already issues that redirect), then signs in and lands correctly: an `[Active]` partner, or a non-partner staff member inside their own territory, returns to the deep link, while a waiting/rejected partner still lands on their status screen. The return target must never force the wrong screen for a waiting/rejected partner. The `?return=` param is threaded through the post-login landing and the direct-hit round trip is verified end to end.

Acceptance criteria (verbatim from ticket):

- [ ] Direct URL hits to a staff-group route with no session redirect to `/staff/login` carrying a sanitized return target.
- [ ] After sign-in the return target is honored for an `[Active]` partner (and for non-partner staff inside their territory), but a waiting/rejected partner still lands on their status screen - partner state beats the return target.
- [ ] Routing/edge-proxy unit tests cover the direct-hit matrix including the return-target sanitize round trip.

**Blocked by:** #473 (T09a) - it consumes that ticket's status-derived `partnerState` to prove partner state beats the return target.

## Read-list (in order)

1. The edge proxy `src/proxy.ts` + `src/proxy.test.ts` - the unauthenticated deep-link redirect to `/staff/login?return=...` already lands here; it is baseline, not new code (own the round-trip tests). (~2K)
2. `sanitizeReturnTarget` / `RETURN_PARAM` / `PATIENT_HOME` in `lib/auth/return-url.ts` + `return-url.test.ts` - the shared sanitize contract the round trip must use. (~0.5K)
3. `postLoginTarget` in `lib/auth/staff-routing.ts` - the precedence order (partner state first, then return target inside owned territory) that makes "state beats return" true; `staff-routing.test.ts` - the existing cases already pin state override without a return; extend with the return+state matrix. (~2K)
4. The landing side of the round trip: the `?return=` read in `app/staff/login/page.tsx` and the post-login landing `landAfterLogin` in `components/auth/staff/StaffLoginForm.tsx` (which must thread the return target through) + both tests. (~2K)

## Do NOT read

- Backend code, operator console, credential internals, `docs/archive/`, patient surfaces, the partner status screens' internals (they are landing targets only), the registration wizard.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (964 passed 2026-09-18), `npm run lint`, `npm run typecheck` - all green this session.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - proxy direct-hit tests assert the sanitized return round trip; routing tests assert the combined matrix: return honored for active/territory-inside, status screens for pending/rejected even with a return present.
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- The proxy redirect already exists (307 to `/staff/login?return=`; operator group adds `role=operator`); the new work is the post-sign-in landing honoring the param plus the matrix tests.
- `postLoginTarget` sanitizes the target, then checks territory; partner state is checked BEFORE the return target - keep that order, it is the AC's guarantee.
- Direct-hit tests build a `NextRequest` directly (see `proxy.test.ts`); the proxy is `src/proxy.ts` (there is no `middleware.ts`).
- The already-signed-in `/staff/login` routing effect already passes `returnTarget`; the fresh-login path gains it here on top of T09a's `partnerState`.
