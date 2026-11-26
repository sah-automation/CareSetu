# Brief - 579 Partner login: leave the handoff as soon as the console is in hand

**Ticket:** #579 · **Parent:** #577 (part of #529) · **Refreshed:** 2026-09-28
**Blocked by:** #578 (the shared handoff navigation hook - closed first)
**Reading surface:** ~7K tokens (budget 10K) - **PASS**

## Scope

A partner who finishes OTP verification is taken to their console as soon as the console is actually ready, instead of being held for a fixed number of seconds after it has already loaded.

Readiness is the conjunction the flow already implies - the in-flow session resume has settled **and** the post-login destination has been resolved - and that boolean plus the partner's navigate routine go into #578's hook. The hook owns _when_; this flow owns _what ready means_. The "Go to Dashboard" button is wired to the hook's go-now callback rather than to the navigate routine directly, so a press is honoured at once but still never before the destination is in hand.

The navigate routine's refusal goes. It returned early when the destination was unresolved, which was safe only because a countdown used to hold the call back. With the countdown replaced by readiness, the hook cannot call it before the destination exists.

**The frozen-screen defect is fixed by construction, not by a guard.** A destination read slower than the old five seconds can no longer reach a state where the timer stopped, the auto-redirect stopped, and the button is inert. There is no timer left to latch into a refusing handler. Do not add a retry, a readiness check, or a re-arm - that would keep the hazard and only narrow the window.

## Acceptance criteria (from the ticket)

- [ ] The handoff is the only thing on the page while the destination read is held: no orphaned sign-in form, no code input, no second top-level heading, no countdown digits in the progress output.
- [ ] Nothing navigates while readiness is false - advancing well past the old five seconds with the read still held navigates nothing.
- [ ] Exactly one navigation, to the correct console route, once the destination lands - through the framework router, never a hard document replacement.
- [ ] The session is still resumed in-flow before the route is pushed.
- [ ] **The regression case:** a destination read held well past the old countdown duration still produces exactly one navigation when it finally lands, with the button live and doing something throughout.
- [ ] The button navigates immediately rather than after a dwell, never before the destination is in hand, and cannot double-navigate when pressed repeatedly or after navigation has begun.
- [ ] Practice, specialty and destination rows appear when known, skip absent values, and the bar and its message are present before they arrive.
- [ ] A destination read that rejects leaves the handoff up with the envelope explanation and its correlation reference, and no navigation.
- [ ] `Under Verification` and `Rejected` partners reach their status surfaces with no handoff ever rendered.
- [ ] The post-login routing matrix, the three exits of the landing routine, and both operator sub-branches of the submit handler are behaviourally unchanged.
- [ ] The countdown is still present in the shared component at the end of this ticket.

## THE EXACT REGION TO CHANGE

`components/auth/staff/StaffLoginForm.tsx`, four regions. **#578 lands first and does not touch this file**, so these line numbers hold on the tree as of 2026-09-28 - re-grep by name if they do not.

| #   | region                      | symbol                                                                                | what changes                                                                                                                                                                                                                                                                                                       |
| --- | --------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | L275-281                    | `landOnConsole`                                                                       | **Remove the `landing === null` refusal.** It becomes just the `landedRef` latch plus `resumeOnce().then(() => router.replace(landing.target))`. The hook guarantees the destination exists before it calls this, so the refusal is now dead weight that would reintroduce the defect.                             |
| 2   | L676-677                    | the handoff call site                                                                 | `resumePending={!resumeSettled \|\| landing === null}` and `onGoToDashboard={landOnConsole}`. Readiness is _already written_ there - this is the conjunction, exactly as it stands, and it becomes the hook's readiness input. `onGoToDashboard` becomes the hook's go-now callback, **not** the navigate routine. |
| 3   | new, beside the state block | the hook call                                                                         | One call, fed the readiness boolean from region 2 and `landOnConsole` as the navigate routine, exposing the go-now callback for region 2.                                                                                                                                                                          |
| 4   | L212-224, L247-272          | `landing`, `resumeRef`, `landedRef`, `resumeSettled`, `resumeOnce`, the resume effect | **No change.** Read them, do not touch them.                                                                                                                                                                                                                                                                       |

**Regions that must NOT change - the three exits of `landPartnerAfterLogin` (L363-386).** All three stay exactly as they are, and the ticket's routing-matrix criterion is checked by reading your own diff:

1. `window.location.replace(target)` when the route state is not an active doctor - a non-doctor partner, or a pending/rejected partner, is routed **straight away** and never sees a handoff.
2. `await landOn(target)` when the target is not a doctor-console landing - an active doctor bound for a `?return=` deep link outside the console navigates immediately, no handoff.
3. `setLanding({ target, ...(await readPracticeIdentity()) })` - the only path that sets `landing`, therefore the only path where the handoff is ever mounted.

**The sibling `landOn` (L286-296) is a different routine** and is not in scope. It is exit 2's navigator and is guarded only by `landedRef`. Do not merge the two and do not "simplify" by having `landOnConsole` call it.

**The operator branches are untouched.** `handleSubmit` has sub-branches calling `landAfterLogin` (L341) - the MFA re-verify branch and the fresh-operator branch - and `landAfterLogin` keeps its hard `window.location.replace`. They must render and behave identically.

## THE TRAP - the tick is still in the component, and it will lose the race

`DoneScreen` still owns a five-second countdown at the end of this ticket (#581 removes it; that ticket is blocked on this one and on #580). **This is expected and correct:** the hook always wins, because the countdown cannot even start until `resumePending` is false, and readiness is what makes `resumePending` false, and the hook then fires after a sub-second dwell from that same moment.

So the countdown is unreachable in this flow. **Do not remove it, and do not re-tune it** - it is shared with the patient flow, which #580 is rewiring in parallel. Touching it here is how the two tickets collide.

The consequence for your tests: anything that advances five seconds and asserts on the _handoff's_ progress output is asserting on dead code. Retarget those assertions at navigation, not at digits. `StaffLoginForm.test.tsx` has exactly two such assertions and both name the removed constant - see the read-list.

**The second trap, and it is silent.** `landOnConsole` currently returns early on `landing === null`, which is the only thing stopping a premature call from navigating to `null`. Remove the refusal and the _only_ thing preventing a null-target navigation is the hook's readiness contract. If you wire the hook with a readiness boolean that is true one render too early, the flow calls `router.replace(undefined)`. Readiness must be the **conjunction**, and if you want belt-and-braces, assert it rather than guard it.

## The regression test - the technique, and why it is the deliverable

The frozen screen shipped because **nothing in the suite ever looked at the surface or the state between the destination resolving and the countdown expiring.** The pattern that closes that gap:

**Hold the destination promise open, submit the code, assert the intermediate state, then let it land and assert exactly one navigation.** Deterministic, no polling, no `waitFor` on the end state.

The harness for this already exists in the suite and was built for #566 - use it rather than writing new scaffolding:

- `holdDestinationRead()` (~L295) - holds one of the three post-OTP reads open and returns the release
- `waitForReleasedHandoff()` (~L279) - advances to the released handoff
- `completePartnerLoginOnPage()` (~L318) - drives the page-level login
- `stubUnreachableProfileRead()` (~L268) - stubs the best-effort practice-profile read

**The regression test is the one thing in #577 that is purely protective, and the one most likely to be deleted by accident.** Name it so it reads as load-bearing - a name about the slow destination, not about the hook. It must fail if the readiness conjunction is ever weakened to a single signal.

## Key facts / prior art - do not re-derive these

- **The three post-OTP round-trips, in order**, from `landPartnerAfterLogin`: (1) `completeStaffLogin` - the current-user read, which also saves the session locally, which is what makes the resume seam honest about resumability; then the pure `postLoginTarget` decision table, no network; (2) the partner route-state read - **this is where a non-doctor or pending/rejected partner is routed straight away**; (3) the best-effort doctor-profile read, **only on the doctor-console branch**, degrading to nulls with a logged error rather than stranding the login. Holding read 2 or read 3 both produce a handoff held with no destination; holding read 3 is the closer analogue to the reported symptom.
- **`resumeSettled` is a real signal, not a mirror of the destination.** Its effect is keyed on the session being present, so since #566 it runs **concurrently** with the destination reads rather than after them. That is why the handoff can be honest, and it is why the gate is a conjunction rather than one signal. **Do not re-key the resume effect** and do not add a second resume call site - `resumeOnce` is already idempotent by ref.
- **`landingFacts` is built unconditionally and only pushes when `landing !== null`**, which is what lets the handoff render before the destination exists. The fact rows need no change; the acceptance criterion about them is a _test_ criterion.
- **The heading is already handled.** The page's sign-in heading is suppressed via `onOwnsHeadingChange` and the handoff renders its own `h1`, so there is exactly one top-level heading today. Criterion 1 is asserting an existing guarantee, not asking you to build a seam - do not redesign it.
- **The submit control and its four-arm label ternary are #566's and out of scope.** Two tests in the handoff describe block cover them; leave both alone.
- **The practice-profile read is not mocked in this suite.** It runs unmocked, throws, and degrades to nulls - which is why the existing handoff tests see no practice or specialty rows. That is a fact about the harness, not a bug. Do not add a mock unless your test needs fact rows, and if it does, `stubUnreachableProfileRead` is the sanctioned way.

## Read-list (in order)

1. **#579 itself** and the #578 brief - the rule the hook implements and the trap the fresh-identity test closes (~1.2K).
2. **`StaffLoginForm.tsx`, six named regions, never the whole file (868 lines):**
   - L79-124 `completeStaffLogin`, the `DoctorLanding` interface, `readPracticeIdentity` - the three round-trips and the degrade (~0.8K)
   - L205-232 the state block: `landing`, `resumeRef`, `landedRef`, `resumeSettled`, and their comments (~0.5K)
   - L245-296 `resumeOnce`, the resume effect, `landOnConsole`, `landOn` - **the two routines you are changing** (~0.9K)
   - L300-315 the single-fire landing effect keyed on the session (~0.3K)
   - L341-386 `landAfterLogin` and `landPartnerAfterLogin` - the three exits and the operator path you must not touch (~0.9K)
   - L485-506 `landingFacts` (~0.3K)
   - L640-682 the whole `done` branch of the stage render, including the handoff call site (~0.5K)
     (~4.2K)
3. **`StaffLoginForm.test.tsx`, four slices only (1917 lines):**
   - L100-190 the `vi.mock` block and `beforeEach` - note `mockFetchPartnerMe` is hoisted and **has no default**: every test that reads partner status must install one, and `beforeEach` does not reset it for you (~1.0K)
   - L205-345 the flow helpers, including the four #566 ones this ticket reuses (~1.0K)
   - L1422-1503 the handoff describe block's first two tests - the held-instant surface test and the countdown-gate test you are retargeting (~0.8K)
   - L1335-1420 the two #562 routing-row tests and the envelope-notice test - the failure path you must keep green (~0.7K)
     (~3.5K)
4. **`components/auth/DoneScreen.tsx` L1-120** - the header comment (it describes the two-line countdown you are superseding, and is wrong for this flow from here on), the duration constant, the props interface, and the tick plus auto-redirect effects. Enough to know what is still running underneath you; do not edit any of it (~1.0K).
5. **`partnerLoginState.ts` L39-58** - `PartnerStage`, and the session field the landing effect keys on (~0.3K).

**Total ~10.2K counting this brief's own ticket body. On the code alone: ~9K. PASS** (budget 10K). **If you go over, drop read-list items 3's last slice and item 5 first** - the two #562 routing rows and the stage union are the least load-bearing.

**Re-grep by name if any of these no longer resolves:** `landOnConsole|landOn\(|landing === null|resumeSettled|resumePending|landedRef|resumeOnce|stage === "done"|landingFacts|onOwnsHeadingChange` in `StaffLoginForm.tsx`; `holdDestinationRead|waitForReleasedHandoff|completePartnerLoginOnPage|stubUnreachableProfileRead|mockFetchPartnerMe` in the suite. Then refresh this brief.

## Do NOT read

- **`StaffLoginForm.test.tsx` whole.** 1917 lines. The mock block, the eight helpers, and the two tests you retarget are all you need. **Grep by name if you change a shared helper** - the ~90 other tests use them.
- **The operator TOTP step's rendering, the demo banner, the phone step's fields, and the whole OTP step** (the code step's own countdown ring is the OTP _expiry_ timer and is unrelated to the handoff's countdown - do not conflate them). You are changing the `done` branch's wiring and one routine.
- **`PatientAuthWizard.tsx` and its suite.** #580's file, in parallel. Its `it` names are confusingly similar to yours; reading it is a pure context switch.
- **`ProviderRegisterWizard.tsx` and its suite, `staff-routing.test.ts`, `src/proxy.test.ts`, `return-url.ts`, the `ROLE_HOME` table, `postLoginTarget` itself.** The routing matrix is already pinned as a table in two places and you are not changing it - your routing criterion is a _no-change_ criterion.
- **`doneScreen.module.css`** and every other dictionary key. The handoff's appearance is #581's, and its copy is unchanged here.
- **The backends, migrations, `docs/adr/0007-*`.** No cookie, CORS, proxy-guard, `credentials` or deploy-env change, so the ADR-0007 hard gate does not apply. No API contract, no schema, no event, no session-transport change - the session is saved exactly where it is today.
- **`docs/archive/`, the PRD, `internal-modules.md`, the roadmap, the UI blueprint, the other standards.** No architecture or requirement question is in scope. The behaviour is stated completely in the ticket. ADR-0016's invariant - pending and rejected partners bypassing this screen - is preserved by leaving exit 1 alone.
- **The e2e specs.** They do not reference this screen.

## Baseline verify (must pass before the first edit)

- **Gate: #578 must be closed.** The full frontend suite must be green before this ticket's verdicts are trustworthy - you cannot attribute a red suite to your own change on a red baseline.
- **Recorded on 2026-09-28 at `acdb078`:** `npm run test:unit:frontend` is **1 failed / 1645 passed (1646)**. The single failure is the known unowned 5s load flake in `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx`, documented in #566's brief. **Not yours.** If a _second_ file fails, that one is yours.
- `npm run typecheck` and `npm run lint` - both clean at that commit.
- The fast loop, and the specific red this ticket is about:
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend
  # expect green, ~90 tests
  npx vitest run src/components/auth/DoneScreen.test.tsx --root apps/frontend
  # expect green, 8 tests - the component is not yours yet, so this must not move
  ```
- `git status --porcelain` - the untracked `docs/agents/briefs/*.md` files are pre-existing repo habit. Do not stage them.

## Done-verify (acceptance criteria -> commands)

```bash
npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend
npm run test:unit:frontend
npm run typecheck
npm run lint
```

Criterion by criterion. **Write the regression test first and see it fail against the unfixed form** - a regression test that has never been seen red is not evidence; capture the red on the ticket.

- **AC-1 (only thing on the page, no digits)** - the existing held-instant test, extended: at the held instant the handoff heading is present, `partner-otp` and `staff-submit` are absent, exactly one `h1` is on the document, and the progress output carries no digits. Assert it **synchronously** - no `waitFor`, no `findBy`, no polling.
- **AC-2 (nothing while not ready)** - the negative half, and it is the half that matters: with the destination held, advance well past the old duration and assert `mockReplace` was **not** called. A readiness boolean of just `resumeSettled` fails this.
- **AC-3 (exactly one, correct route, router not reload)** - release the destination, assert `mockReplace` called once with the console route. Assert it is `mockReplace` and not `mockLocationReplace` - the no-hard-reload invariant.
- **AC-4 (resume before route)** - assert the ordering, not just the destination: the session-resume call precedes the `router.replace`. The wizard suite has a sibling of this test; copy its assertion shape.
- **AC-5 (the regression case)** - hold the destination far past the old duration with the button **enabled and asserted live** partway through, then release, then assert `mockReplace` called **exactly once**. This is the ticket's most important test.
- **AC-6 (button honoured, once only)** - press go-now while the destination is held: not called. Press it again: still not called. Release, let the dwell elapse: called exactly once. Also press after navigation has begun and assert the call count does not move.
- **AC-7 (facts and a never-empty screen)** - the facts test, plus an assertion that the progress indicator and status line are present _before_ the facts land.
- **AC-8 (rejected destination)** - extend the existing envelope-notice test rather than adding a parallel one: the handoff stays visible, the `role="alert"` explanation and its trace id are present, and `mockReplace` was not called.
- **AC-9 (pending and rejected bypass)** - extend the existing `it.each` rows; do not duplicate. Assert the handoff is **absent** and `mockLocationReplace` got the status target.
- **AC-10 (nothing else moved)** - read your own diff:
  ```bash
  git diff -- apps/frontend/src/components/auth/staff/StaffLoginForm.tsx
  ```
  `landPartnerAfterLogin`'s three exits, `landAfterLogin`, `landOn`, and both operator sub-branches of `handleSubmit` must show no behavioural change.
- **AC-11 (the countdown is still there)** -
  ```bash
  git diff -- apps/frontend/src/components/auth/DoneScreen.tsx apps/frontend/src/components/auth/doneScreen.module.css
  # expect: empty. The component and its stylesheet are #581's, and the
  # stylesheet must not appear in your diff at all.
  ```

## Handoff notes

- **The change is one boolean and one routine.** Everything hard here is downstream of feeding the _existing_ conjunction into the hook and dropping the refusal. If you are restructuring the landing effect, the three exits, or the OTP step, you have left the ticket.
- **The refusal removal is the whole defect fix, and it is only safe because of the hook.** Read that sentence twice. Removing the refusal _without_ the hook's readiness contract is strictly worse than the bug: you would navigate to `undefined`. The order of the two edits does not matter; the presence of both does.
- **Do not add a retry, a readiness check, or a re-arm inside the component.** #577 explicitly prefers the defect fixed by construction over a guard, because a guard keeps the timer and the hazard and only narrows the window.
- **Your test must assert the intermediate state, not the end state.** Every existing handoff test in this file is a `waitFor` on the settled outcome, and that is precisely why a blank card with a live button shipped once already. The test you write is as much the deliverable as the code change.
- **The countdown is dead code in this flow and that is fine.** Do not remove it, do not re-tune it, do not touch its stylesheet - #580 is rewiring the other consumer in parallel and #581 deletes the timer for both.
- **`mockFetchPartnerMe` has no default and `beforeEach` does not reset it.** A test that reads partner status without installing an answer gets a leaked one from whichever test ran before it. That is #562's harness, and it is deliberate; install what you need.
- **No em-dashes anywhere** in code, comments, or the commit message - the `no-em-dash gate` pre-commit hook enforces it and the codebase follows the rule in its own prose. Use simple dashes.
- **Leave #566 and #537 exactly as they are.** #577 supersedes two of #566's unchecked acceptance criteria _by reference, not by amendment_, and removes the duration #537 specified. Do not close or edit either issue.
- **This brief is the contract.** Read it, not the world. Do not read the component's stylesheet, the wizard, the dictionary, or the 1917-line suite whole.
