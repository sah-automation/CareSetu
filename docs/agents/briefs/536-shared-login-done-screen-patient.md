# Brief - 536 Shared login done screen + patient flow

**Ticket:** #536 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

After a patient completes OTP verification the flow lands on a proper "verified" done screen instead of flashing blank: confirmation icon, informative copy, a visible 3-2-1 progress countdown with a progress indicator, and an always-available "Go to Dashboard" button that navigates immediately (US-1, US-2). The countdown starts only after the session-resume call succeeds, and the existing resume-then-redirect ordering plus the `?return=` target logic is preserved - only the in-between UX changes.

The done-screen component is shared: this ticket builds it and wires the patient flow; the doctor flow consumes it in a later ticket. All copy resolves through the typed EN/HI dictionary - no inline strings (US-33).

AC:

- [ ] A shared done-screen component renders the verified state with a progress countdown and an always-visible "Go to Dashboard" button
- [ ] Patient flow: the countdown starts only after session resume resolves; auto-redirect fires on 0 with the existing `?return=` target; clicking the button navigates immediately
- [ ] The blank-flash on the patient done step is gone (rendered component test covers the shown state, not a redirect race)
- [ ] EN/HI copy for every new string in the dictionary with parity; component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The patient auth wizard `DoneStep` in `components/auth/otp/PatientAuthWizard.tsx` - the current inline done state (icon + verified copy + Go home) that becomes the shared component, and the `resumeSession()`-then-redirect ordering it must preserve (~0.9K).
2. `components/auth/otp/otpState.ts` - the `useOtpFlow` machine the wizard stage drives; only the stage/"done" boundary matters (~0.3K).
3. The auth session seam: `resumeSession()` in `lib/auth/AuthContext.tsx` (the countdown's start gate) and `saveSession`/`clearSession` in `lib/auth/session.ts` (~0.6K).
4. The `?return=` logic: `RETURN_PARAM` + `sanitizeReturnTarget` in `lib/auth/return-url.ts` and its use in `app/login/page.tsx` (~0.4K).
5. Shared UI grains for the component: `EmptyState`, `Button` (`components/ui/button.tsx`), and the `CountdownRing` already used in the OTP wizard - the countdown/progress indicator can reuse or mirror it (~0.5K).
6. The typed i18n engine: `lib/i18n/dictionaries.ts` (surface-group structure, how a block is added, `useLang()`/`STRINGS[lang]` access, the `Dictionary = typeof en` typing) and `lib/i18n/dictionaries.test.ts` (parity enforcement, incl. function arity) (~1.5K).
7. Test prior art: `PatientAuthWizard.test.tsx` and `app/login/page.test.tsx` (rendered patient-flo w tests, not redirect races) (~1.2K).

## Do NOT read

- The doctor login flow internals beyond the dictionary seam (#537 owns it), backend code, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - done-screen rendered tests (shown state + countdown firing + immediate navigate) and dictionary parity suite green.
- `npm run typecheck` - clean (compile-time bilingual parity).

## Handoff notes

- No shared done-screen exists today (grep `DoneScreen`/`DoneStep` returns only inline diverging states) - this component is net-new and is the contract #537 consumes.
- Countdown fires only after `resumeSession()` resolves; that resolve also drives the `?return=` redirect target. The patient flow must not hard-reload (the #496 no-reload seam already lives in the wizard).
- i18n is typed-per-locale objects: add the block to `en`, mirror in `hi`, and let `dictionaries.test.ts` gate parity. Parameterized strings are functions; keep arity equal across locales.
- The 5-second countdown is a deliberate product decision in the parent spec ("opening your dashboard in 3...2...1").
- No em-dashes anywhere (lint-gated); use simple dashes.
