# Brief - 471 F014-T11 E2E: partner register-and-login loop

**Ticket:** #471 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A browser-level proof of the whole partner leg: a doctor registers through the wizard, confirms the phone with the demo on-screen code, is signed into the partner surface, and - after closing and reopening the browser - logs back in with phone + SMS code into their own state-correct screen. The serial Playwright auth-loop spec is extended with this partner register-and-login loop, and the existing patient loop keeps passing (back-to-back, same session).

Acceptance criteria (verbatim from ticket):

- [ ] The serial Playwright auth-loop spec includes a partner flow: register → on-screen demo code confirmation → session → land on the correct self-service screen.
- [ ] The spec then "returns": partner logs out / closes, returns to the staff login, signs back in with phone + code in the partner side, and lands by state again.
- [ ] The existing patient auth loop still passes unmodified; the demo read-back (`NEXT_PUBLIC_DEMO_MODE`) drives the code entry for both roles exactly the same way.

**Blocked by:** #467 (frontend partner login form), #468 (registration wizard phone-confirmation step), #469 (state-driven landing) - the browser flows under test must exist first, with the backend from 02-06 live.

## Read-list (in order)

1. `tests/e2e/auth-loop.spec.ts` (327 lines, serial `describe.configure({ mode: "serial" })`, `test.setTimeout(120_000)`) - the shared-phone/random-phone helper, `startRegistration`, `readMockOtp` (GET `http://localhost:8000/v1/auth/dev/otp?phone=+91...`), `verifyOtp`, the demo-banner literal assertion (`/^Demo OTP: \d{6}$/`), and the patient loop shape to extend with the partner loop. (~4K)
2. `playwright.config.ts` - demo-mode env seeding: frontend webServer with `NEXT_PUBLIC_DEMO_MODE: "true"`, backend webServer (`scripts/e2e-backend.cjs`) with `APP_ENVIRONMENT=test`, `SMS_PROVIDER=mock`, `GATEWAY_*` overrides; the `/health` + `/` probes; `tests/e2e/patient-journey.spec.ts` as the second serial-loop prior art. (~1.5K)
3. The frontend flows under test from #467-469 (partner login form phone→code, wizard confirm step, state-driven landing) - read their briefs 467-469 in this folder + skim the components only where the selector/copy literals matter. (~1.5K)

## Do NOT read

- Backend internals, `docs/archive/`, unit-test internals, operator console, anything outside the e2e + login/wizard/landing surface.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (936 passed on 2026-09-17), `npm run lint`.
- E2E itself needs the dev servers live; `npm run test:e2e` (Playwright, browsers from the shared cache per `D:\Dev\tools\README.md`). Run the auth-loop spec file to certify the patient loop is green BEFORE editing it, and again after the partner loop is added.

## Done-verify (acceptance criteria → commands)

- `npx playwright test tests/e2e/auth-loop.spec.ts` green with the new partner loop and the unchanged patient loop.
- `npm run lint` green.

## Handoff notes

- Certify the patient loop green first (baseline), then ADD the partner loop to the SAME serial describe - the AC requires the existing patient loop to pass unmodified, back-to-back with the new partner flow in one session.
- Demo read-back parity means NO new demo plumbing for partners: the mock SMS read-back (`/v1/auth/dev/otp`) is phone-keyed and the demo banner surfaces the code the same way for both roles - the partner loop should reuse `readMockOtp` and the same selectors.
- The "returns" leg simulates a returning partner: end the partner sign-in (persist the phone), open a fresh context (browsers do not leak sessions per the existing per-test-context pattern), go to `/staff/login`, sign in on the partner side with phone + code, and assert the state-correct landing (waiting screen for a not-yet-activated doctor).
- Demo banner copy is byte-stable (pinned literal) - if the partner banner must differ, do not change the shared literal; keep both roles rendering `/^Demo OTP: \d{6}$/`.
