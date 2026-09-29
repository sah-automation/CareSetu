# Brief - 580 Patient login: leave the handoff as soon as the session is resumed

**Ticket:** #580 · **Parent:** #577 (part of #529) · **Refreshed:** 2026-09-28
**Blocked by:** #578 (the shared handoff navigation hook - closed first)
**Reading surface:** ~6.6K tokens (budget 10K) - **PASS, comfortable**

## Scope

A patient who finishes OTP verification is taken to their home surface as soon as their session is ready, instead of being held for a fixed number of seconds after sign-in has already succeeded.

This flow's single precondition - the in-flow session resume has settled - plus its navigate routine go into #578's hook. **There is no destination read on this path**, so readiness is one signal where the partner flow's is a conjunction; that structural difference is the whole reason the hook takes a boolean rather than knowing about either flow. The "Go to Dashboard" button is wired to the hook's go-now callback rather than to the navigate routine directly, so a press mid-load is honoured at once but still never before the session is resumed.

Preserved exactly, only retargeted at the new contract: resume-before-route, the return target including a deep link, no double-navigation, and the handoff staying up while the resume is in flight.

## Acceptance criteria (from the ticket)

- [ ] The handoff is on screen while the session resume is in flight, with no countdown digits in the progress output.
- [ ] Nothing navigates while the resume is outstanding.
- [ ] Exactly one navigation, to the correct return target, the moment the resume settles - framework router, never a hard document replacement.
- [ ] The session is still resumed before the route is pushed.
- [ ] A deep-link arrival routes to the destination it was heading to; with no return target, the patient home.
- [ ] A destination that is ready almost immediately still gets a readable beat rather than a sub-second flash.
- [ ] A go-now press mid-load navigates as soon as the session is ready; a second press produces a single navigation.
- [ ] An already-stored session still routes straight to the return target without showing the form.
- [ ] The countdown is still present in the shared component at the end of this ticket.

## THE EXACT REGION TO CHANGE

`components/auth/otp/PatientAuthWizard.tsx` (344 lines - read it whole, it is small). **#578 lands first and does not touch this file.**

| #   | region                      | symbol                                                                     | what changes                                                                                                                                                                                                                                                                |
| --- | --------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | L300-306                    | `landOnReturnTarget`                                                       | **No change.** Read it. It is already correct: it latches on `landedRef` and navigates inside `resumeOnce().then(...)`. Unlike the partner routine, it has no destination refusal, so there is nothing to remove. This is the asymmetry with #579 and it is worth noticing. |
| 2   | L336-337                    | the `DoneStep` call site                                                   | `resumePending={!resumeSettled}` is the readiness boolean, exactly as it stands. `onGoToDashboard={landOnReturnTarget}` becomes the hook's **go-now callback**, not the navigate routine.                                                                                   |
| 3   | new, beside the state block | the hook call                                                              | One call, fed the readiness boolean from region 2 and `landOnReturnTarget` as the navigate routine. It is the _same shape_ as #579's, which is the point: the two flows now agree on what ready costs by construction.                                                      |
| 4   | L274-298                    | `resumeRef`, `landedRef`, `resumeSettled`, `resumeOnce`, the resume effect | **No change.** Read them, do not touch them.                                                                                                                                                                                                                                |

**`DoneStep` (L187-210) is a local pass-through component** that renders the shared handoff with dictionary copy and forwards the two host-owned signals. It already takes `resumePending` as a prop and will need to forward the go-now callback the same way. It is not a second handoff implementation - keep it a pass-through, and do not grow it.

**Two render-level bailouts are load-bearing and must not change:** the wizard returns nothing before hydration settles, and returns nothing when a session exists and the stage is not `done`. The second is what makes "an already-stored session routes straight to the return target without showing the form" true, and it is a different mechanism from the handoff. If you break it, an already-signed-in patient sees the handoff flash on every page load.

## THE TRAP - four countdown tests that all assert dead code

`DoneScreen` still owns a five-second countdown at the end of this ticket (#581 removes it, and #581 is blocked on this one and on #579). **The countdown is unreachable in this flow:** it cannot start until `resumePending` is false, readiness is what makes it false, and the hook then fires after a sub-second dwell from that same moment.

So the four `#551` tests in the success-and-session describe block - "shows the shared done screen, counts down, and redirects at zero", "holds the countdown back until the resume seam settles", "does not double-navigate when the CTA is pressed mid-countdown", and the resume-ordering test - are asserting the old contract. **Retarget them at the new one; do not delete them.** Two of them carry guarantees that must survive (no double-navigation, resume before route) and one carries the only assertion of the ordering invariant. Losing a test because its subject changed is how a regression gets in.

Their helper `fakeCountdownClock` (~L163) fakes **only** `setInterval` and `clearInterval`, with a `tick(ms)` helper. The hook's dwell will be scheduled with a _different_ timer (`setTimeout`), so **faking only `setInterval` means the hook's timer will not advance under this harness.** The single most likely way to get this ticket wrong is to retarget a test, watch the navigation never fire, and "fix" it by deleting the test. Widen the faked timer set to include `setTimeout`/`clearTimeout` and keep the assertions.

**Do not remove the countdown, do not re-tune it, and do not touch its stylesheet.** #579 is rewiring the partner consumer in parallel; #581 deletes the timer for both.

## Key facts / prior art - do not re-derive these

- **Resume-before-route is an invariant, not an implementation detail.** The navigate routine routes _inside_ `resumeOnce().then(...)`, so the identity is in state before the destination surface mounts. The reason is concrete: the provider remounting on the destination route wipes an in-progress completion-wizard draft. **Never invert this order**, and do not "simplify" it into a bare `router.replace`.
- **The resume seam never rejects**, which is why `.then()` is safe without a `.catch()` here, and why `landedRef` (not an error flag) is the once-only latch.
- **The flow's own `hydrated` flag is a third signal and it is not readiness.** It answers "has the stored session been read", not "is the fresh session resumable". Do not fold it into the readiness boolean; the bailouts use it and the handoff does not need it.
- **The handoff is mounted unconditionally on the terminal stage**, and has been since #563. There is no wrapper to drop and no blank-card flash left to fix here - that was #566 on the partner side and #563 on this one. The render is already a plain pass-through.
- **No facts on this path.** The shared handoff takes optional detail rows; the patient flow supplies none and never will (there is no practice to describe). Do not add any.
- **The handoff supplies its own `h1`**; the wizard's step heading is not in play here, and this ticket's criteria say nothing about heading count. Do not go looking for a heading problem to fix.
- **The demo banner, the phone step, the register refusal states, the verify step, the resend states, the language toggle and the sign-out path are all untouched.** They are in the same file and they are not yours.

## Read-list (in order)

1. **#580 itself** and the #578 brief - the rule the hook implements and the fresh-identity trap (~1.2K).
2. **`PatientAuthWizard.tsx` in full (344 lines)** - it is small enough to read whole and you are editing three regions of it. The parts that matter most: the `DoneStep` pass-through, the `returnTo` prop and its default, the already-authenticated effect, the state block, `resumeOnce`, the resume effect, `landOnReturnTarget`, the two render bailouts, and the terminal-stage render (~2.5K).
3. **`PatientAuthWizard.test.tsx`, four slices only (924 lines):**
   - L1-60 the header comment and imports - **the #563 note at the top explains why the fake owns only one function; read it before you widen the fake** (~0.5K)
   - L120-200 the flow helpers: `verifiedResult`, `enterPhone`, `startOtpFlow`, `typeOtp`, `verifyButton`, `fakeCountdownClock`, `tick` (~0.7K)
   - L564-760 the success-and-session describe block in full - **all four `#551`/`#496` tests you are retargeting, plus the already-stored-session test you must not break** (~1.6K)
   - L780-830 the return-url describe and its `completeFlowWithReturnTo` helper - the deep-link criteria live here and this block should need no change at all (~0.6K)
     (~3.4K)
4. **`components/auth/DoneScreen.tsx` L1-120** - the header comment, the duration constant, the props interface, and the tick plus auto-redirect effects. Enough to know what is still running underneath you; do not edit any of it (~1.0K).

**Total ~8.1K counting this brief's own ticket body; ~6.9K on the code. PASS** (budget 10K).

**Re-grep by name if any of these no longer resolves:** `DoneStep|landOnReturnTarget|resumeSettled|resumeOnce|landedRef|resumePending|returnTo|hydrated` in the wizard; `fakeCountdownClock|DONE_SCREEN_COUNTDOWN_SECONDS|const tick` in the suite. Then refresh this brief.

## Do NOT read

- **`StaffLoginForm.tsx` and its suite.** #579's file, being edited **in parallel with you**. Its `it` names are confusingly similar to yours, and reading it is a pure context switch. Everything you need about the partner flow's shape is in #577.
- **`PatientAuthWizard.test.tsx` whole.** 924 lines. The header comment, the eight helpers, the success-and-session block and the return-url block are all you need; the ~35 phone-step, refusal-state, verify-step, resend, banner, language and sign-out tests need not be read. **Grep by name if you change a shared helper** - they all use it.
- **`otpState.ts` beyond the `hydrated` and `session` fields.** It is the flow reducer, and this ticket does not change the flow's state machine at all.
- **The shared sign-in atoms and their suite, the registration wizard, the doctor shell, `doneScreen.module.css`, and every dictionary key except the handoff's.** The handoff's appearance is #581's; its copy is unchanged here.
- **The backends, migrations, `docs/adr/0007-*`.** No cookie, CORS, proxy-guard, `credentials` or deploy-env change, so the ADR-0007 hard gate does not apply. No API contract, no schema, no event, no session-transport change.
- **`staff-routing.ts` and its tests.** That is the partner matrix, not yours.
- **`docs/archive/`, the PRD, `internal-modules.md`, the roadmap, the UI blueprint, the other standards.** No architecture or requirement question is in scope. The behaviour is stated completely in the ticket.
- **The e2e specs.** They do not reference this screen.

## Baseline verify (must pass before the first edit)

- **Gate: #578 must be closed.** The full frontend suite must be green before this ticket's verdicts are trustworthy.
- **Recorded on 2026-09-28 at `acdb078`:** `npm run test:unit:frontend` is **1 failed / 1645 passed (1646)**. The single failure is the known unowned 5s load flake in `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx`, documented in #566's brief. **Not yours.** If a _second_ file fails, that one is yours.
- `npm run typecheck` and `npm run lint` - both clean at that commit.
- The fast loop, and the specific red this ticket is about:
  ```bash
  npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx --root apps/frontend
  # expect green, ~45 tests
  npx vitest run src/components/auth/DoneScreen.test.tsx --root apps/frontend
  # expect green, 8 tests - the component is not yours yet, so this must not move
  ```
- `git status --porcelain` - the untracked `docs/agents/briefs/*.md` files are pre-existing repo habit. Do not stage them.

## Done-verify (acceptance criteria -> commands)

```bash
npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx --root apps/frontend
npm run test:unit:frontend
npm run typecheck
npm run lint
```

Criterion by criterion:

- **AC-1 (up while in flight, no digits)** - with the resume held open, the handoff is on screen and the progress output carries no digits. Assert it **synchronously** - no `waitFor`, no `findBy`, no polling.
- **AC-2 (nothing while outstanding)** - the negative half: with the resume outstanding, advance well past the old duration and assert `mockReplace` was **not** called.
- **AC-3 (exactly one, correct target, router not reload)** - let the resume settle, assert `mockReplace` called once with the return target. Assert it is `mockReplace`, not a location assignment.
- **AC-4 (resume before route)** - assert the **ordering**, not just the destination. The existing `#496` test does this and is your template; keep it, retargeted.
- **AC-5 (deep link, and the fallback)** - the existing return-url block. **This block should need no change** - if you find yourself editing it, you have changed the return target rather than the handoff, which is out of scope. Both its "redirects to the returnTo prop" and its "falls back to /patient" cases must stay green untouched.
- **AC-6 (a readable beat, not a flash)** - assert the navigation is **not** synchronous with the resume settling: settle the resume, and the route has not been pushed yet; then advance the dwell and it has. This is the criterion that keeps the dwell from being optimised away later.
- **AC-7 (go-now honoured, once only)** - press go-now while the resume is outstanding: not called. Release the resume: called. Press again: the call count does not move. This is the retargeted form of the old mid-countdown CTA test.
- **AC-8 (already-stored session)** - the existing test at the end of the success block, unchanged and green. It is the negative case for the render bailouts.
- **AC-9 (the countdown is still there)** -
  ```bash
  git diff -- apps/frontend/src/components/auth/DoneScreen.tsx apps/frontend/src/components/auth/doneScreen.module.css
  # expect: empty. The component and its stylesheet are #581's, and the
  # stylesheet must not appear in your diff at all.
  ```
- And the wiring is one boolean, so read your own diff:
  ```bash
  git diff -- apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx
  # landOnReturnTarget, the resume effect, and both render bailouts must show
  # no behavioural change
  ```

## Handoff notes

- **This is the easier half of the pair, and the difference is structural.** The partner routine had a refusal to remove and a conjunction to build; this one has a single signal and a routine that is already correct. #579 has the defect, this ticket has the clean case. Do not import the partner's difficulty over here by analogy.
- **The `DoneStep` pass-through is a pass-through.** It exists so the wizard does not re-implement the handoff. Growing it into anything else is how the two flows start to drift, which is the one thing this refactor exists to prevent.
- **Widen the fake timer set; do not delete the tests that need it.** `fakeCountdownClock` fakes only the interval timers, and the hook's dwell is a timeout. If a retargeted test's navigation never fires, that is the fake - not a reason to drop the assertion. The old countdown is dead code, so a test that _passes because of the countdown_ is a test that has stopped testing anything.
- **The two render bailouts are not the handoff.** They are how an already-signed-in patient skips it. Both criteria 1 and 8 are unbreakable only while those two `return null`s stand exactly where they are.
- **Never invert resume-then-route.** It reads like a stylistic choice and it is a data-loss guard: the provider remounting on the destination route wipes an in-progress completion-wizard draft. The `#496` test is the reason it stayed.
- **Do not touch `doneScreen.module.css` or the countdown constant.** #579 is in the partner file in parallel, and #581 deletes the timer for both flows.
- **No em-dashes anywhere** in code, comments, or the commit message - the `no-em-dash gate` pre-commit hook enforces it and the codebase follows the rule in its own prose. Use simple dashes.
- **This brief is the contract.** Read it, not the world. Do not read the partner form, the shared atoms, the stylesheet, or the 924-line suite whole.
