# Brief - 475 Spec: land active doctor partners on /doctor after staff login

**Ticket:** #475 · **Parent:** none (spec ticket) · **Refreshed:** 2026-09-18
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

An `[Active]` doctor partner (partner whose `partner_type` is `doctor`) must land on the doctor console `/doctor` after a staff-surface sign-in, instead of the partner console `/partner`. "Doctor" is a partner type, not an `iam` role, so the routing reads `partner_type` from the existing `/v1/partner/me` response (`PartnerMeView`) and routes via partner type. Pending/rejected status screens still override; lab/chemist still land on `/partner`; multi-staff-role still lands on the scoped picker; the `?return=` deep-link territory is extended to `/doctor` for doctor partners; the unreadable-status path still degrades to role routing. No backend change.

Acceptance criteria (verbatim from ticket's User Stories):

- [ ] Active doctor partner lands on `/doctor` after staff login (fresh sign-in AND already-signed-in visitor on `/staff/login`).
- [ ] Status screens override the doctor rule: pending/under-verification doctor -> waiting screen, rejected doctor -> rejection screen (single and multi-role).
- [ ] Active lab and chemist still land on `/partner`; operator and multi-staff-role behaviour unchanged.
- [ ] `?return=` deep-link inside `/doctor` is honored for a doctor partner; `/partner/...` deep links keep working for doctor partners; pending/rejected status still beats the return.
- [ ] `fetchPartnerRouteState()` returns `partnerType` alongside `partnerState` from one `/v1/partner/me` read; on fetch error both degrade to `undefined` (role routing) with the existing logged path.

## Read-list (in order)

1. `apps/frontend/src/lib/auth/staff-routing.ts` - the whole seam: `partnerStatusToState`, `fetchPartnerRouteState` (must gain `partnerType`), `returnAllowed`, `postLoginTarget` (gains `partnerType` input, doctor branch, `/doctor` territory). (~1.5K)
2. `apps/frontend/src/lib/auth/staff-routing.test.ts` - the tabular matrix to extend: active doctor -> `/doctor`; lab/chemist -> `/partner`; pending/rejected override; multi-role; deep-link territory for doctor; `fetchPartnerRouteState` mapping + degradation. (~1.5K)
3. Landing call sites that both use `fetchPartnerRouteState` + `postLoginTarget` and must stay in lockstep: `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` (`landAfterLogin`) and `apps/frontend/src/app/staff/login/page.tsx` (already-signed-in effect). `ProviderRegisterWizard.tsx` (hardcodes `partnerState: "pending"`) is out of scope. (~1.5K)
4. `apps/frontend/src/lib/partner/api.ts` - `PartnerMeView`/`PartnerType`/`fetchPartnerMe` already carry `partner_type`; the routing reads it as-is. (`/v1/partner/me` returns it, confirmed by `isPartnerMeView`.) (~0.5K)
5. `apps/frontend/src/components/dashboard/types.ts` - `ROLE_HOME` already maps `doctor -> /doctor`; `STAFF_ROLES` derives from it (doctor included but never present in real session roles). (~0.3K)
6. Call-site tests: `app/staff/login/page.test.tsx` and `components/auth/staff/StaffLoginForm.test.tsx` (already-signed-in + landAfterLogin assertions) - extend, don't duplicate. (~1K)

## Do NOT read

- Backend code (no API change), operator console, credential internals, doctor console surface pages, `docs/archive/`, patient surfaces, `proxy.ts` (deep-link redirect already exists; `returnTarget` handling is unchanged on the proxy side).

## Baseline verify (must pass before the first edit)

- `npm run typecheck:frontend` - green this session (2026-09-18).
- `npm run test:unit:frontend` - **2 known pre-existing failures** (unrelated to this seam, confirmed in isolation): `src/app/page.test.tsx` (homepage EN/Hindi toggle parity) and `src/app/choose-role/page.test.tsx` ("redirects to /login when /v1/me fails"). 999 passed. These are the starting truth, not regressions from this ticket.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - routing matrix extends to active-doctor -> `/doctor`, lab/chemist -> `/partner`, status override, deep-link doctor territory; `fetchPartnerRouteState` maps status+type and degrades to `{ undefined, undefined }`. Failure count must stay exactly the 2 known baseline failures (no new ones).
- `npm run typecheck:frontend`, `npm run lint` green.

## Handoff notes

- `postLoginTarget` precedence order to keep: `pending` first, `rejected` second, then sanitized return inside territory, then single-role home (partner-type aware), then picker, then `/choose-role`. `partnerType` is consulted ONLY in the active/normal branch - never for pending/rejected.
- Doctor-ness is a `partner_type` attribute, never the `doctor` role string; real sessions hold `patient | partner | operator` only, so no session role change is involved.
- `fetchPartnerRouteState` returns `{ partnerState, partnerType }`; both call sites destructure it. `partnerType` when status read fails must be `undefined` so the lander stays on the lab/chemist-safe role path.
- `partnerType === "doctor"` extends `returnAllowed` territory to `/doctor` (in addition to the partner home). No change to the proxy's `/doctor/:path*` guard (already exists).
