# Brief - T6 Frontend - Login page with role-based redirect

**Ticket:** #152 - **Parent:** #146 Phase 2.5 - **Refreshed:** 2026-08-17
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Extract the existing phone+OTP auth flow from `PatientAuthWizard` into a dedicated `/login` route. The login page handles both registration and login (same phone+OTP flow). On successful session issuance: reads role from response, redirects to `/{role}` dashboard. If user is already authenticated (valid cookie/session), redirects to their dashboard instead of showing the login form. Preserves en/hi i18n support from the existing wizard.

Acceptance criteria (verbatim):

- `/login` route renders the phone+OTP auth flow
- Phone input, OTP verification, and session issuance work end-to-end
- On successful login: redirects to `/patient` (single role for now)
- If already authenticated (valid session in localStorage + cookie): redirects to `/{role}` without showing login form
- Language toggle (en/hi) works, matching existing wizard behavior
- `AuthenticatedHome` sub-component removed from PatientAuthWizard (moves to dashboard in Ticket 8)
- `PatientAuthWizard.test.tsx` updated to reflect extraction (tests still pass)
- `npm run test:unit:frontend` passes

## Read-list (in order)

1. `src/components/auth/otp/PatientAuthWizard.tsx` (330 lines) - the full wizard component: PhoneStep, OtpStep, DoneStep, AuthenticatedHome sub-components; understand the component tree and what gets extracted (~4K tokens)
2. `src/components/auth/otp/otpState.ts` (599 lines, read the `useOtpFlow` hook signature and `StoredSession` type) - the state machine hook that drives the OTP flow; the login page re-uses this hook directly (~2K tokens)
3. `src/components/auth/otp/shared.tsx` (200 lines) - reusable atoms: `BrandHeader`, `LangToggle`, `PhoneInput`, `OtpInput`, `ErrorMessage`, `NoticeMessage`, `PrimaryButton`, `GhostButton`; the login page composes these (~1.5K tokens)
4. `src/lib/auth/api.ts` (138 lines) - `registerPhone`, `verifyOtp`, `issueSession` functions; the login page calls these on successful OTP verification (~1K tokens)
5. `src/lib/auth/session.ts` (50 lines) - `saveSession`, `readSession`; the login page calls `saveSession` after successful auth (~0.5K tokens)
6. AuthContext API (from T3 output) - the `isAuthenticated` check for redirect-away-when-already-logged-in (~0.3K tokens)

## Do NOT read

- Backend code, dashboard components (T8), icons.tsx, other modules, PRD, roadmap.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (2 files pass, 2 pre-existing failures)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - existing wizard tests + new login page tests pass
- Manual: visit `/login`, complete phone+OTP flow, land on `/patient`
- Manual: visit `/login` while authenticated, get redirected to `/{role}`

## Handoff notes

- The `PatientAuthWizard` currently contains `AuthenticatedHome` (shown after successful login). This sub-component moves to the dashboard layout in T8. For T6, after successful login, redirect to `/patient` instead of showing `AuthenticatedHome`.
- The `useOtpFlow` hook from `otpState.ts` is self-contained - it manages phone state, OTP state, timers, and API calls. Import and use it directly in the login page component.
- The `PatientAuthWizard.test.tsx` (615 lines) tests the full wizard including `AuthenticatedHome`. After extracting the login flow, some tests may need adjustment - the wizard tests should still cover the OTP logic, but the `AuthenticatedHome` assertions may need removal or mocking.
- The `/login` route should be a client component (`"use client"`) since it uses hooks and state.
- Language toggle: reuse `LangToggle` from `shared.tsx`; the i18n strings are in `otpState.ts`.
- For the "already authenticated" check: use AuthContext's `isAuthenticated` (from T3). If T3 is not yet merged, fall back to checking `readSession()` from `session.ts` and cookie presence.
