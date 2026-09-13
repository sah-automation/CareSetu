# Brief - 02 Surface wrong-TOTP error and fix post-login redirect

**Ticket:** #296 . **Parent:** #294 . **Refreshed:** 2026-09-04
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

Two frontend fixes for the operator login flow:

**Wrong TOTP error display:** When an operator enters a wrong TOTP code, the form stays on the TOTP step and shows "Invalid authentication code. Please try again." instead of either silently re-entering MFA context (first submission) or showing the generic "Something went wrong" message (MFA re-entry step).

**Post-login redirect:** After successful operator login, the browser navigates to `/operator` instead of the form resetting to its initial state. Uses `window.location.replace` (full page reload) to ensure `AuthContext` re-reads the session from localStorage.

### Acceptance criteria

- [ ] Wrong TOTP on first submission shows "Invalid authentication code" and stays on TOTP step (does not silently transition)
- [ ] Wrong TOTP on MFA re-entry step shows "Invalid authentication code" (not generic error)
- [ ] Correct TOTP still logs in and navigates to `/operator`
- [ ] No brief flash of the login form after successful login
- [ ] `npm run test:unit:frontend` passes
- [ ] `npm run lint` and `npm run typecheck` pass

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` - lines 106-185: `landAfterLogin` function, both `.catch()` handlers (first submission at line 170, MFA re-entry at line 144)
2. `apps/frontend/src/components/auth/staff/staffLoginState.ts` - `staffOperatorErrorCopy` function (lines 108-123): add `INVALID_OPERATOR_CODE` case
3. `apps/frontend/src/lib/i18n/dictionaries.ts` - EN + HI `staffAuth.login` section (around lines 76-117): add `invalidOperatorCode` string
4. `apps/frontend/src/lib/auth/staff-routing.ts` - `postLoginTarget` function: confirms operator route is `/operator`
5. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx` - line 966: reference pattern for `window.location.href` post-login navigation

## Do NOT read

- Backend files (`apps/backend/`)
- Unrelated frontend modules
- Archives (`docs/archive/`)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Done-verify (acceptance criteria mapped to commands)

- `npm run test:unit:frontend` - existing tests still pass
- `npm run lint` - no lint violations
- `npm run typecheck` - tsc --noEmit passes
- Manual E2E: wrong TOTP shows "Invalid authentication code", correct TOTP redirects to `/operator`

## Handoff notes

- Depends on Ticket #295: the backend must return `INVALID_OPERATOR_CODE` for this ticket's frontend handling to trigger.
- The first-submission `.catch()` (line 170-183) currently transitions to MFA context on `SESSION_MFA_REQUIRED`. Add an `else if` for `INVALID_OPERATOR_CODE` that shows the error and stays on the same step. The existing `SESSION_MFA_REQUIRED` branch stays for MFA-not-enrolled.
- The MFA re-entry `.catch()` (line 144) just calls `setNotice(envelopeNotice(error))`. `staffOperatorErrorCopy` needs a new `case "INVALID_OPERATOR_CODE"` that returns the new i18n string. The `SESSION_MFA_REQUIRED` code should NOT hit this path (it is handled by the first-submission branch).
- For the redirect fix: replace `router.push(postLoginTarget(...))` with `window.location.replace(postLoginTarget(...))` inside `landAfterLogin` (line 109). `window.location.replace` is already the established pattern in `ProviderRegisterWizard` (line 966).
- The `StaffAuthStrings` type in `dictionaries.ts` (line 683) derives from the `Dictionary` type. Adding `invalidOperatorCode` to the EN and HI dictionary objects should automatically satisfy the type. Verify no type errors after adding.
