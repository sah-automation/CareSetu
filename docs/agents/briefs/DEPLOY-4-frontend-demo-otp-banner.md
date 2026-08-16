# Brief - 118 DEPLOY-4 - Frontend demo OTP banner

**Ticket:** #118 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The demo read-back on the PWA: `fetchDemoOtp(phone)` calls `GET /v1/auth/dev/otp?phone=...` and returns the code (null on 404/error), and `PatientAuthWizard` renders a visible "Demo OTP: XXXXXX" banner after a successful register/resend when `NEXT_PUBLIC_DEMO_MODE === "true"` (inlined at build time). When the flag is absent the component behaves exactly as today - banner code inert, no extra network call.

Acceptance criteria (verbatim):

- `fetchDemoOtp` returns the code on 200, null on 404/error, and never throws to the caller
- With `NEXT_PUBLIC_DEMO_MODE=true`: banner appears after register and after resend with the fetched code
- Without the flag: no banner, no read-back call, wizard behaviour unchanged
- Frontend unit tests cover both flag states; `npm run test:unit:frontend`, `npm run typecheck:frontend` green

## Read-list (in order)

1. Plan §4.5, §4.6, §5.3 - the fetch function and banner contract, and the Vercel build-time inlining of `NEXT_PUBLIC_DEMO_MODE` (~0.6K).
2. `apps/frontend/src/lib/auth/api.ts` (whole) - the `post<T>` helper, error-envelope handling, and the existing `NEXT_PUBLIC_API_BASE_URL` inlining pattern to copy for the flag (~1.5K).
3. `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx` (whole) - the composition, where PhoneStep/OtpStep submit, and where the banner slots in (~3.5K).
4. `apps/frontend/src/components/auth/otp/otpState.ts` - ONLY the `OtpFlow` type and the `submitPhone`/`resendOtp` outcome fields the banner keys on (a successful register/resend); do NOT absorb the whole state machine (~1.8K).
5. `apps/frontend/src/components/auth/otp/PatientAuthWizard.test.tsx` - ONLY the fetch-mocking/setup conventions and one existing register/resend test, then add banner tests for both flag states (~1.5K).

## Do NOT read

- Backend internals beyond the `GET /v1/auth/dev/otp` contract, `otpState.ts` beyond the outcome slice above, the module CSS files line-by-line, other channels, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (currently 25 passed)
- `npm run typecheck:frontend` (currently clean)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - banner tests pass for both flag states; existing 25 tests stay green
- `npm run typecheck:frontend`, `npm run lint` - clean

## Handoff notes

- `NEXT_PUBLIC_*` env vars are inlined at build time; read the flag at module/render time as `process.env.NEXT_PUBLIC_DEMO_MODE === "true"`.
- `fetchDemoOtp` is best-effort by design: it must never throw into the auth flow - every failure path returns null (network error, 404, unreadable body), and a null simply suppresses the banner.
- The banner re-fetches the code after BOTH a successful register and a successful resend (the mock adapter keeps only the latest code per phone, so a stale banner would show an invalid OTP).
- The existing wizard tests mock the fetch layer; reuse that pattern - do not hit a real backend.
