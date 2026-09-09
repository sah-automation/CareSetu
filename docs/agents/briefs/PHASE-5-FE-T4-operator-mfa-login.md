# Brief -- T4 Operator MFA login

**Ticket:** #282 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~5K tokens (budget 10K) -- within budget

## Scope

Wire the existing `StaffLoginForm.tsx` to the real operator login flow. Submit calls `POST /v1/auth/operator/login` (phone + TOTP). Surface the `SESSION_MFA_REQUIRED` (401) envelope as an MFA input step in the existing MFA slot. On successful auth: create session via `saveSession`, route via `postLoginTarget` in `staff-routing.ts`. Phone display stays masked per IAM convention. Keep email+password form fields for the partner staff login path per blueprint section 4.2.

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` -- 249 lines. Focus on: `handleSubmit` (~line 92-95, currently `setNotice({ kind: "phase5" })`), MFA slot stub (~line 92-95, renders when `mfaEnrolled` prop is true but nothing sets it), `Notice` type (`kind: "phase5" | "envelope"`, optional `traceId`). The form has `email` + `password` fields for partner staff login; operator login uses phone + TOTP.
2. `apps/frontend/src/components/auth/staff/staffLoginState.ts` -- `validateStaffLogin` function, field error types
3. `apps/frontend/src/lib/operator/api.ts` -- T1 output: `operatorLogin(phone, code)` function
4. `apps/frontend/src/lib/auth/api.ts` -- `SessionResult` interface (jwt, jti, scope, identity_id, expires_in_seconds, refresh_token), `MeResult` interface (subject_id, roles, phone)
5. `apps/frontend/src/lib/auth/session.ts` -- `saveSession(session, phone)`, `clearSession()`, `StoredSession` shape
6. `apps/frontend/src/lib/auth/staff-routing.ts` -- `postLoginTarget(input)`, `PostLoginInput` interface, `PartnerStatusState` type, `LoginSurface` type
7. `apps/frontend/src/lib/api-errors.ts` -- `ApiError`, `parseErrorEnvelope`, `extractTraceId`, `ErrorEnvelope`

## Do NOT read

- partner pages, patient pages, registration wizard, backend dispatcher, docs/archive/, prototype/.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- **T1 dependency**: `lib/operator/api.ts` must exist before this ticket starts.
- The form currently has `email` + `password` fields. For operator login, the user enters phone + TOTP code. Two approaches: (a) add a phone field alongside email (dual-mode form), or (b) detect operator login and show phone+TOTP fields. Blueprint section 4.2 shows the login form with conditional MFA slot -- keep the email+password for partner staff, add phone+TOTP for operator.
- The MFA slot is already stubbed in the form (renders when `mfaEnrolled` prop is true). Wire it: after phone+password submit, if the response is `SESSION_MFA_REQUIRED` (401), show the TOTP input. The MFA slot can be reused for this.
- `SESSION_MFA_REQUIRED` is the error code in the `ErrorEnvelope` when TOTP is missing/wrong. Check for this specific code in the catch block.
- After successful login: `saveSession(sessionResult, phone)` then route via `postLoginTarget({ surface: "staff", roles, partnerState? })`. The `roles` come from `MeResult` (fetch `/v1/me` with the new JWT to get roles).
- Phone masking: the backend masks phones server-side. The frontend should also mask when displaying (e.g., `+91XXXXXX1234`). Check if IAM already returns masked phones or if the frontend needs to mask.
- The existing `Notice` type can be extended with `{ kind: "mfa", message: string }` for the MFA step, or reuse `{ kind: "envelope" }`.
