# Brief - 537 Doctor login done screen

**Ticket:** #537 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A doctor (partner) who verifies their login code gets a real done screen - confirmation with practice info and destination - instead of the current empty card and a hard page reload (US-3, US-4). The flow resolves its routing target first and, for an Active partner landing on the console, renders the shared verified done screen with the countdown and a "Go to Dashboard" button, then navigates with the framework router (no hard replace). Pending and rejected partners bypass the done screen entirely and land straight on their verification status screens as today (US-5, from ADR-0016 post-login routing). Outline order and existing destination logic are preserved.

AC:

- [ ] Active doctor: verify resolves the destination first, then the done screen renders (icon, practice/branding copy, countdown, Go to Dashboard), navigating via the framework router
- [ ] Pending/rejected partner: routed immediately to their status screen, never shown the done screen
- [ ] No hard page reload in the active path
- [ ] EN/HI copy for every new string with parity; rendered component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The shared done-screen component from #536 (the shipped `DoneScreen` + its i18n surface) - what the doctor flow renders for active landings; conform to what shipped (~0.4K).
2. The staff login form in `components/auth/staff/StaffLoginForm.tsx` - the partner SMS-OTP branch, `landAfterLogin()` (currently `window.location.replace` at the done stage), and the current `stage === "done"` empty-card render that becomes the done screen (~0.8K).
3. The partner flow state machine `components/auth/staff/partnerLoginState.ts` - the stage that mints the session (`issuePartnerSession`, ADR-0016 routes) and reaches "done" (~0.7K).
4. The post-login routing matrix in `lib/auth/staff-routing.ts` - `postLoginTarget()` order (partner status override: pending/rejected to status screens, then `?return=` inside owned territory, then single-role doctor home, then role picker); `partnerStatusToState`/`fetchPartnerRouteState` (~0.9K).
5. The partner status screens `app/(partner)/partner/status/pending` and `rejected` (with their tests) - the bypass destinations that must remain reachable without the done screen (~0.6K).
6. The i18n story: the `doctorConsole`/`staffAuth` dictionary block (how the practice/branding copy lands) + `dictionaries.test.ts` parity (~0.7K).
7. Test prior art: `StaffLoginForm.test.tsx` and `lib/auth/staff-routing.test.ts` (~1K).

## Do NOT read

- Patient login's internal flow (#536 owns the shared component usage; the wizard internals only matter via the shipped component), backend code, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - doctor done-screen rendering, pending/rejected bypass, no-hard-reload tests green.
- `npm run typecheck` - clean (bilingual parity).

## Handoff notes

- The hard reload lives in `StaffLoginForm.landAfterLogin()` today; the active path must move to the framework router with the same `postLoginTarget()` result.
- Routing target resolves before the done screen renders (Active console landers only); pending/rejected never touch the component.
- Practice/branding info on the done screen comes from the partner session/profile data already available after `fetchPartnerMe`; no new backend call in this ticket.
- The i18n additions extend the shared done-screen surface from #536; keep EN/HI arity-equal.
- No em-dashes anywhere (lint-gated); use simple dashes.
