# Brief - 467 F014-T07 Frontend: partner login form (phone + OTP)

**Ticket:** #467 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The partner login page becomes real end-to-end: a returning doctor, lab or chemist lands on the one staff login page (partner side shown by default), enters their phone, receives the SMS code, completes login and is given their session - in English or Hindi. The dead email/password fields and the "staff authentication arrives in Phase 5" notice are gone. The interaction reuses the patient wizard pattern including the demo banner, and the polite no-account refusal points the caller to registration. The operator login stays exactly where it is today - reachable only by its explicit parameter or the internal-team footer link, never shown on the partner view. The operator flow is untouched.

Acceptance criteria (verbatim from ticket):

- [ ] Partner mode on the staff login page is phone → SMS-code, reusing the patient wizard's interaction pattern (phone step, code step, countdown/resend, demo banner showing the code in demo mode).
- [ ] The email + password fields and the "arrives in Phase 5" notice are removed from partner mode; the `?role=operator` entry and the internal-team footer link still reach the unchanged operator TOTP flow.
- [ ] On success the partner session is saved via the existing save path (access JWT + refresh handled, presence-hint cookie written) and the caller is routed onward; refusals render the right copy: cooldown, locked, suspended, and no-account-pointing-to-registration.
- [ ] All new copy exists in English and Hindi in the shared dictionary; the bilingual parity unit test covers the additions.
- [ ] Component tests cover: phone→code flow, demo banner, refusal copy, operator mode still present and unchanged, and that no patient surface is triggered by a partner login.

**Blocked by:** #462, #463, #464 (partner OTP issue route, partner OTP verify + schema, tighten session mint) - the backend routes this form calls do not exist before those land.

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` + `staffLoginState.ts` (`StaffLoginRole = "partner" | "operator"`, `validateStaffLogin`, error-copy helpers) + `apps/frontend/src/app/staff/login/page.tsx` (the `?role=operator` split) - the dead partner email/password placeholder that becomes the phone→code flow; the operator branch must stay byte-identical. (~4.5K)
2. `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx` + `otpState.ts` (the `useOtpFlow` state machine: `normalizePhone`, countdown/resend, `OTP_TTL_SECONDS`/`RESEND_COOLDOWN_SECONDS`/`MAX_ATTEMPTS`, demo banner gated on `NEXT_PUBLIC_DEMO_MODE === "true"` calling `fetchDemoOtp`) + `shared.tsx` UI atoms - the interaction pattern and demo banner to reuse for partner mode. (~4K)
3. The auth API client + session save: `apps/frontend/src/lib/auth/api.ts` (`issuePartnerSession`, `verifyOtp`/`registerPhone`/`resendOtp` shapes - new partner login/verify calls go here), `apps/frontend/src/lib/auth/session.ts` (`saveSession` writing `caresetu.access_jwt`/`caresetu.refresh_token` + the `caresetu_authed=1` hint cookie), and `lib/auth/staff-routing.ts` `postLoginTarget` for onward routing. (~2K)
4. The bilingual dictionary `apps/frontend/src/lib/i18n/dictionaries.ts` `staffAuth` block (en ~L75, hi ~L1228) + the parity test `dictionaries.test.ts` - new copy lands in both languages and passes the parity gate. (~1.5K)
5. Component test prior art: `apps/frontend/src/components/auth/staff/StaffLoginForm.test.tsx`, `staffLoginState.test.ts`, and `components/auth/otp/PatientAuthWizard.test.tsx` (demo banner uses `vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true")`). (~2.5K)

## Do NOT read

- Operator API internals beyond what the form already calls, partner-verification internals, backend code, `/docs/archive/`, anything outside the slim read-list above.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (936 passed on 2026-09-17), `npm run lint`, `npm run typecheck` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - updated/new component tests: phone→code flow, demo banner, refusal copy (cooldown/locked/suspended/no-account), operator mode unchanged, no patient surface triggered.
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- Naming drift: there is no `loginPartner`/`requestOtp` client function today. Partner backend routes (`/v1/auth/partner/login`, `/v1/auth/partner/verify`) arrive from #462/#463; the client additions should sit beside `issuePartnerSession` in `lib/auth/api.ts` and follow the existing request/`guardShape` conventions of `lib/request.ts`.
- The operator flow is protected: `?role=operator` + internal-team footer link keep routing to `operatorLogin` -> `completeStaffLogin` -> `postLoginTarget`, and the TOTP `SESSION_MFA_REQUIRED` step is untouched.
- Save path is the existing one: after a successful partner session, `saveSession(session, phone)` writes both tokens + the `caresetu_authed=1` hint cookie (SameSite=Lax, 30-day, Secure on https - ADR-0005 amendment), then `postLoginTarget({ surface: "staff", roles: ["partner"], partnerState })` routes by state (#469 drives state).
- The dictionary block for the patient wizard is named `auth` (not `patientAuth`); the staff block is `staffAuth`. New copy goes in both `en` and `hi`; the parity test walks both trees and fails on any divergence.
- Do NOT remove or rename the existing `staffAuth.login.phase5Notice` in a way that breaks other consumers until the replacement copy is live; the AC removes the notice from the partner UI, which may leave the key unused but present (check `tsc`/vitest for dangling references).
