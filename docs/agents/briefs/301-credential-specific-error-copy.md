# Brief - 301 Credential-specific error copy for wrong logins (Phase 5 auth fixes)

**Ticket:** #301 · **Parent:** #299 · **Refreshed:** 2026-09-04
**Reading surface:** ~2.5K tokens novel (budget 10K) - within budget

## Scope

Operators who enter a wrong phone or TOTP get a clear "invalid credentials" style message instead of the current "Something went wrong on our side. Please retry." Users are guided to check their input rather than assume a system failure - and no raw error code leaks into the UI.

Today `SESSION_REFUSED` (409, from the operator login endpoint when the phone is unknown or the identity is not Active) falls through to the generic fallback string, and the default fallback itself still says "Something went wrong on our side."

- [ ] `SESSION_REFUSED` maps to the existing "Invalid credentials" copy, same as `INVALID_CREDENTIALS`.
- [ ] Any other/unexpected error code on the operator login path shows the credential-focused fallback ("Something went wrong, please check your credentials and try again") in both English and Hindi.
- [ ] The generic error message wording is updated (EN + Hindi) to the credential-focused text; no new i18n keys are introduced.
- [ ] The error-copy unit tests cover `SESSION_REFUSED` and the changed default; no raw code ever leaks to the UI copy.
- [ ] Full frontend unit suite passes.

## Read-list (in order)

1. **Staff login error-copy helper** (`staffOperatorErrorCopy` and `staffLoginErrorCopy` in the staffLoginState module) - the single place client-side login error codes map to dictionary copy. Add a `SESSION_REFUSED` case to each mapper (the operator mapper is the required one; the auth mapper for consistency), pointing at the existing `invalidCredentials` key, and change both `default` fallbacks from the generic key to the `invalidCredentials` key. (`~0.6K tokens`)
2. **Staff login error-copy unit tests** - covers `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED`, unknown codes never leaking, non-envelope throws. Extend for `SESSION_REFUSED` and the new default. (`~0.7K tokens`)
3. **Login string dictionary** (EN + Hindi `staffAuth.login`) - `invalidCredentials` stays as-is; `genericError` gains the credential-focused wording in both locales. Bilingual parity is compile-time enforced by the dictionary shape: both locales must change together or typecheck fails. (`~0.8K tokens`)

## Do NOT read

- The registration wizard, backend IAM routes, API clients, the proxy, archives.
- Do NOT change backend error emission (`SESSION_REFUSED` at 409 already exists and is correct).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 58 files / 617 tests pass. Note: the process exits 1 on a _pre-existing_ teardown-timing error in `channels.test.tsx` ("window is not defined" after environment teardown, an uncleared timer). That file is unrelated to this ticket; ignore its teardown error, your suite must remain green otherwise.

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend -- src/components/auth/staff/staffLoginState.test.ts` - error-copy tests pass, including `SESSION_REFUSED` mapping.
- `npm run typecheck:frontend` - dictionary parity holds across locales and the new case compiles.
- `npm run test:unit:frontend` - no new failures.

## Handoff notes

- The spec's expected fallback wording is "Something went wrong, please check your credentials and try again." (EN) with the Hindi given in the parent spec. Apply it to the `genericError` key in both locales; no new keys.
- `SESSION_MFA_REQUIRED` is deliberately NOT mapped here - the caller handles it as a state transition to the TOTP re-verify step, never as free copy. Leave that path untouched.
- This is a pure frontend copy change; the backend error envelope and codes stay as-is.
