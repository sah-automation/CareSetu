# Brief - 302 Operator login via hidden role=operator URL param (Phase 5 auth fixes)

**Ticket:** #302 · **Parent:** #299 · **Refreshed:** 2026-09-04
**Reading surface:** ~5.5K tokens novel (budget 10K) - within budget

## Scope

The staff login page shows two clean, separate flows instead of one form that morphs fields while you type:

- **Default** (`/staff/login`): email + password fields only, for partners (doctor / lab / chemist). No phone, no TOTP.
- **Operator** (`/staff/login?role=operator`): phone + TOTP fields only, for internal team members.

Today the form switches to operator (phone + TOTP) mode the moment any character is typed into the phone field, making partner email/password login impossible and exposing the TOTP field to partners. The subtitle also mentions "operator" alongside the partner roles.

- [ ] The login page reads `role` from the URL search params and passes it to the form; default (no param) is partner mode.
- [ ] Partner mode renders only email + password; operator mode (`role=operator`) renders only phone + TOTP; no field appears/disappears while typing.
- [ ] The phone-typed `isOperatorMode` switching logic is removed; the operator login flow (login -> `SESSION_MFA_REQUIRED` re-verify step -> post-login routing) still works unchanged in operator mode.
- [ ] Form validation rules follow the mode: partner requires email + password, operator requires phone + TOTP.
- [ ] The login subtitle no longer mentions operators (EN + Hindi); partner roles only.
- [ ] New tests assert field visibility per mode via test ids; existing login and validation tests still pass.
- [ ] Full frontend unit suite passes.

## Read-list (in order)

1. **Staff login page** - reads `useSearchParams`, composes `StaffLoginForm`, renders the subtitle. Add `searchParams.get("role")` and pass `role` (default `"partner"`) as a prop to the form. (~1K tokens)
2. **Staff login form component** - where the mode switch must land. Current `isOperatorMode` (line ~210) derives from `phone.trim().length > 0 && !isMfaStep`; replace with a `role` prop (`"partner"` default / `"operator"`). Branch field rendering (the non-MFA branch) so partner mode shows only the email + password block and operator mode only phone + TOTP. The `handleSubmit` operator path (login -> `SESSION_MFA_REQUIRED` -> masked re-verify step -> post-login routing) stays untouched; the partner path keeps the honest phase5 placeholder. (~2.5K tokens)
3. **Login validation helper** - `validateStaffLogin` currently detects operator mode from a non-empty phone field (line ~49). Mode must instead follow the `role` prop: operator mode requires phone + TOTP, partner mode requires email + password. Signatures change so the caller passes the mode. (~1K tokens)
4. **Login form + validation unit tests** - existing tests cover phone-typed switching, operator flow, and validation rules; they will need updating to the role-prop contract and new field-visibility assertions (partner shows no phone/TOTP test ids; operator shows no email/password test ids). (~1K tokens)
5. **Login string dictionary** (EN + Hindi `staffAuth.login` subtitle) - remove the operator mention from `subtitle` in both locales; bureaucratic parity is compile-time enforced. (~0.3K tokens)

## Do NOT read

- The registration wizard, backend IAM modules, the proxy, API clients, archives.
- Do NOT wire partner email+password to a backend - it stays a Phase 5 placeholder by design (out of scope).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 58 files / 617 tests pass. Note: the process exits 1 on a _pre-existing_ teardown-timing error in `channels.test.tsx` ("window is not defined" after environment teardown, an uncleared timer). That file is unrelated to this ticket; ignore its teardown error, your suite must remain green otherwise.

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend -- src/components/auth/staff/StaffLoginForm.test.tsx src/components/auth/staff/staffLoginState.test.ts src/app/staff/login/page.test.tsx` - mode rendering + validation tests pass.
- `npm run typecheck:frontend` - role prop plumbing and dictionary parity compile.
- `npm run test:unit:frontend` - no new failures.

## Handoff notes

- The operator flow must keep working _verbatim_: phone + TOTP login, `SESSION_MFA_REQUIRED` transitions to the masked re-verify step, then `postLoginTarget` routing. Do not alter `completeStaffLogin`, `landAfterLogin`, or `envelopeNotice`.
- The `role` prop replaces the phone-presence heuristic in BOTH the form's render branch and `validateStaffLogin` - keep them consistent or mode rendering and validation will disagree.
- The page already wraps `useSearchParams` in a `Suspense` boundary, so reading `role` there is safe.
- On the operator redirect (#303) this param will be supplied by the proxy as `/staff/login?role=operator`; the `return` param must be preserved and forwarded as today.
