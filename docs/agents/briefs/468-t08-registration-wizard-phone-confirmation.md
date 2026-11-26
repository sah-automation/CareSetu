# Brief - 468 F014-T08 Frontend: registration wizard phone-confirmation step

**Ticket:** #468 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

Registering as a doctor, lab or chemist now confirms the phone with an SMS one-time code before the session is handed out - so the partner identity is created tied to a phone the applicant actually controls, from the first moment. The four-step registration wizard gains the phone-confirmation step between submit and landing: register → confirm phone (code shown in demo mode) → mint the partner session → land on the waiting screen. An existing partner's phone (duplicate resolution) simply re-verifies with a fresh code.

Acceptance criteria (verbatim from ticket):

- [ ] After the review step submits (`POST /v1/partner/register`), the wizard presents a phone-confirmation step (phone + code, mirroring the patient OTP pattern and demo banner) before any session is minted.
- [ ] Confirming the phone (partner verify route) then mints the partner session (partner session route) through the existing save path; a skipped/failed confirmation means no session and no partner home access.
- [ ] Refusal copy (cooldown / locked / suspended / wrong code) renders in English and Hindi.
- [ ] The wizard ends on the correct waiting-screen landing as today once confirmed.
- [ ] Component tests cover: confirm-then-mint order, no-session-on-failure, duplicate-phone re-verify, bilingual additions, demo banner.

**Blocked by:** #462, #463, #464 (partner OTP issue route, partner OTP verify + schema, tighten session mint) - the wizard's confirm step calls those routes and 04 makes the old mint-without-verify stop working.

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx` - the submit path (`handleSubmitPartner`: `registerPartner` → `issuePartnerSession` → `saveSession` → `submitCredentials` → `postLoginTarget`) that gains the confirm step, plus the step-slot rendering; and `providerRegisterState.ts` (`validateStep`, `hasStepErrors`, upload validation, `COUNCIL_OPTION_IDS`) for where a new confirmation step plugs into the state machine. (~4.5K)
2. The OTP pattern to mirror: `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx` + `otpState.ts` (`useOtpFlow`, `normalizePhone`, countdown/resend, demo banner via `NEXT_PUBLIC_DEMO_MODE` + `fetchDemoOtp`) - the confirmation step reuses these atoms. (~2K)
3. The API clients + save path: `apps/frontend/src/lib/partner/api.ts` (`registerPartner`), `apps/frontend/src/lib/auth/api.ts` (new partner login/verify + `issuePartnerSession`), `lib/auth/session.ts` (`saveSession`, `clearSession`). (~1.5K)
4. The dictionary `apps/frontend/src/lib/i18n/dictionaries.ts` `register` + `staffAuth` blocks (en ~L75-210, hi ~L1228-1350) + `dictionaries.test.ts` parity gate - the confirmation-step copy in both languages. (~1.5K)
5. Wizard test prior art: `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.test.tsx` ("calls registerPartner then issuePartnerSession then saveSession on successful submit"), `providerRegisterState.test.ts`, `app/staff/register/page.test.tsx`. (~2K)

## Do NOT read

- Backend code, operator flows, directory/credential internals, `docs/archive/`, patient record/consent UI.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (936 passed on 2026-09-17), `npm run lint`, `npm run typecheck` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - component tests assert confirm-before-mint, no-session-on-failure (mint not called when confirmation fails/skipped), duplicate-phone re-verify, bilingual parity, demo banner on the confirmation step, landing on the waiting screen after confirm.
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- The current submit path hands the session immediately after `registerPartner`. New order: `registerPartner` → phone-confirmation step (code shown in demo mode; wrong/expired/locked/suspended copy) → `verifyPartner` (new client call to `/v1/auth/partner/verify`) → `issuePartnerSession` → `saveSession` → `submitCredentials` (if the wizard still does) → `postLoginTarget` → waiting screen. #464 refuses to mint an unverified phone, so the confirm step is the only way to reach the session.
- Duplicate resolution: an existing partner's phone (same normalized number re-registered) resolves to the existing identity; the wizard just re-verifies with a fresh code - no re-registration UI, no duplicate account. The confirm step is the same for both cases.
- After the integration of #469, landing is state-driven; for THIS ticket the confirmed-landing target stays the waiting screen exactly as today (`postLoginTarget` with `partnerState: "pending"`).
- Refusal copy goes into `en` + `hi` and must pass the parity test; reuse the patient wizard's refusal copy verbatim where semantics match (cooldown/locked/suspended/wrong code).
- Do not touch the four-step wizard's existing validation or upload slots; the confirmation step slots in after review/submit, before mint.
