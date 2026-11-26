# Brief - 566 Render the verified handoff on the OTP stage, not the resolved destination

**Ticket:** #566 · **Parent:** #560 (front five defects, part 5 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #562, #563 (the red-test baseline repair - the full frontend suite must be green before this ticket's verdicts are trustworthy)
**Reading surface:** ~9.5K tokens (budget 10K) - **PASS, within budget (tight; treat the two `StaffLoginForm.test.tsx` slices as the first thing to drop if you go over)**

## Scope

The instant a partner's code is accepted, they are on the verified handoff screen. No stale sign-in card, no live "Get verification code" button, no "Sign in" heading telling them they are still signing in.

**The reported window is exactly the length of the post-login destination resolution - three network round-trips - and during it the submit button is live, so a partner who taps it gets no feedback.** The fix is to make the handoff's render condition the **OTP stage**, not the **resolved destination**. Destination resolution stops being a render precondition: while it is in flight the handoff screen is already mounted and reports a pending state.

**The change makes the staff flow structurally identical to the patient flow**, which already renders its terminal step unconditionally.

AC:

- [ ] The handoff screen's render is keyed to the OTP stage alone. A held destination promise, with the code submitted, shows the handoff **synchronously** - no polling, no waiting.
- [ ] At that instant the code input, the submit control, and the page's sign-in heading are all absent, and a pending state is present. The test asserts the intermediate surface, which is the gap that let the flash ship.
- [ ] The countdown is released only once the session is genuinely ready to resume, and does not start while the destination is in flight.
- [ ] A failed destination resolution leaves the handoff screen visible with an explanation, not a blank card.
- [ ] The submit control's label has an explicit terminal case; it no longer falls through to the phone-step label.
- [ ] A pending or rejected partner reaches their status screen with no handoff screen ever rendered.
- [ ] The countdown's own duration and its copy are unchanged - only when it starts moving is in scope.
- [ ] This is a red-capable, deterministic, sub-second command: the held-promise case is the regression test, and it fails on the reported symptom before the fix.

## THE EXACT REGION TO CHANGE

One file, five regions. Line numbers are on the tree as of 2026-09-27 (`StaffLoginForm.tsx`, 759 lines); **#562 rewrites the sibling test file, not this one**, so these regions should hold - re-grep if they do not.

| #   | file : lines                                                         | symbol                                                                   | what changes                                                                                                                                                                                                                                                                                                       |
| --- | -------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx:556-573` | the `partner.state.stage === "done" ?` branch of the 3-way stage render  | **Drop the `landing !== null ?` wrapper.** Render `<DoneScreen>` unconditionally on the done stage. This is the core fix: today this branch returns `null` while the destination is unresolved, which is the blank card.                                                                                           |
| 2   | `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx:169-182` | the post-verification **resume** effect                                  | Its guard is `if (partner.state.stage !== "done" \|\| landing === null) return;` - the resume seam does not start until the destination resolves. It must start earlier (on the session being present) so `resumeSettled` becomes an **independent** signal rather than a mirror of `landing`. See the trap below. |
| 3   | `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx:568`     | the `resumePending={!resumeSettled}` prop on `<DoneScreen>`              | Must become "resume outstanding **OR** destination outstanding" (e.g. `!resumeSettled \|\| landing === null`). This is what makes AC-3 true once region 2 is decoupled.                                                                                                                                            |
| 4   | `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx:743-757` | the `<button data-testid="staff-submit">` and its label ternary          | Gate the button on the same condition as the handoff, and give the label an explicit terminal case. Today it has none, so it falls through to the phone step's `t.getCode`.                                                                                                                                        |
| 5   | `apps/frontend/src/app/staff/login/page.tsx:96`                      | the page-level `<h1 className="mb-4 text-xl font-bold">{t.heading}</h1>` | Suppress once the flow is terminal. **This `h1` is in the page, not the form** - see the structural note below.                                                                                                                                                                                                    |

**Regions that must NOT change - the exit branches (L273-296 of `landPartnerAfterLogin`).** Three exits after the reads, and all three stay exactly as they are:

1. `window.location.replace(target)` when `routeState.partnerType !== "doctor" \|\| routeState.partnerState !== undefined` - a non-doctor partner, or a pending/rejected partner, is routed **straight away** and never sees a handoff.
2. `await landOn(target)` when `!isDoctorConsoleLanding(target)` - an active doctor bound for a `?return=` deep link outside the console navigates immediately, no handoff.
3. `setLanding({ target, ...(await readPracticeIdentity()) })` - an active doctor on a console landing is the **only** path that sets `landing` and therefore the only path where the countdown may run. Preserved by AC-6.

**The operator branches are untouched.** `handleSubmit` has four sub-branches and only the partner ones are in scope: the MFA re-verify branch (L315-332, calls `landAfterLogin`) and the fresh-operator branch (L336-370, also calls `landAfterLogin`) must render and behave identically. `landAfterLogin` (L251-261) keeps its hard `window.location.replace`. Region 4's label change must not alter what the operator branch renders.

## THE THREE ROUND-TRIPS AFTER OTP ACCEPTANCE - confirmed, in this order

Your count is **confirmed exactly: three network round-trips**, plus one free pure function between them. `landPartnerAfterLogin` (L273-296) runs them in this sequence:

| order | call                                                                                         | site                    | what it does                                                                                                                                                                                                |
| ----- | -------------------------------------------------------------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | `completeStaffLogin(session)` → `fetchMe(session.jwt)` then `saveSession(session, me.phone)` | L69-75, called at L274  | the current-user read; **also saves the session locally**, which is why the resume seam can be honest about resumability                                                                                    |
| -     | `postLoginTarget({...})`                                                                     | L276-281                | **pure routing-target function, no network cost.** A pure decision table, already pinned as a table in `staff-routing.test.ts` and `src/proxy.test.ts`. It sits _between_ the second and third round-trips. |
| 2     | `fetchPartnerRouteState(me.roles)` → `fetchPartnerMe`                                        | L275                    | the partner route-state read; **this is where a non-doctor partner or a pending/rejected partner is routed straight away** via exit 1                                                                       |
| 3     | `readPracticeIdentity()` → `fetchDoctorProfile()`                                            | L95-112, called at L295 | the doctor-profile read, **only on the doctor-console branch**; best-effort, degrades to `{ practiceName: null, specialty: null }` with a `console.error` rather than stranding the login                   |

The post-verification **landing** effect (L212-222) fires **once**, keyed on `partner.state.session` becoming present - not on the stage, not on the landing. It calls `landPartnerAfterLogin` and funnels a throw into `setNotice(envelopeNotice(error))`. Do not re-key it.

**`readPracticeIdentity`'s profile read is NOT mocked in the test file.** There is no `vi.mock("@/lib/doctor/api")` and no `global.fetch` stub in `StaffLoginForm.test.tsx`, so the third read runs unmocked, throws, and degrades to nulls. That is why the existing done-screen tests see no `Practice` / `Specialty` fact rows. It is a real fact about the harness, not a bug - do not "fix" it by adding a mock unless your new test needs fact rows.

## THE TRAP - decoupling the resume seam will silently break AC-3

This is the whole ticket's engineering difficulty and it is one boolean.

Today `resumeSettled` is set by the effect at L169-182, whose guard includes `landing === null`. So `resumeSettled === true` currently _implies_ the destination resolved. Region 1 removes the render's dependence on `landing`, and region 2 removes the resume effect's dependence on `landing` - which is what makes the handoff honest - but together they also destroy the only thing that was keeping the countdown from starting early.

If you do region 1 and region 2 and leave `resumePending={!resumeSettled}` alone, then: destination in flight, resume already settled, `resumePending === false`, `DoneScreen` starts its 1-second interval immediately - the countdown runs for several seconds **before there is any destination to navigate to**, and `onGoToDashboard` (`landOnConsole`, L185-191) returns early on every tick because `landing === null`. AC-3 fails, and it fails in a way that looks like a cosmetic nit until someone reads the AC.

**The honest gate is the conjunction.** The countdown starts only when the session is genuinely resumable **and** the destination is in hand. `resumePending` must be true while _either_ is outstanding. Note the two are genuinely different clocks - the resume seam is one call, the destination is a three-read chain - so the countdown must not be wired to just one of them.

A second, subtler consequence of region 2: starting the resume seam on session-present (rather than on landing-resolved) is what makes `resumeSettled` a real signal, but it also means the resume call now runs **concurrently** with the destination reads rather than after them. That is the point (it is why the countdown can be released without waiting), and it is safe because `resumeOnce` is already idempotent-by-ref (`resumeRef`, L154, L161-164) and `landedRef` (L155) already guards against a double-navigate. Do not add a second resume call site.

## The submit label - the nested ternary, verbatim

`StaffLoginForm.tsx:749-755`, exactly as it stands:

```tsx
{
  isMfaStep
    ? t.mfaSubmit
    : isOperatorMode
      ? t.signIn
      : partner.state.stage === "otp"
        ? t.mfaSubmit
        : t.getCode;
}
```

Four cases, no terminal case. On the done stage the expression falls all the way through to `t.getCode` - the phone step's "Get verification code" - which is the live-button-with-the-wrong-label half of the reported flash. AC-5 asks for an **explicit** terminal case: add a `partner.state.stage === "done"` arm with its own label (dictionary copy, both locales) rather than reordering the arms so an existing one happens to match. Reordering is the trap - it would silently change what the operator and MFA branches render, and the operator branch is out of scope.

`disabled` on the same button (L746) is `isOperatorMode || isMfaStep ? loading : partnerBlocked`, where `partnerBlocked = partner.state.busy || partner.state.challenge === "locked"` (L386-387). Neither term is true on the done stage, which is why the button is live. AC-2's "submit control is absent at that instant" is the stronger, better fix - render it out - not merely disable it.

## Key facts / prior art - do not re-derive these

- **The regression-test technique is: hold the destination promise open, submit the code, assert the intermediate surface synchronously. No polling, no waiting, no `findBy`.** The three existing done-screen tests in this file all use `await waitFor(() => { … })` and assert only the **settled end state** - `StaffLoginForm.test.tsx:583-605` (`waitFor` then `getByRole("heading", { name: "Identity verified" })` and the `role="status"` progress line), `:685-700` (same shape), and the `?return=` test at `:708-729`. **That is exactly why the flash shipped**: nothing in the suite ever looked at the surface _between_ submit and resolve, so a blank card with a live button was not a failing expectation anywhere. AC-2 is a criterion about closing that gap, not about a new component.
- **The prior art for the done screen's own gating is `DoneScreen.test.tsx`, not the staff suite.** `apps/frontend/src/components/auth/DoneScreen.test.tsx` (178 lines) is the isolated host-free contract: the `advance(ms)` helper (L24-29, `act(async () => { await vi.advanceTimersByTimeAsync(ms) })`), the `renderDone(overrides)` factory (L32-51), and the two tests that matter here - **L107-126 `"holds the countdown back until the resume seam has settled (#551)"`**, which advances `DONE_SCREEN_COUNTDOWN_SECONDS * 1000 * 2` and asserts the progress line still carries no digits and `aria-valuenow` is still `5`, and **L138-150 `"does not double-navigate when the CTA is pressed mid-countdown (#551)"`**. Copy the `advance` helper's shape if your new test needs timers; note `afterEach` there does `cleanup(); vi.useRealTimers();` (L19-22) and `StaffLoginForm.test.tsx`'s own `afterEach` (L123-128) does **not** reset timers - if you add fake timers, add the reset.
- **The honest countdown gate already exists and is named: `resumeSettled` (L156), and the prop that consumes it is `resumePending` (`DoneScreen.tsx:53`).** `DoneScreen` holds its interval while `resumePending` is true (L96-106) and fires the auto-redirect only when `!resumePending && secondsLeft === 0` (L109-114). Its progress line already has a genuine two-state shape: `resumePending ? openingLabel : openingInLabel(secondsLeft)` (L116-118), rendered into `<p role="status">` (L140-142) with a sibling `role="progressbar"` carrying `aria-valuemax={DONE_SCREEN_COUNTDOWN_SECONDS}` (L143-151). **The pending state AC-2 wants is already rendered by the component** - you do not need a new pending element, and asserting "a pending state is present" should mean the digit-free `openingLabel` line, not something you added.
- **`DONE_SCREEN_COUNTDOWN_SECONDS = 5` and all the `doneScreen.*` copy are out of scope** (AC-7). The component owns the tick deliberately - `DoneScreen.tsx:24-27` says "the screen owns the tick, so no host repeats the number". Do not add a second countdown, do not change the duration, do not reword `openingLabel` / `openingInLabel` / `goToDashboardLabel`.
- **`landOnConsole` (L185-191) and `landOn` (L196-206) both no-op safely while `landing === null` / once `landedRef` is set** - that is why rendering the handoff before the destination resolves cannot cause a premature navigation. `landOnConsole` returns early on `landing === null`; `landOn` returns early on `landedRef.current`. You do not need to add a guard; you do need a test that the early tick does not navigate.
- **The stage is a three-value union, not a boolean.** `PartnerStage = "phone" | "otp" | "done"` (`apps/frontend/src/components/auth/staff/partnerLoginState.ts:39`), and `PartnerOtpState.session: SessionResult | null` (L56) is the field the landing effect keys on. The done stage is reachable only after `issuePartnerSession` mints a session, so "session present" and "stage is done" are effectively the same moment - which is what makes keying the render on the stage safe.
- **A pending or rejected partner reaches their status screen with no handoff screen, and the test must prove it, not infer it.** Exit 1 is a `window.location.replace`; the handoff is active-partner-only. AC-6's test is the negative case: assert the handoff is **absent** for a `{ Under Verification }` and a `{ Rejected }` partner. The existing `it.each` rows at `StaffLoginForm.test.tsx:654-675` and `:733-755` already walk those states - extend rather than duplicate.
- **The envelope notice renders above the stage switch, not inside it** (`StaffLoginForm.tsx:420-433`, a `role="alert"` div with `data-testid="staff-login-error"`). So AC-4 - a failed destination resolution shows the handoff **plus** a visible explanation - is naturally satisfiable once region 1 is fixed: today the explanation appears _underneath_ a blank card with a live button, because the branch returns `null` while `landing` is unset. There is already a test for the explanation in isolation (`StaffLoginForm.test.tsx:833-860`, `"shows the envelope notice when the post-login landing fails"`, asserting the trace id) - it does not assert the handoff's presence, which is the gap.
- **The `h1` suppression is structural, not a one-liner.** The heading is `apps/frontend/src/app/staff/login/page.tsx:96`, inside the page's card div, **outside** `<StaffLoginForm>` (L97). `StaffLoginForm` owns the stage and knows nothing about the page's chrome, so suppressing the heading from the form requires lifting the terminal-ness signal to the page (a prop up, a lifted state, or the page reading the stage). Separately: `DoneScreen` renders **its own** `<h1>` (`DoneScreen.tsx:128`), so leaving the page heading in place produces **two `h1`s** on one screen - which is both the reported symptom and a document-structure regression. Whatever mechanism you choose, assert the count, not just the absence of the "Sign in" name.

## Read-list (in order)

1. **Issue #566 itself** - the eight AC and its Context pack (~0.7K).
2. **`StaffLoginForm.tsx`, ten named regions, never the whole file (759 lines):**
   - L66-75 `completeStaffLogin` (round-trip 1 + the local session save) (~0.3K)
   - L77-88 the `DoctorLanding` interface + its doc comment (the "null until resolved" contract you are changing) (~0.25K)
   - L90-112 `readPracticeIdentity` (round-trip 3 and its degrade) (~0.3K)
   - L143-156 the `landing` / `resumeRef` / `landedRef` / `resumeSettled` state block and its comments (~0.4K)
   - L161-206 `resumeOnce`, the resume effect, `landOnConsole`, `landOn` (~0.7K)
   - L208-222 the post-verification landing effect (single-fire on session) (~0.3K)
   - L251-296 `landAfterLogin` (operator, untouched) and `landPartnerAfterLogin` (the three exits) (~0.8K)
   - L305-320 the head of `handleSubmit`; L372-388 the partner branch tail, `isMfaStep`, `partnerBlocked` (~0.5K)
   - L395-417 `landingFacts` (optional-facts behaviour is what lets the handoff render before `landing` exists) (~0.3K)
   - L540-573 the end of the code-step branch and the whole `done` branch; L743-757 the submit button and its label ternary (~0.7K)
     (~4.6K)
3. **`DoneScreen.tsx` L23-61** (the props interface, especially `resumePending` and the optional `facts`) and **L73-120** (`secondsLeft`, `departedRef`, `depart`, the tick effect, the auto-redirect effect, the `progressLine` ternary) (~0.9K). Do not read L121-161 beyond confirming it is a plain render.
4. **`DoneScreen.test.tsx` L19-51** (the `advance` helper and `renderDone`) and **L107-150** (the two `#551` countdown tests) - the prior art for the held/pending pattern (~0.9K).
5. **`StaffLoginForm.test.tsx`, three slices only (1218 lines):** L100-155 (the `vi.mock` block and `beforeEach` - note `mockFetchPartnerRouteState` is **not** `mockReset()` there, and the `@/lib/auth/staff-routing` factory at L113-121 still **replaces** `fetchPartnerRouteState`, which is #562's dead-mock fault), L180-200 (`typePartnerPhone` / `typeCode` / `typeCodeAndSubmit` / `startPartnerOtpFlow` - the helpers your test drives), L550-621 and L677-706 (the two existing done-screen tests, the settled-end-state pattern you are deliberately not copying) (~2.2K). **The 42 other tests need not be read** - grep by name if you change a shared helper. **#562 will rewrite L100-155: re-grep by name after it lands.**
6. **`apps/frontend/src/app/staff/login/page.tsx` L88-99** - the wordmark, the card, the `h1` at L96 and the form mount at L97 (~0.3K). Also glance L40-59 for `t` and the page's own already-authenticated redirect effect, so you know which surface the `h1` lives on.
7. **`partnerLoginState.ts` L39-40 and L42-58** - `PartnerStage`, `PartnerOtpState.stage`, `.session`, `.busy`, `.challenge` (~0.3K).
8. **`apps/frontend/src/lib/auth/staff-routing.ts` L70-98** - `fetchPartnerRouteState` and its catch that degrades to `{ undefined, undefined }` (~0.3K). Just enough to know which seam the held promise attaches to and that a _rejection_ also has to keep the handoff visible.

**Total ≈ 9.5K tokens. PASS** (budget 10K).

**Re-grep by name if this no longer resolves:** `partner.state.stage === "done"|landing !== null|resumeSettled|resumePending|staff-submit` in `StaffLoginForm.tsx`; `mockFetchPartnerRouteState|mockFetchPartnerMe|importOriginal|clearMocks|mockReset|restoreMocks` in `StaffLoginForm.test.tsx` and in `apps/frontend/vitest.config.ts` (there is **no** global mock-lifecycle option - #562's brief confirms it, so every lifecycle decision is per-file and manual). If #562 has un-mocked `fetchPartnerRouteState`, the seam you hold open in the regression test is `mockFetchPartnerMe` rather than `mockFetchPartnerRouteState` - re-derive from the red output, not from this brief.

## Do NOT read

- **`StaffLoginForm.test.tsx` whole.** 1218 lines. The mock block, the four helpers, and the two settled-end-state done-screen tests are all you need; the rest is context you will not use. Note that after #562 the mock block's shape is _guaranteed_ to differ from what item 5 describes.
- **`StaffLoginForm.tsx` L446-540 and L574-742** - the operator TOTP step's rendering, the demo banner, the phone step's fields, and the whole OTP step (countdown, resend, back, cooldown, lockout, attempts, error, notice). You are changing the render _condition_ of the done branch, the submit control, and the resume effect - not the steps. The code step's own countdown (`partner-countdown`, L613) is the OTP expiry timer and is **unrelated** to the handoff's countdown; do not conflate them.
- **`PatientAuthWizard.tsx` and `PatientAuthWizard.test.tsx`.** #563's file. The ticket's structural claim is that the patient flow _already_ does this right, which is enough; reading the wizard to copy its render switch is a context switch you do not need, and its `it` names are confusingly similar to the staff suite's.
- **`ProviderRegisterWizard.tsx` and its test.** A later ticket rewrites it; it has nothing to do with post-login landing.
- **`staff-routing.test.ts`, `src/proxy.test.ts`, `return-url.ts`, the `ROLE_HOME` table.** The routing matrix is already pinned as a table in both; you are not changing `postLoginTarget`, and the held-promise test asserts the _surface_, not the target.
- **The backends, `apps/backend/**`, migrations, `docs/adr/0007-\*`.** Nothing here touches a cookie, a CORS rule, a proxy guard, `credentials`, or a deploy env var, so ADR-0007's hard gate does not apply. No API contract, no schema, no event, no session-transport change - the session is saved exactly where it is today, by `completeStaffLogin`.
- **`docs/archive/`**, the PRD, `internal-modules.md`, the roadmap, `docs/design/ui-blueprint.md`, `docs/standards/*`. No architecture or requirement question is in scope. The behaviour ACs are stated completely in the issue.
- **`doneScreen.module.css`.** It carries an **uncommitted** edit tracked by #561, and the handoff's _appearance_ is out of scope. Do not read it, do not edit it, do not let it into your diff.

## Baseline verify (must pass before the first edit)

- **Gate: #562 and #563 must be closed.** "Full frontend unit suite green" is a done-verify for this ticket, and you cannot attribute a red suite to your own change on a red baseline. Per #564's recorded baseline the suite is **13 failed / 1519 passed (1532), 3 files**: `StaffLoginForm.test.tsx` (10, = #562), `PatientAuthWizard.test.tsx` (2, = #563), and one third-file 5s `Test timed out` that is a load flake owned by nobody. Its identity moves between runs at this commit - name it by file and test, do not expect one file.
- **Confirm #562 landed, because it changes your test file.** After #562 the `vi.mock("@/lib/auth/staff-routing")` factory no longer replaces `fetchPartnerRouteState`, `mockFetchPartnerMe` becomes the live seam, and `beforeEach` resets it. If the factory at L113-121 **still** replaces `fetchPartnerRouteState`, #562 has not landed - stop.
- The fast loop, and the specific red this ticket is about:
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend
  # expect green, 52 tests, after #562
  npx vitest run src/components/auth/DoneScreen.test.tsx --root apps/frontend
  # expect green, 8 tests
  ```
- `npm run test:unit:frontend` - green after the blockers. If a third file is still timing out at 5s, record it as the pre-existing load flake and move on.
- `npm run lint` - confirmed green 2026-09-27 (all 17 pre-commit hooks, including the no-em-dash gate).
- `npm run typecheck` - confirmed green 2026-09-27 (mypy strict 251 files; `tsc --noEmit` clean).
- `git status --porcelain` - the uncommitted `apps/frontend/src/components/auth/doneScreen.module.css` is pre-existing (#561). Not yours; do not commit it.
- **AC-8 demands you prove red before green.** After the blockers are closed, write the held-promise test and run it against the **unfixed** `StaffLoginForm.tsx`. It must fail on the reported symptom - the handoff absent and the submit button present at the held instant. Capture that red on the ticket. A regression test that has never been seen failing is not evidence.

## Done-verify (acceptance criteria -> commands)

- AC-1, AC-2, AC-8 - the held-promise regression test, and it is sub-second and synchronous:
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "<your held-promise test name>"
  # deterministic; no fake timers needed for the assertion itself
  ```
  Inside that single test, with the destination promise held open and never resolved: the handoff heading is present, the progress line is the **digit-free** `openingLabel` (no `" in 5"`), `partner-otp` is absent, `staff-submit` is absent, the page's "Sign in" `h1` is absent, and **exactly one** `h1` is on the document. All of it asserted **without** `waitFor`, `findBy`, or a polling loop.
- AC-3 - the countdown gate:
  ```bash
  # a fake-timer test: while resume OR destination is outstanding, advance
  # DONE_SCREEN_COUNTDOWN_SECONDS * 1000 * 2 and assert aria-valuenow is still 5,
  # the progress line still carries no digits, and onGoToDashboard was NOT called.
  # then settle both and assert the countdown moves and navigates exactly once.
  ```
  The negative half is the half that matters: the `!resumeSettled`-only wiring fails this.
- AC-4 - failure path: with the destination promise **rejected**, assert the handoff is visible **and** the `role="alert"` explanation (and its trace id) is present. Extend the existing test at `StaffLoginForm.test.tsx:833-860` rather than adding a parallel one.
- AC-5 - the label: with the handoff mounted and no destination, assert the submit control's rendered text is the new terminal label, not `STRINGS.en.staffAuth.login.getCode`. Also assert the **operator** branch still renders `t.signIn` and the MFA branch still renders `t.mfaSubmit` - the reordering trap.
- AC-6 - the negative case: for `{ Under Verification }` and `{ Rejected }`, assert the handoff is absent and `mockLocationReplace` was called with the status-screen target. Extend the existing `it.each` rows.
- AC-7 - out-of-scope proof:
  ```bash
  git diff -- apps/frontend/src/components/auth/DoneScreen.tsx
  # expect: no change to DONE_SCREEN_COUNTDOWN_SECONDS or any doneScreen.* copy
  # (a change to DoneScreenProps is acceptable and expected; a change to the
  #  duration or the copy is not)
  ```
- The operator branches are untouched:
  ```bash
  git diff -- apps/frontend/src/components/auth/staff/StaffLoginForm.tsx
  # read your own diff: landAfterLogin (L251-261) and the two operator sub-branches
  # of handleSubmit (L315-332, L336-370) must show no behavioural change
  ```
- The full harness:
  ```bash
  npm run test:unit:frontend
  npm run lint
  npm run typecheck
  ```

### Acceptance criteria as a checklist

- [ ] The `done` branch renders `<DoneScreen>` on the stage alone - the `landing !== null` wrapper is gone. Assert it, do not eyeball it.
- [ ] The regression test holds the destination promise open, submits the code, and asserts the intermediate surface **synchronously** - no `waitFor`, no `findBy`, no polling. Deterministic and sub-second (AC-8).
- [ ] The test was seen **failing on the unfixed code**, and the red output is on the ticket (AC-8).
- [ ] At the held instant: the handoff heading is present, the pending state is present as the digit-free `openingLabel`, and `partner-otp`, `staff-submit`, and the page's "Sign in" `h1` are all absent.
- [ ] The document carries exactly **one** `h1` while the handoff is up (the page heading is suppressed; `DoneScreen`'s own `h1` is not duplicated).
- [ ] `resumePending` is the conjunction - true while the resume seam **or** the destination is outstanding. A countdown that ticks before a destination exists fails AC-3.
- [ ] The resume seam starts on session-present (not on landing-resolved), stays a single idempotent call via `resumeRef`, and `landOnConsole` / `landOn` still no-op safely before a destination exists - proven by a test that an early tick does not navigate.
- [ ] A **rejected** destination resolution leaves the handoff visible with the envelope explanation and its trace id. No blank card on any path.
- [ ] The submit label has an explicit terminal case. The operator branch still renders `t.signIn` and the MFA branch still renders `t.mfaSubmit` - asserted, because reordering the ternary is the failure mode.
- [ ] A pending and a rejected partner reach their status screens with `window.location.replace` and **no handoff ever rendered**. The handoff is active-partner-only.
- [ ] The three exit branches in `landPartnerAfterLogin` and both operator sub-branches of `handleSubmit` are behaviourally unchanged; `landAfterLogin` keeps its hard reload.
- [ ] `DONE_SCREEN_COUNTDOWN_SECONDS` and every `doneScreen.*` string are unchanged. Only **when** the countdown starts is in scope.
- [ ] `DoneScreen.module.css` is untouched and stays out of the diff.

## Handoff notes

- **The change is one render condition plus one boolean.** Everything hard in this ticket is downstream of those two edits: the resume-effect guard, the `resumePending` conjunction, the submit gating, the label arm, the `h1`. If you find yourself restructuring the landing effect, the exit branches, or the OTP step, you have left the ticket.
- **The trap is the `resumePending` conjunction, and it is silent.** Region 1 and region 2 together look obviously right and break AC-3 with no failing test, because the failure is "the countdown ran for four seconds with nothing to navigate to" - which reads as a cosmetic nit until someone reads the criterion. Write the negative half of the AC-3 test (advance 10s while either is outstanding, assert no movement, no navigation) **before** you touch the effect guard.
- **Assert the intermediate surface, not the end state.** Every existing done-screen test in this file is a `waitFor` on the settled state, and that is precisely why a blank card with a live button shipped. The test you add is the deliverable as much as the code change.
- **The heading lives in the page, so its suppression is a seam you must design.** Do not fake it by asserting only on the form's internals. `DoneScreen` renders its own `h1`; a leftover page heading means two of them.
- **Do not widen the label fix by reordering.** A nested ternary that "accidentally" works after a reorder has changed the operator branch's copy, and the operator flow is explicitly out of scope.
- **Two blockers, still open at brief time** (#562, #563), and the full suite is red until they land. #562 will also rewrite the mock block you read - re-grep the mock names rather than trusting the line numbers in read-list item 5.
- **The third round-trip is unmocked in the test file** and degrades to nulls. That is expected. Do not add a `fetchDoctorProfile` mock just to make fact rows appear unless a test needs them.
- **`fetchPartnerMe` is the live route-state seam after #562**, and `mockFetchPartnerRouteState` is the one to hold open before it. Whichever it is, hold exactly one of the three reads and assert the surface - holding the _third_ read is also legitimate, since it is the last one before `setLanding`.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes. The repo's own comments follow this.
- **This brief is the contract.** Read it, not the world. Grep for line numbers; do not read the component, and do not read the 1218-line test file whole.
