# Brief - 287 Fix operator login protocol - TOTP-only, no password-as-code

**Ticket:** #287 · **Parent:** phase5-frontend-review-fixes.md Fix 6 · **Refreshed:** 2026-09-03
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Fix the operator login form to send a 6-digit TOTP `code` (not a password value) on the first submit, matching the backend's `OperatorLoginRequest { phone, code }` contract where `code` must match `^[0-9]{6}`. The dead password field is replaced by a TOTP input. `SESSION_MFA_REQUIRED` still surfaces the re-verification step.

- [ ] First operator submit sends a 6-digit TOTP `code`, not the password field value
- [ ] Form labels and validation reflect TOTP (not password) on the operator path
- [ ] `SESSION_MFA_REQUIRED` two-step re-verification flow is preserved
- [ ] Non-6-digit codes are rejected client-side before hitting the API
- [ ] Tests: operator submit sends 6-digit TOTP code, non-6-digit rejected, SESSION_MFA_REQUIRED still surfaces TOTP step

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` - the form component. Line 158: `operatorLogin({ phone: rawPhone, code: password })` sends password as TOTP code. Lines 129-141: TOTP re-verification path. Lines 160-174: `SESSION_MFA_REQUIRED` handling. Lines 44-46: `mfaEnrolled` prop (separate fix #288). (~400 lines, ~8K tokens)
2. `apps/frontend/src/components/auth/staff/staffLoginState.ts` - `validateStaffLogin()` (lines 42-64): validates phone + password. `staffOperatorErrorCopy()` (lines 98-113): maps error codes. (~113 lines, ~2K tokens)
3. `apps/frontend/src/lib/operator/api.ts` - `operatorLogin()` function: sends `{ phone, code }` to `POST /v1/auth/operator/login`. `OperatorLoginRequest` type is already `{ phone, code }`. (~286 lines, ~5K tokens - read selectively, focus on operatorLogin)
4. Backend contract: `iam/adapters/routes.py` lines 109-118 - `OperatorLoginRequest` has no password field, only `{ phone, code }` where code is `^[0-9]{6}$` TOTP.
5. Test files: `StaffLoginForm.test.tsx`, `staffLoginState.test.ts`, `operator/api.test.ts`

## Do NOT read

- `apps/frontend/src/lib/partner/api.ts` (different auth path)
- `apps/frontend/src/lib/auth/api.ts` (different auth path)
- Backend modules beyond the route definition
- i18n dictionaries (unless adding new error copy)

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - StaffLoginForm tests pass with TOTP-first flow
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source
- `npm run lint` - clean

## Handoff notes

- **Blocked by #286** (shared fetch helper) - both touch `operator/api.ts`. Wait for #286 to land before starting.
- The backend `OperatorLoginRequest` at `iam/adapters/routes.py:109-118` accepts `{ phone, code }` where code must be exactly 6 digits. There is no password field. The current frontend incorrectly sends the password value as `code` on first submit.
- The `SESSION_MFA_REQUIRED` error code (returned when MFA is needed) triggers a state transition to a TOTP input step. Confirm whether the backend still emits this given there is no password step - the two-step flow may be unnecessary if the first submit already expects TOTP.
- `staffLoginState.ts` `validateStaffLogin()` currently requires a password for operator mode. This needs to change to require a 6-digit TOTP code instead.
