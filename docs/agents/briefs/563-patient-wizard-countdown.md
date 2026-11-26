# Brief - 563 Repair the patient wizard done-screen countdown failures

**Ticket:** #563 · **Parent:** #560 (front five defects, part 2 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #561 (the frontier pre-flight; its recorded baseline is the reference for "was it red before")
**Reading surface:** ~7.8K tokens (budget 10K) - within budget

## Scope

Make `src/components/auth/otp/PatientAuthWizard.test.tsx` green so the frontend unit suite is green before anyone touches anything else. Two failures, and the ticket insists they are not the same fault: one reproduces in isolation (pressing the done screen's CTA mid-countdown does not navigate), the other only fails in a full-suite run and is the batch's one claimed cross-file pollution. Both must be fixed at their cause.

**A red suite makes every downstream red/green verdict meaningless, and the patient wizard is the reference implementation the partner OTP redesign is being rebuilt on** - so it has to be trustworthy before it becomes a template. #563 is repairing, not recording-as-known-failing, despite the spec allowing the latter.

**Almost certainly a test-harness repair, not a production change.** See the Prefactor section: both failures are explained by the suite's partial timer fake disabling `@testing-library`'s ability to re-poll. AC-5 still holds - if you do find a genuine product defect, state it explicitly rather than folding it in silently.

AC:

- [ ] Both done-screen countdown failures pass, in isolation and as part of a full frontend unit run.
- [ ] The full-suite-only failure is diagnosed and fixed at its cause, not papered over by test ordering or a skip.
- [ ] The countdown tests that already pass (the countdown-at-zero case, the resume-seam-holds case, the clear-on-unmount case) still pass, unchanged in what they assert.
- [ ] A verdict on "the frontend unit suite is green" is meaningful: zero failures, zero skipped tests added to reach it.
- [ ] No production behaviour change unless a genuine product defect is found, in which case it is stated explicitly rather than folded in silently.

## Read-list (in order)

1. **Issue #563 itself** - the five AC above. Its read-list hint ("grep for the failing test names first, do not read the suite whole") is why this list is sliced (~0.7K).
2. **`PatientAuthWizard.test.tsx` L16-70 - the module-level mock block** (~0.6K). The `@/lib/auth/api` factory (an `importOriginal` spread replacing six functions), the `vi.hoisted` `state.resumeSession`, the `@/lib/auth/AuthContext` mock that hands it to `useAuth`, and the `next/navigation` mock that produces `mockReplace`. Note there is **no** mock of `@/lib/auth/staff-routing` and **no** `fetchMe` here - the patient surface does not touch the staff-routing seam.
3. **`PatientAuthWizard.test.tsx` L107-166 - the flow helpers and the clock harness** (~0.6K). `enterPhone`, `startOtpFlow`, `typeOtp`, `verifyButton`; then **`fakeCountdownClock()` (L139-141) and `tick()` (L144-148)** - the two functions at the heart of the ticket; then `afterEach` (L150-153) and `beforeEach` (L155-166). Read the `afterEach` and `beforeEach` line by line: the AC-2 diagnosis depends on exactly which mocks are reset and which are not.
4. **`PatientAuthWizard.test.tsx` L551-592 and L642-671 - the two failing tests, whole** (~0.8K). `shows the shared done screen, counts down, and redirects at zero (#551)` and `does not double-navigate when the CTA is pressed mid-countdown (#551)`. Both use `try { ... } finally { vi.useRealTimers(); }`.
5. **`PatientAuthWizard.test.tsx` L594-640 and L673-712 - the three #551 tests AC-3 protects** (~0.9K). `holds the countdown back until the resume seam settles (#551)`, `awaits the session-resume seam before routing to the return target (#496)`, and the clear-on-unmount case inside the second of those. Read them so you know the exact assertions you must not weaken.
6. **`PatientAuthWizard.tsx` - named regions only, not the whole 381-line file (~0.9K):**
   - L227-245, the `DoneStep` prop contract (`resumePending`, `onGoToDashboard`).
   - **L301-343, the whole post-login landing block** - `resumeRef`, `landedRef`, `resumeSettled`, `resumeOnce`, the release effect at L322-335, and `landOnReturnTarget` at L337-343. This is the production machinery both failing tests are asserting about, and the comment at L301-314 states the contract in words.
   - L369-376, the `DoneStep` call site that passes `resumePending={!resumeSettled}` and `onGoToDashboard={landOnReturnTarget}`.
7. **`apps/frontend/src/components/auth/DoneScreen.tsx` (162 lines - read whole)** (~1.4K). The prior art and the contract. Note the header comment, `DONE_SCREEN_COUNTDOWN_SECONDS = 5` (L27), `departedRef` (L78), the `depart` callback (L85-92), the tick effect (L96-106) and the auto-redirect effect (L109-114). This component is **correct and does not change**; it is what the wizard tests are measuring.
8. **`apps/frontend/src/components/auth/DoneScreen.test.tsx` (178 lines - read whole)** (~1.5K). The other half of the prior art, and the shape to converge on. Its `afterEach` is `cleanup(); vi.useRealTimers();`. Every countdown test uses **full** `vi.useFakeTimers()` and an `advance(ms)` helper built on `act(async () => vi.advanceTimersByTimeAsync(ms))` - which is the same `tick` shape the wizard file already has. It asserts the countdown-at-zero, the resume-seam-holds, the no-double-navigate and the clear-on-unmount cases in isolation, all green. Compare its harness to read-list item 3 and decide why one file's countdown tests are reliable and the other's are not.
9. **`apps/frontend/vitest.config.ts`** (20 lines, read whole) - no global mock-lifecycle option; `environment: "jsdom"`, `setupFiles: ["./vitest.setup.ts"]` (~0.2K).
10. **A six-line grep of the installed testing-library, not a read of the library (~0.2K):** in `node_modules/@testing-library/dom/dist/wait-for.js`, the two lines that matter are `if (!(0, _helpers.jestFakeTimersAreEnabled)()) { intervalId = setInterval(checkRealTimersCallback, interval); }` and the adjacent `observer = new MutationObserver(checkRealTimersCallback)`. In `node_modules/@testing-library/dom/dist/helpers.js`, `jestFakeTimersAreEnabled()` returns `setTimeout._isMockFunction === true` - i.e. it probes **`setTimeout` only**. These six lines are the mechanism behind both failures; do not read the rest of either file.

**Re-grep by name if this no longer resolves:** `fakeCountdownClock`, `toFake`, `advanceTimersByTimeAsync`, `DONE_SCREEN_COUNTDOWN_SECONDS` in `PatientAuthWizard.test.tsx`; `landOnReturnTarget`, `resumeOnce`, `resumeSettled` in `PatientAuthWizard.tsx`. If `fakeCountdownClock` no longer passes `toFake: ["setInterval", "clearInterval"]`, the root cause below has already been changed - re-derive from the red output.

## Do NOT read

- **`PatientAuthWizard.test.tsx` whole.** 882 lines. The mock block, the clock harness, and the five countdown tests are the whole ticket. The phone step, the three register-refusal states, the verify step, the four resend-refusal states, the demo-OTP banner and the sign-out test all pass and are not your business - grep them by name if you change a shared helper like `startOtpFlow`.
- **`src/components/auth/staff/StaffLoginForm.test.tsx`** - a separate ticket (#562) with ten failures of its own. It has a test named `does not double-navigate when the CTA is pressed mid-countdown (#551)`-adjacent wording and a _different_ `DoneScreen` test with the same intent; conflating the two files is the easiest wrong turn here.
- **The partner OTP step and `providerRegisterState.ts` / `partnerLoginState.ts`** - later tickets in the #560 cut. Nothing in this ticket reaches them.
- **`src/components/auth/otp/otpState.ts` (438 lines), `shared.tsx`, `variantB.module.css`, the i18n dictionaries.** The failures are about _when_ a state lands, not what the state machine contains. `otpState.ts` is the file a fresh agent is most tempted to read and the one that tells them nothing.
- **The backends, `apps/backend/**`, migrations, `docs/adr/0007-\*`.** No cookie, CORS, proxy-guard, `credentials` or deploy-env surface is touched, so ADR-0007's hard gate does not apply. No API contract, no session transport, no migration.
- **`docs/archive/`**, the PRD, `internal-modules.md`, the roadmap, the UI blueprint.\*\* `docs/standards/coding-standards.md` is the only standard that touches you, and only for its tests clause.

## Prefactor - do not re-derive these

- **The two failures, precisely characterized.** #561 recorded, across six full-suite runs, that this file contributes `1 failed` deterministically and `2 failed` intermittently. In isolation (`npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx`) it is `33 tests | 1 failed`, and the one is `does not double-navigate when the CTA is pressed mid-countdown (#551)`. The other, `shows the shared done screen, counts down, and redirects at zero (#551)`, **passes in isolation** and appeared in 2 of 6 full-suite runs. That asymmetry is the ticket's "not the same fault" claim, and it is real.

- **What each failure actually looks like, from the captured output - this is the part that saves the hour:**

  | Test                                                                      | Failing assertion                                                                                       | What the DOM shows                                                                                                                                                                                 |
  | :------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `does not double-navigate when the CTA is pressed mid-countdown (#551)`   | L663 `await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/patient"))` - `Number of calls: 0` | Done screen fully rendered, `role="status"` = "Opening your dashboard in 3", `aria-valuenow="3"`. The click landed; the navigation never happened.                                                 |
  | `shows the shared done screen, counts down, and redirects at zero (#551)` | L570 `screen.getByText("Opening your dashboard in 5")` - `Unable to find an element with the text`      | `role="status"` = **"Opening your dashboard"** (no digits), `aria-valuenow="5"`, `aria-valuetext="Opening your dashboard"`. The countdown is still **held**, i.e. `resumePending` is still `true`. |

- **One mechanism explains both, and it is the partial timer fake.** `fakeCountdownClock()` (L139-141) calls `vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] })` - it fakes the interval and leaves everything else, including `setTimeout`, real. `@testing-library/dom`'s `waitFor` then mis-detects the environment: `jestFakeTimersAreEnabled()` probes **only** `setTimeout._isMockFunction`, so it reports "fake timers are off", registers a `MutationObserver`, **and** arms its real-timer fallback poll on `setInterval` - the one function you did fake. That poll can therefore only fire on `advanceTimersByTime`, which the tests never call from inside a `waitFor`. The consequence: a `waitFor` whose assertion needs a _second_ check after an async flush never gets one, because the click produces no DOM mutation either (the `departed` state re-renders to identical output). Both failures are "assertion checked once, too early":

  - The `does not double-navigate` failure is `waitFor`'s first synchronous check, before `landOnReturnTarget`'s `void resumeOnce().then(() => router.replace(returnTo))` (PatientAuthWizard.tsx L342) has run its microtask.
  - The `counts down and redirects at zero` failure is a bare **synchronous** `getByText` for a value that only exists after `setResumeSettled(true)` flushes from the effect at L327-331, plus the dead poll above. It is a microtask-drain race, which is exactly why it is timing-sensitive and therefore intermittent under a full-suite load.

- **The "genuine cross-file pollution" framing is a hypothesis, and the evidence does not support it.** Vitest isolates each test file into its own module registry and environment by default, so another file's `vi.mock` cannot reach this one. And this file's own `beforeEach` (L155-166) `mockReset()`s **every** mock it declares - `registerPhone`, `verifyOtp`, `resendOtp`, `issueSession`, `fetchDemoOtp`, `mockReplace`, `state.resumeSession` - so the "no `vi.clearAllMocks()` in `afterEach`" gap the ticket worries about is real as _hygiene_ but is **not** the cause of either failure. AC-2 asks you to fix the cause, not the label: establish the cause yourself from the two DOM states above, and if it is the timer fake rather than pollution, say so explicitly in the PR and the issue. Do not go looking for a polluting neighbour file.
- **The `afterEach` hygiene gap is still worth closing, on its own merits.** `afterEach` (L150-153) has no `vi.clearAllMocks()`, so call counts survive into the next test within the file. Nothing depends on it today because `beforeEach` resets. Adding `vi.clearAllMocks()` (or `vi.resetAllMocks()`) is cheap and makes the file's contract match `DoneScreen.test.tsx` and the rest of the repo - but it is **not** what turns the suite green, and shipping it as the fix would be papering over (AC-2). The other candidate in the batch, #562, has the opposite problem in a different file and is handled there.
- **The three tests AC-3 protects, and what "unchanged in what they assert" means.** `holds the countdown back until the resume seam settles (#551)` gates a never-resolving `gate` promise onto `state.resumeSession`, proves the clock never runs behind the resume call, then `release!()`s it and proves the countdown starts from the top. `awaits the session-resume seam before routing to the return target (#496)` covers the return-target path and the clear-on-unmount case. The clear-on-unmount assertion is `vi.getTimerCount()` dropping to 0. If your fix changes the clock harness, **all three of these must keep their current expectations** - including "starts from the top" and the exact digit counts. Converging on `DoneScreen.test.tsx`'s full `vi.useFakeTimers()` will put pressure on these; the pressure means the harness needs to be driven differently, not that the expectations should move.
- **`DoneScreen.tsx` is correct.** Its once-only guard is a `useRef` (`departedRef`, L78) rather than state specifically so it survives a StrictMode double-invoke, and `goRef` (L79) exists so a fresh inline callback identity cannot re-arm the auto-redirect. Both are load-bearing. If your reading of the wizard's failures suggests a component defect, read these two refs twice before you touch anything.

## Baseline verify (must reproduce a known-red state before the first edit)

The baseline here is red by design. Reproduce both halves **separately** - that is the ticket's own instruction, and it is the only way to know which failure you are looking at:

```bash
# Half one: reproduces in isolation. Expect 33 tests | 1 failed.
npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx

# Half two: needs the full run, and is intermittent. Run the full suite a few
# times; expect 11-12 failed | 1521-1520 passed (1532) with 1-2 of them here.
npm run test:unit:frontend

# Exact names, machine-readable. --outputFile resolves relative to the cwd,
# so run from apps/frontend with an absolute path.
npx vitest run --reporter=json --outputFile="D:/Dev/tools/temp/opencode/baseline-563.json"
```

`git status --porcelain` must be clean of `apps/frontend/src/components/auth/doneScreen.module.css` before you trust a verdict - #561 owns that. If #561 has not run, stop and do that first. Also confirm #562's file is not part of your red: if `StaffLoginForm.test.tsx` is still red, that is #562's scope, not a dependency you inherited.

## Done-verify (acceptance criteria -> commands)

- AC-1, in isolation and in the full run - the two commands the AC names, both required:
  ```bash
  npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx    # 33/33 green
  npx vitest run --reporter=json --outputFile="D:/Dev/tools/temp/opencode/after-563.json"
  # assert: 0 failures in PatientAuthWizard.test.tsx
  ```
  Run the full suite **at least three times** before declaring victory. The second failure was intermittent (2 of 6 runs at baseline); a single green run proves nothing about it.
- AC-2, cause fixed not hidden: the PR states which of the two mechanisms in the Prefactor was the cause of each failure, with the DOM evidence that identified it. A green suite with the cause unstated fails AC-2. No `.only`, no `.skip`, no reordering of `describe` blocks to hide a leak, no deleted assertion.
- AC-3, the three protected tests unchanged: `holds the countdown back until the resume seam settles (#551)`, the clear-on-unmount case inside `awaits the session-resume seam before routing to the return target (#496)`, and the countdown-at-zero case all still pass **with their current expectations**. Show the diff for L594-712 is empty of expectation changes.
- AC-4, meaningful green: `git diff` on the file contains no added `.skip`, `it.skip`, `describe.skip`, or `it.todo`. And `DoneScreen.test.tsx` is still green - a fix that breaks the prior art has moved the problem, not solved it.
- AC-5, no production behaviour change:
  ```bash
  git diff --stat -- apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx
  git diff --stat -- apps/frontend/src/components/auth/DoneScreen.tsx
  git diff --stat -- apps/backend/
  # all empty, or a production change called out explicitly in the PR with a
  # stated product defect
  ```
- Full suite, and no collateral damage:
  ```bash
  npm run test:unit:frontend
  npm run typecheck
  npm run lint
  ```
  After both #562 and #563 have landed, `npm run test:unit:frontend` should be `Test Files 0 failed` / `Tests 0 failed | 1532 passed`. While #562 is still open, `Tests 1-2 failed` confined to `PatientAuthWizard.test.tsx` is the correct state. An intermittent `CaseWorkspacePage stage + forced review (US-15) > renders the case stage chip for the pre-summary stage` failure may also surface - it is order-dependent, belongs to no ticket in this batch, and is recorded in #561. Do not let it masquerade as your regression, and do not silently absorb it.

## Handoff notes

- **Do not "fix" this by asserting less.** The obvious wrong turn is to relax the timing assertions (drop the `getByText("...in 5")`, loosen the mid-countdown digit check) until the suite is green. That is papering over by assertion deletion and fails AC-4's spirit and AC-2's letter. The wizard is the reference implementation later partner-OTP work is rebuilt on - a suite that passes because its timing expectations were loosened is worse than a red one.
- **The same wrong turn is available in the opposite direction:** switching to full `vi.useFakeTimers()` without reconciling the `findBy*` helpers. `startOtpFlow` (L114-124) and `enterPhone` (L107-112) depend on `findBy*` keeping real timers - the comment at L136-138 says so explicitly. Whatever you do to the clock, those helpers must keep working, and the three AC-3 tests must keep their current expectations. `DoneScreen.test.tsx` is the working example to converge on, not a template to copy blindly: it does not use `findBy*` at all.
- **The `finally { vi.useRealTimers(); }` in all four countdown tests is a correctness guard, not boilerplate.** If you hoist the clock setup into `beforeEach`, keep a matching teardown, or the leak moves to whichever test runs next - which is precisely the #562 failure mode one file over.
- **The `setDeparted` re-render produces no DOM mutation.** That is why `waitFor` cannot recover on its own, and it is the non-obvious link between the two failures. It is also why "just add `await act(...)` around the click" is a targeted fix for the first failure and probably not sufficient for the second, which needs the resume-settle microtask drained before a synchronous `getByText`.
- **`localStorage.clear()` is in `beforeEach` (L156) and is load-bearing** for `a stored session triggers a redirect to /patient without showing the form` (L713). Leave it. If you restructure the hooks, check that test too.
- **The wizard does not use the staff-routing seam.** There is no `fetchPartnerMe`, no `postLoginTarget`, no `/v1/partner/me` read in this file. If you find yourself reasoning about partner status while debugging a countdown, you have crossed into #562's territory.
- **#563 is the last of the three.** When it lands, the frontend unit suite is green and every later ticket in the #560 cut can trust a red/green verdict. Say so in the PR.
- **No em-dashes anywhere (lint-gated).** Use simple dashes. `npm run lint` runs pre-commit, which includes prettier and a trailing-whitespace hook, so run it before declaring done.
