# Brief - 573 Partner OTP step: its own heading, the page heading yields, accessibility scan clean

**Ticket:** #573 · **Parent:** #560 (front five defects, part 12 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #572 (the shared-atom swap - read `572-partner-otp-step-shared-atoms.md` and its parent `571-shared-signin-atoms-prefactor.md` first)
**Reading surface:** ~6.2K tokens (budget 10K) - **PASS, within budget**
**Chain position:** 3 of 3, and the last. Inherits the atom names, the layout-class names, the test-hook prop names, the step's test-id census, and the ring's new home from #571 and #572. **Do not re-list any of that here.**

## Scope

Three things, all small, one of which is a seam you have to design rather than a line you have to write:

1. **The code step carries its own heading**, so a partner knows which step they are on without reading the surrounding copy. Drawn from the shared string dictionary, in **both** locales.
2. **The page-level "Sign in" heading yields to it.** The page puts its `<h1>` above the whole form; once the step owns a heading, the page must end up with **exactly one** top-level heading on **every** stage, or the scan goes red and the document structure regresses.
3. **An automated accessibility scan on the step reports zero violations**, using the seam the patient profile page already uses.

**This is the last ticket in the chain.** It adds no component, restyles nothing, and moves no state. If you find yourself re-litigating the code step's markup, you are in #572.

## THE HEADING-COUNT TRAP - "every stage" is three stages, not two

The page has exactly **one** `h1` today, and by the time this ticket lands each of the three stages needs exactly one - **from a different owner**:

| stage   | the one `h1`               | owner                                                                  | status today                                                       |
| ------- | -------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `phone` | `t.heading` = "Sign in"    | **`app/staff/login/page.tsx:96`**                                      | present                                                            |
| `otp`   | **the step's new heading** | **`StaffLoginForm.tsx`** (this ticket)                                 | **missing - you add it**                                           |
| `done`  | `DoneScreen`'s own `<h1>`  | **`DoneScreen.tsx:128`** (`<h1 className={styles.title}>{title}</h1>`) | present; #566 already required the page heading be suppressed here |

**The suppression is therefore not one branch, it is two.** Suppressing the page `h1` only on the `otp` stage leaves the `done` stage with two `h1`s - `DoneScreen`'s plus the page's - which is exactly the regression #566's brief flagged and exactly what an `axe` page-order or `heading-order` rule can catch. Suppress on **`otp` and `done`**; keep it on `phone`. If #566 has not already suppressed it on `done`, this is your job and say so in the PR.

**The prior art for the step heading is the patient wizard, and it is one line.** `PatientAuthWizard.tsx:112` (phone step) and `:169` (code step) both render `<h1 className={stylesB.title}>{t.verify}</h1>`. So the shared step's own heading is an **`h1` carrying the `.title` class**, not an `h2` and not a `<p>` - which is what makes "exactly one top-level heading" achievable at all.

## THE SUPPRESSION IS A SEAM YOU MUST DESIGN

**The `h1` lives in the page; the stage lives in the form.** `page.tsx:96` renders the heading and `:97` renders `<StaffLoginForm role={role} returnTarget={returnTarget} />` - `StaffLoginForm` knows the stage (`partner.state.stage === "otp" | "done"`) and knows nothing about the page's chrome. You cannot suppress the heading from inside the form without a signal crossing that boundary. Three shapes, all legitimate:

- **lift the stage (or a derived "the form owns a heading" boolean) up to the page** - the page reads it and conditionally renders the `h1`;
- **render the heading slot as a prop** the page passes and the form fills;
- **move the heading into the form** and delete `page.tsx:96` entirely - cleanest, and it makes "exactly one" structural rather than conditional, but it relocates the phone stage's heading, which AC-5 forbids changing.

**Say which you chose and why in the PR.** The failure mode to avoid is a suppression that works on the `otp` stage in a unit test and leaves two `h1`s on `done`, or that quietly deletes the phone stage's heading to make a count assertion pass.

**And the tests live in two different files, for a concrete reason.** `StaffLoginForm.test.tsx` renders `<StaffLoginForm />` **bare** - no page, so the page `h1` is not in that DOM at all; the step's heading and its scan belong there. `app/staff/login/page.test.tsx` renders the **real** page including the real form (only `next/navigation`, `@/lib/auth/AuthContext` and `@/lib/partner/api` are mocked, at `:15-28`), so the page-level suppression and the cross-stage `h1` count belong there. **Splitting the assertions across the two files is correct, not a dodge** - say so, because a reader will otherwise assume one of them is missing the other half.

## The accessibility scan - the prior art, exactly

There is **no shared scan helper module.** Six suites import `axe-core` and each does its own:

- **`apps/frontend/src/app/(patient)/patient/profile/page.test.tsx`** - **the named prior art.** `import * as axe from "axe-core"` at `:21`, and three call sites: **`:465-477`** (`"scans clean on axe with a completed profile rendered"`), **`:479-491`** (`"...with the blocked-save explanation rendered"`), **`:580-592`** (`"...with all three zones rendered"`). Every one is the same shape: `render(...)` -> `await waitFor(...)` on the surface's readiness -> `expect((await axe.run(container)).violations).toEqual([])`. **Each has its own local render-and-wait; none is extracted.** Copy that shape; do not build a shared helper, and do not add a fourth abstraction layer to a codebase that has six copies of this already.
- The other five, for reference on the `container` vs `document.body` vs scoped-node choice: `HealthBackgroundZone.test.tsx:1010,1026` (`document.body`), `ProfileCompletionWizard.test.tsx:204,208` (`container` and a step-scoped node), `ProfileNudges.test.tsx:230` (`container`), `ConsentSheet.test.tsx:279` and `AppShell.test.tsx:596` (`const { violations } = await axe.run(...)`), `AccountMenu.test.tsx:791` (`screen.getByRole("menu")`). `axe-core` is a root devDependency at `^4.13.0` - **nothing to install.**
- **For this ticket, `container` is the right target**, matching the profile page and scoping the scan to the step rather than the page's surrounding chrome. If you scan `document.body` you take on the page's own violations - the wordmark link, the register CTAs - and this ticket does not own them.

**The step needs the scan to be red-capable.** Write it, run it against the pre-fix tree, and capture the red. A scan that is green before and after is a scan that never saw the two-`h1`s state.

## Key facts / prior art - do not re-derive these

- **The new string is a plain string key in the `staffAuth.login` namespace**, and it needs **no arity care**: the parity gate's arity rule (`:33-36` of the differ) only fires on **functions**. A string key present in both locales at the same path is enough. If you find yourself writing `(n: number) =>` for a step heading, stop - that is a different string than the one you want.
- **The namespace to add to, in both locales, and nowhere else:** `dictionaries.ts` **`:109-182`** (en, `staffAuth.login`, 74 lines) and **`:1891-1954`** (hi, the same namespace, 64 lines - Hindi is more compact, which is why the two blocks are different lengths). `staffAuth` opens at `:108` (en) and `:1890` (hi); the namespace closes at `:182` / `:1954`, where `pending:` begins. The page's existing heading is `staffAuth.login.heading` at **`:112`** (en, `"Sign in"`) and **`:1894`** (hi).
- **The parity gate is a hand-rolled recursive differ, not a schema tool.** `apps/frontend/src/lib/i18n/dictionaries.test.ts` (127 lines): `parityProblems(en, hi, path)` at `:13-64` returns `string[]` of `"<path>: <reason>"` findings rather than throwing, and it checks four things - **missing key in either locale** (`:42-49`), **array length mismatch** (`:18-20`), **function arity mismatch** (`:33-36`), **type mismatch** (`:60-62`). Two positive tests (`:67-73`) and **five negative self-tests** (`:76-127`) that feed deliberately broken copies through the _same_ checker and assert the exact finding string - missing-from-hi, missing-from-en, string-reshaped-to-function, array-length-diverged, element-type-diverged-inside-an-array. **A new key present in `en` and absent in `hi` fails mechanically as `".staffAuth.login.<key>: missing from hi"`.** That is the whole gate; run it, do not reason about it.
- **The heading's copy is not the page's copy.** The page's `heading: "Sign in"` answers "what page am I on"; the step's answers "which step am I on". The patient wizard's equivalent is `t.verify` (`dictionaries.ts`, the `auth` namespace, used for both its steps - so even the patient wizard reuses one string across two steps). **Decide deliberately** whether the partner step's heading is a new key or a reuse of an existing `staffAuth.login` string; a new key is what AC-1 and AC-4 imply, and a reuse is a legitimate cheaper answer **only if you say so and the parity gate still passes.**
- **The code step's other heading-bearing copy already exists and does not move:** the expiry line `t.codeExpires`, the hint `t.codeHint`, the label `t.codeLabel` (all `staffAuth.login`, `:155-157`). #572 already moved them into the shared layout. **Do not reword them.**
- **AC-5 pins the rest of the page's heading arrangement.** The phone step keeps the page's "Sign in" and gains no heading of its own. **The operator branch keeps its current arrangement** - it shares the page, and `page.tsx:96` is the _only_ `h1` in the operator path today, so the suppression must not fire when `role="operator"`. The suppression is a **partner** condition, not a role-agnostic one.
- **The page's other copy is untouched:** the wordmark `<span className="text-lg font-bold">CareSetu</span>` at `:35`, the `t.subtitle` line at `:92`, `t.newHereTitle` / `t.newHereBody` at `:103-104`, the three register CTAs at `:105-127`, and the `t.noRolePickerNote` / `t.interimNote` block at `:130-142`. Only the `h1` at `:96` is in play.

## Read-list (in order)

1. **Issue #573 itself** - the six AC and its Context pack (~0.7K).
2. **`docs/agents/briefs/572-partner-otp-step-shared-atoms.md`** - the ~0.8K of it you need: the region map, the hook-to-selector census, and the Handoff notes on the atoms and the `.title`/`.sub` classes (~0.8K). **Then its parent #571's brief for the ring's new home and the two props** (~0.4K) - both are the chain hand-off, not source re-reads. Re-grep once to confirm where the ring's styles live (~0.1K).
3. **`apps/frontend/src/lib/i18n/dictionaries.ts`, two regions and nothing else** - **`:109-182`** (en `staffAuth.login`: `heading` 112, the partner-OTP block 152-181, `demoOtp` 179, `verifiedTitle` / `verifiedBody` 180-181) and **`:1891-1954`** (hi `staffAuth.login`: `heading` 1894, the same keys). **This is ~2KB of source; the file is 206KB / 3339 lines. Never read it whole.** If you need `pending:` or any other namespace you have gone out of scope. (~1.3K)
4. **`apps/frontend/src/lib/i18n/dictionaries.test.ts`, whole (127 lines)** - `parityProblems` 13-64 (all four rules), the two positive tests 66-74, and the five self-tests 76-127. Small, and it is the gate you must not break. (~1.1K)
5. **`apps/frontend/src/app/(patient)/patient/profile/page.test.tsx`, three regions** - `:21` (the `import * as axe from "axe-core"` line in context), **`:465-491`** (the two render-and-wait scans verbatim), **`:580-592`** (the third). **Do not read the other 750 lines** - the file is a profile-settings suite and only its scan shape is prior art. (~0.6K)
6. **`apps/frontend/src/app/staff/login/page.tsx` L88-99** - the `<main>`, the wordmark block, the subtitle at `:92`, the card div, **the `<h1>` at `:96`**, and the form mount at `:97`. Then **L100-142** so you know what else is on the page and must not move. (~0.4K)
7. **`apps/frontend/src/app/staff/login/page.test.tsx` L1-80** - the header comment, the `next/navigation` / `AuthContext` / `partner/api` mock block at `:15-28` (**note `@/lib/auth/api` is NOT mocked**), `mockSession` 30-40, the `beforeEach` / `afterEach` at `:42-58` (which does `mockSession(null)` and resets `searchParamsValue` - so every test starts on a signed-out visitor, i.e. the **phone** stage), and the first two `it`s 64-78. Note **there is no heading assertion in this file at all today** - this ticket adds the first. (~0.7K)
8. **`apps/frontend/src/components/auth/DoneScreen.tsx` L120-135** - just the render head, to confirm `<h1 className={styles.title}>{title}</h1>` at `:128` and see what surrounds it. You need to know the `done` stage already owns a top-level heading; you are not changing this file. (~0.2K)
9. **Grep only, no read:**
   ```powershell
   # where the step's heading will live, and the class it will carry
   Select-String -Path "apps\frontend\src\components\auth\staff\StaffLoginForm.tsx" -Pattern 'stylesB.title|styles.title|stylesB.section|<section'
   # the two stylesheet classes the heading adopts
   Select-String -Path "apps\frontend\src\components\auth\otp\variantB.module.css","apps\frontend\src\components\auth\otp\otpShared.module.css" -Pattern '^\.title|^\.sub'
   # the patient wizard's one-line precedent
   Select-String -Path "apps\frontend\src\components\auth\otp\PatientAuthWizard.tsx" -Pattern '<h1'
   # and the h1 census on the staff surfaces
   Select-String -Path "apps\frontend\src\app\staff\login\page.tsx","apps\frontend\src\components\auth\staff\StaffLoginForm.tsx","apps\frontend\src\components\auth\DoneScreen.tsx" -Pattern '<h1'
   ```
   (~0.1K)

**Total ≈ 6.2K tokens. PASS** (budget 10K).

**Re-grep by name if this no longer resolves:** `partner.state.stage ===` in `StaffLoginForm.tsx` (the suppression's condition); `<h1` across the three staff-surface files (the count); `staffAuth` in `dictionaries.ts` (the namespace boundaries). **#572 has to have landed - if the step still renders a bare `<input>` with `tracking-[0.5em]`, or the ring is still private to the patient wizard, stop.**

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`dictionaries.ts` beyond `:109-182` and `:1891-1954`.** It is **206KB / 3339 lines.** Reading it whole is the single most expensive mistake available on this ticket. Never read it in full, never open it in an editor without a line range, and never `Get-Content` it unfiltered.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`.** No module, no event, no API, no schema, no session transport, no role vocabulary. `CONTEXT.md`'s ADR-0007 hard gate does not fire - nothing here touches a cookie, a CORS rule, a middleware, a `credentials` option, or a deploy env var. AC-1 through AC-6 are stated completely in the issue.
- **`shared.tsx`, `otpShared.module.css`, `variantB.module.css`, `variantB.module.test.ts`.** #571's brief gives you every name. The only thing you need from the stylesheet is the `.title` rule, and item 9's grep gets it.
- **The partner code step's markup and state.** #572's brief has it. You are adding a heading and a scan, not re-reading 160 lines of JSX.
- **`StaffLoginForm.test.tsx` beyond one grep.** 1218 lines, 52 tests, and 75 of its assertions are #572's census. You need **one** place to put the step's heading assertion and the scan; grep the code-step describe's head. Do not read the operator describe.
- **`PatientAuthWizard.test.tsx`, `ProviderRegisterWizard.tsx` and its suite, `staff-routing.ts`, `AuthContext.tsx`, `return-url.ts`.** The wizard's one-line `<h1>` precedent is item 9's grep; the rest is other tickets' and other surfaces'.
- **The five other `axe-core` suites beyond the profile page's three sites.** Item 5 is the prior art. Knowing that four other files call `axe.run(document.body)` or a scoped node is background, not instruction - you are scanning `container`.
- **Backend code, migrations, e2e specs, `docs/standards/*`.** No standard in this repo covers a heading or a test-only accessibility scan. `@axe-core/playwright` also exists at `^4.13.0` and is for the e2e suite - **not** this ticket; the issue names the unit-test seam.

## Baseline verify (must pass before the first edit)

- **Gate: #572 must have landed**, and #571 and #562/#563 before it. Verify the step is on the shared atoms with one grep (item 9's first line plus `tracking-\[0\.5em\]` returning nothing in `StaffLoginForm.tsx`).
- ```bash
  npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend
  # confirmed green 2026-09-27: 7 tests, and it is green independently of the
  # blockers - this is the loop you will iterate the new string against
  npx vitest run src/app/staff/login/page.test.tsx --root apps/frontend
  # expect 15 tests green
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend
  # expect 52 tests green
  ```
- **Confirmed red 2026-09-27** (before the blockers): `StaffLoginForm.test.tsx` **10 failed of 52** = #562; `PatientAuthWizard.test.tsx` **2 failed of 33** = #563. Full-suite measured baseline: `docs/agents/briefs/564-design-token-gate-class-attributes.md`.
- `npm run test:unit:frontend` - green once #562, #563, #571, #572 are closed.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief.
- `git status --porcelain` - the uncommitted `apps/frontend/src/components/auth/doneScreen.module.css` is pre-existing (#561). Not yours; do not commit it.
- **Prove the scan is red-capable before you make it green.** Add the step heading **and** the scan, and run the scan against the tree where the page `h1` is still rendered. It must report a violation, and that violation must be about the duplicate top-level heading - not about something incidental you then went and fixed. Capture the red on the ticket. A scan that was never seen failing is not evidence of anything.

## Done-verify (acceptance criteria -> commands)

- AC-1 (the step carries its own heading, from the dictionary):
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "heading"
  # assert the heading is present on the otp stage, that it is an h1, and that it
  # carries the shared title class - matching PatientAuthWizard.tsx:169
  ```
- AC-2 (**exactly one** top-level heading on **every** stage) - the count, not the absence:
  ```bash
  npx vitest run src/app/staff/login/page.test.tsx --root apps/frontend -t "heading"
  ```
  Assert `container.querySelectorAll("h1")` has length **1** on the phone stage, on the `otp` stage, and on the `done` stage. **A test that only asserts the page heading is gone passes while the `done` stage has two `h1`s** - the count is the criterion, and #566's brief already records that `DoneScreen` renders its own `h1` at `:128`.
- AC-3 (**the scan reports zero violations**):
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "axe"
  # import * as axe from "axe-core"; render the step; await the waitFor; then
  # expect((await axe.run(container)).violations).toEqual([])
  ```
  Same shape as `page.test.tsx:465-477` - no shared helper, no new abstraction.
- AC-4 (the new string in **both** locales at equal arity):
  ```bash
  npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend
  # 7 tests green - and it was run against the tree with the new key present
  git diff -- apps\frontend\src\lib\i18n\dictionaries.ts
  # expect: exactly one added key in EACH of staffAuth.login (en) and
  # staffAuth.login (hi). One side only is a red parity suite, not a warning.
  ```
- AC-5 (**no other heading on the page changes**):
  ```bash
  git diff -- apps\frontend\src\app\staff\login\page.tsx
  # expect: the h1 at :96 suppressed by a condition, nothing else touched
  npx vitest run src/app/staff/login/page.test.tsx --root apps/frontend -t "operator"
  # the operator form still renders, and the page h1 is still there for it
  ```
  The phone step keeps the page's heading and gains none of its own. The operator branch is untouched.
- AC-6 (page still free of the patient's value-props and step strip): the negative test #572 added stays green; do not re-derive it.
- The full harness:
  ```bash
  npm run test:unit:frontend
  npm run lint
  npm run typecheck
  ```

### Acceptance criteria as a checklist

- [ ] The code step carries **its own heading**, drawn from `staffAuth.login`, rendered as an **`h1` carrying the shared `.title` class** - matching the patient wizard's one-line precedent at `PatientAuthWizard.tsx:169`.
- [ ] The page-level sign-in heading is **suppressed on the `otp` stage and on the `done` stage**, and **kept on the `phone` stage** and for the **operator** branch. The suppression is a partner condition, not a role-agnostic one.
- [ ] **Exactly one `h1` on all three stages, asserted as a count** - not as the absence of a name. A test that only checks the page heading is gone passes while `done` carries two.
- [ ] The suppression mechanism is a **deliberate seam** (signal lifted to the page, a heading slot passed down, or the heading moved into the form), and the choice is stated in the PR. The form does not silently learn the page's chrome and the page does not silently lose its heading.
- [ ] **An `axe-core` scan on the step reports zero violations**, in the `page.test.tsx:465-477` shape: `import * as axe from "axe-core"`, `render`, `await waitFor(...)`, `expect((await axe.run(container)).violations).toEqual([])`. **No shared scan helper is introduced** - the six existing copies are each local and this is the seventh.
- [ ] The scan was **seen failing** on the pre-fix tree, and the violation it reported was the duplicate top-level heading. The red output is on the ticket.
- [ ] The new string is present in **English and Hindi at the same path** in `staffAuth.login`, and `dictionaries.test.ts` is green. A plain string needs no arity care; a function would.
- [ ] **The `h1` count assertions are split across the two right files** - the step's heading and scan in `StaffLoginForm.test.tsx` (which renders the form bare), the page-level suppression and the cross-stage count in `page.test.tsx` (which renders the real page and real form).
- [ ] The **phone step keeps the page's heading and gains none of its own**; the **operator branch's heading arrangement is unchanged**; the wordmark, subtitle, `newHere` block, register CTAs, and role-picker note are byte-identical.
- [ ] No component is added, no state moves, no class beyond the shared `.title` is introduced, and the code step's existing copy (`codeExpires`, `codeHint`, `codeLabel`) is not reworded.
- [ ] The staff page stays **free of the patient's registration value-props and step strip** - #572's negative test still green.
- [ ] `doneScreen.module.css` is untouched and stays out of the diff.

## Handoff notes

- **This is the smallest ticket in the chain and the only one whose difficulty is architectural.** Two strings, one conditional, one scan. The whole ticket is the question "how does the page learn that the form owns a heading", and the answer is three lines of a seam.
- **Assert the count, not the name.** "The page heading is suppressed" is satisfied by deleting `page.tsx:96` outright - which would also delete the phone stage's heading, breaking AC-5. `container.querySelectorAll("h1").length === 1`, on all three stages, is the only assertion that catches both mistakes.
- **The `done` stage is the trap.** `DoneScreen.tsx:128` renders its own `h1` and has since #566. If #566 suppressed the page heading there, your job is the `otp` stage alone; if it did not, suppressing only `otp` leaves two `h1`s on the terminal screen - the exact regression #566's brief predicted. **Check which it is** rather than assuming, and if you are adding the `done` suppression, say so in the PR so #566's record is not contradicted.
- **Do not extract a shared `axe` helper.** Six suites call `axe.run` each in their own way; the house pattern is a local render-and-wait per call site. A seventh shared module is a refactor this ticket does not own.
- **Scan `container`, not `document.body`.** `document.body` drags in the page's own chrome - the wordmark link, the three register CTAs, the role-picker note - and this ticket does not own those. `HealthBackgroundZone.test.tsx` uses `document.body` because it is a component suite with no page; the profile **page** suite uses `container`, which is your case.
- **The dictionary is a 206KB file and a parity gate, in that order.** A missing Hindi key fails mechanically as `".staffAuth.login.<key>: missing from hi"`, so the failure is loud - but only if you actually run `dictionaries.test.ts`, which is green independently of every blocker in this chain. It is the cheapest command you will run all session; run it after the dictionary edit, not at the end.
- **A new key and a reused key are both defensible; an unstated one is not.** The patient wizard reuses `t.verify` for both its steps, so reuse has precedent. AC-1 and AC-4 read as a new key. If you reuse, say which existing string and why the copy is right for this step - `heading: "Sign in"` answers a different question than "which step am I on".
- **`StaffLoginForm.test.tsx` renders the form bare, so it structurally cannot see the page heading.** Do not "fix" that by rendering the page inside the form suite; the split is correct, and `page.test.tsx` already renders the real page with the real form, which is where the cross-stage count belongs.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes. The repo's own comments follow this.
- **This is the chain's last ticket.** #571 owns the atoms and the ring, #572 owns the swap. If you need a change to either, post it as a finding on the parent (#560) rather than absorbing it here - the chain is designed so each ticket is small enough to review on its own.
- **This brief is the contract.** Read it, not the world. Never read `dictionaries.ts` whole; never read the 1218-line staff suite.
