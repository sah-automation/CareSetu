# Brief - 288 Remove dead mfaEnrolled slot from StaffLoginForm

**Ticket:** #288 · **Parent:** phase5-frontend-review-fixes.md Fix 5 · **Refreshed:** 2026-09-03
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Delete the inert `mfaEnrolled` prop, its disabled MFA input slot, and any now-unused state/strings from StaffLoginForm. The real `SESSION_MFA_REQUIRED`-driven TOTP step is preserved. Dead dictionary copy removed.

- [ ] `mfaEnrolled` prop and disabled slot removed from StaffLoginForm
- [ ] Unused mfaEnrolled state/strings dropped from dictionaries
- [ ] Real SESSION_MFA_REQUIRED-driven TOTP step still works
- [ ] Tests: dead slot assertions removed, real MFA-step coverage kept

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` - Lines 44-46: `mfaEnrolled?: boolean` prop. Lines 397-422: disabled MFA input slot rendered when `mfaEnrolled` is true. The real TOTP step is driven by `SESSION_MFA_REQUIRED` (lines 129-141) - keep that. (~400 lines, ~8K tokens - read selectively, focus on the dead slot and MFA flow)
2. `apps/frontend/src/components/auth/staff/staffLoginState.ts` - check for any `mfaEnrolled`-related state or error copy. (~113 lines, ~2K tokens)
3. `apps/frontend/src/lib/i18n/dictionaries.ts` - search for `mfaEnrolled`, `mfaCodeLabel`, `mfaHelp` keys in the `staffAuth` section. Remove dead copy. (~1100 lines - grep only, don't read whole file)
4. Test files: `StaffLoginForm.test.tsx`, `staffLoginState.test.ts`

## Do NOT read

- partner modules, operator modules, doctor page, audit modules
- Backend modules

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - StaffLoginForm tests pass without dead slot
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source
- `npm run lint` - clean

## Handoff notes

- The `mfaEnrolled` prop is never set to `true` anywhere in the codebase - it's dead code.
- The real MFA flow is driven by `SESSION_MFA_REQUIRED` error code from the API, which triggers a state transition to the TOTP input step. That flow must be preserved.
- Check `StaffLoginForm.test.tsx` for any test assertions on `data-testid="mfa-slot"` or `data-testid="mfa-slot-input"` - those need to be removed.
