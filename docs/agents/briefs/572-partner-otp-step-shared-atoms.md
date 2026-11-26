# Brief - 572 Partner OTP step: rebuild on the shared sign-in atoms and delete the one-off utilities

**Ticket:** #572 · **Parent:** #560 (front five defects, part 11 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #571 (the ring move + the two shared-atom props - **read `571-shared-signin-atoms-prefactor.md` first**)
**Reading surface:** ~7.2K tokens (budget 10K) - **PASS, within budget**
**Chain position:** 2 of 3. Inherits the atom names, the layout-class names, the test-hook prop name, the ring's new home, and the Enter-to-verify fact from #571's brief. **Do not re-list any of that here.**

## Scope

The partner code-entry step is rebuilt on the atoms the patient wizard already uses. Not restyled - **rebuilt on**. The arbitrary-value and one-off utilities that signal hand-built work are deleted outright, and every state the step carries today survives the swap.

The step's current markup is `StaffLoginForm.tsx:601-672` (the `else` arm of the `stage === "phone"` ternary) plus **six state blocks at `:674-739` that render outside the stage ternary but are part of the code step's surface**. The verify control is `:743-756`.

**One design language for one interaction** - the six-box code input, the countdown ring, the resend ghost, the link-style edit control, the shared error and notice, the primary verify action - is what the patient wizard already ships twenty lines above in the same codebase. That is the whole argument.

## THE CONSTRAINT THAT DECIDES THIS TICKET'S SHAPE

**The staff sign-in suite asserts on this step 50 times by `data-testid` (33 more on `staff-submit`).** Adopting the shared atoms without a test-hook would force a mass rewrite of tests that have nothing to do with this work. **That is precisely why #571 exists**, and it is why the selector census is a done-verify here and not a nicety.

The census (`#571` brief item 9) - every assertion is `toHaveTextContent` or `getByTestId`/`findByTestId`/`queryByTestId`, never a role or class query:

| selector                  | count | element today                                                    | after the swap                                     |
| ------------------------- | ----- | ---------------------------------------------------------------- | -------------------------------------------------- |
| `partner-otp`             | 13    | `<input>` (`:645`)                                               | `OtpInput`'s hidden input, via #571's hook         |
| `partner-error`           | 11    | `<p role="alert">` (`:713-716`)                                  | `ErrorMessage` - already `<p role="alert">`        |
| `partner-resend`          | 6     | `<button>` (`:657`)                                              | `GhostButton`                                      |
| `partner-demo-banner`     | 4     | `<div role="status">` (`:732-734`)                               | `NoticeMessage` **or** a hooked banner - see below |
| `partner-resend-cooldown` | 2     | `<p className="mb-2 text-sm text-on-surface">` (`:691-700`)      | the `.attempts` treatment                          |
| `staff-submit`            | 33    | `<button type="submit">` (`:744-745`)                            | `PrimaryButton` with **#571's type passthrough**   |
| `partner-countdown`       | 1     | bare `<p>` with the seconds (`:611-614`)                         | **the ring**, which carries the hook               |
| `partner-code-expires`    | 1     | `<p className="text-xs opacity-80">` (`:605-610`)                | layout `<p>`, `opacity-80` gone                    |
| `partner-code-hint`       | 1     | `<p className="text-sm text-on-surface">` (`:617-622`)           | layout `<p>`                                       |
| `partner-edit-number`     | 1     | bare `<button className="text-sm underline">` (`:661-669`)       | the link-style edit control                        |
| `partner-attempts`        | 1     | `<p className="mb-2 text-sm text-on-surface">` (`:701-711`)      | the `.attempts` treatment                          |
| `partner-notice`          | 1     | `<p className="mb-2 text-sm text-on-surface">` (`:721-728`)      | `NoticeMessage`                                    |
| `partner-cooldown`        | 1     | `<p>` (`:674-682`) - **phone step**, not code step               | **out of this step's scope**                       |
| `partner-lockout`         | 1     | `<p className="mb-2 text-sm text-danger">` (`:683-690`) - shared | the `.attempts` treatment                          |
| `partner-phone`           | 8     | `<input>` (`:598`) - **phone step**                              | **out of this step's scope**                       |

**Total on the code step: 42 `partner-*` + 33 `staff-submit` = 75 references.** If your diff shows a staff assertion rewritten beyond the handful that must change shape, you have rewritten tests that were not what this work is about.

## THE REGION MAP - one file, six regions

`StaffLoginForm.tsx`, 759 lines. **#571 has already landed, so the import block (`:22-47`) has changed** - re-grep before you trust any line number here.

| #   | lines          | what changes                                                                                                                                                                               |
| --- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `:22-47`       | add the shared-atom imports (`OtpInput`, `ErrorMessage`, `NoticeMessage`, `PrimaryButton`, `GhostButton`, the ring, and the layout stylesheet)                                             |
| 2   | **`:601-672`** | **the step itself.** The `tracking-[0.5em]` input at `:644`, the bare countdown `<p>` at `:611-616`, the `opacity-80` expiry line at `:606`, the hand-rolled resend/edit row at `:649-670` |
| 3   | `:691-711`     | the `partner-resend-cooldown` and `partner-attempts` blocks -> the `.attempts` treatment                                                                                                   |
| 4   | `:712-728`     | `partner-error` -> `ErrorMessage`; `partner-notice` -> `NoticeMessage`                                                                                                                     |
| 5   | `:729-739`     | the demo banner -> the shared **notice** treatment, so it stops reading as an error                                                                                                        |
| 6   | **`:743-756`** | the verify control -> `PrimaryButton` **with `type="submit"`** and the label ternary left alone                                                                                            |

**Region 6 carries the trap.** The label is a four-arm nested ternary (`:749-755`) and #566 already changed it once. **Do not touch the ternary** - you are swapping the element, not the copy, and the operator and MFA arms are out of scope. `disabled` at `:746` is `isOperatorMode || isMfaStep ? loading : partnerBlocked`; the partner arm keeps `partnerBlocked`.

**Regions that must NOT change - the operator branch, wholesale.** `:336-370` (the fresh-operator phone+TOTP submit) and `:315-332` (the masked-phone MFA re-verify path triggered by `SESSION_MFA_REQUIRED`, which sets `mfaContext` at `:359`), and the whole operator render at `:445-555`: `mfa-phone-display` (`:449`), `mfa-input` (`:472`), `mfa-code-error` (`:477`), the `mfaHelp` line (`:483`, **operator branch**), `staff-phone` (`:509`), `staff-totp` (`:541`), `staff-totp-error` (`:546`), the second `mfaHelp` line (`:552`), the `staff-form-summary` (`:438`), and the envelope `staff-login-error` notice (`:420-433`). It shares the page, not the step.

**The two `opacity-80` sites at `:483` and `:552` are the operator branch - out of scope.** The one in this step is `:606`.

## The one-off utilities to delete - and how they are asserted absent

| defect                                                                                                                                           | site                                                                                                           | replacement                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `tracking-[0.5em]` - an arbitrary letter-spacing standing in for the missing six-box input                                                       | `:644`                                                                                                         | `OtpInput` (the `.otpBox` treatment)        |
| `opacity-80` - a bare percentage where a muted-text token exists                                                                                 | `:606`                                                                                                         | the muted-token treatment                   |
| ad-hoc one-off spacing (`mb-4 flex items-center gap-3`, `mb-2 text-sm text-sm`, `w-full rounded-md border border-hairline bg-surface px-3 py-2`) | `:597`, `:625`, `:644`, `:649`, `:656`, `:665`, `:677`, `:685`, `:695`, `:704`, `:715`, `:723`, `:735`, `:747` | the layout classes + the atoms' own styling |

**These must be asserted absent from the source, not from the DOM.** A jsdom test environment applies no stylesheet, so `expect(otp).not.toHaveClass("tracking-[0.5em]")` passes on a class that is still in the source and is a false green. The prior art for a source-level rule is already in the tree and you should copy its shape:

- **`apps/frontend/src/components/auth/otp/variantB.module.test.ts`** - `readFileSync(new URL("./x.css", import.meta.url), "utf8")` at L6-7, then `expect(css).toMatch(...)` on the raw text. Use `readFileSync(new URL("./StaffLoginForm.tsx", import.meta.url), "utf8")` and the same `toMatch` / `not.toMatch` on the three class strings.
- **`apps/frontend/src/app/design-tokens.test.ts`** - `walkSources` / `sourceFiles` / `allSourceFiles` / `SELF` / `cssFiles`, the recursive source discovery (#564's detector). If you would rather scan the whole tree than one file, that is the shape - but one file plus three literal strings is the smaller, more legible gate here.

**Assert three things:** `not.toMatch(/tracking-\[0\.5em\]/)`, `not.toMatch(/opacity-80/)`, and the absence of the specific one-off spacing utilities you replaced. The first two are cheap and total. The third is yours to enumerate - list them.

**Scope note, and it is a real one:** `tracking-[0.5em]` occurs **exactly twice in the whole auth tree** - `StaffLoginForm.tsx:644` (this ticket) and **`ProviderRegisterWizard.tsx:772`**, the partner **registration** wizard. The registration wizard is a different surface, a different ticket, and outside this chain. **Delete this ticket's occurrence; leave the other one and say so on the ticket.** Do not grep-and-fix the pair, and do not let a "while I was there" fix into your diff.

## Key facts / prior art - do not re-derive these

- **All atom names, layout-class names, the ring's new home, the test-hook prop name, and the hook-to-selector mapping are in `571-shared-signin-atoms-prefactor.md`.** Read that brief; do not re-open `shared.tsx`, `otpShared.module.css`, `variantB.module.css`, or `variantB.module.test.ts` to re-derive them. If #571 chose option (b) for the ring's styles, the ring's classes live in `otpShared.module.css`; if (a), in `variantB.module.css`. **Check the brief's Handoff note, then confirm with one grep.**
- **Enter-to-verify works today and must keep working, through the button type, not a key handler.** There is **no** `onKeyDown` anywhere in `apps/frontend/src/components/auth/**`. The mechanism is native form submission: `<form onSubmit={handleSubmit}>` at `:419` plus `<button type="submit">` at `:744`, and `handleSubmit`'s partner arm at `:374-378` dispatches `submitPhone` or `submitOtp`. **#571's `PrimaryButton` defaults to `type="button"`.** If you pass `type="submit"` to it, Enter keeps working; if you omit the prop, Enter-to-verify dies in a real browser and **no test in the suite catches it** - all twelve `typeCodeAndSubmit` sites use `fireEvent.click`. Write a test that closes this.
- **Every state the step carries today, and where it lives.** Expiry copy `t.codeExpires` (`:609`); the countdown `formatCountdown(partner.state.expiresIn)` (`:615`); the code hint with the normalised number `{t.codeHint} <strong>{partner.state.phone}</strong>` (`:621`); the attempt budget `t.attemptsLeft(partner.state.attemptsLeft)` / `t.noAttempts` (`:707-709`); the cooldown `t.resendIn(partner.state.cooldownRemaining)` at both `:680` (phone step) and `:698` (code step); the lockout `t.lockout(Math.ceil(partner.state.lockoutRemaining / 60))` (`:688`); the demo read-back `t.demoOtp(partner.demoOtp)` (`:737`); the last error `partner.state.lastError` (`:718`); the last notice `partner.state.lastNotice` (`:726`). **All nine must still render.** The state fields they read are `PartnerOtpState` at `partnerLoginState.ts:42-58`.
- **The gating conditions on each state block are load-bearing and easy to lose in a rewrite.** `:674-675` cooldown is `stage === "phone" && cooldownRemaining > 0`; `:683` lockout is **`challenge === "locked"` alone** (renders on both stages, no stage guard); `:691-693` resend cooldown is `stage === "otp" && cooldownRemaining > 0 && challenge !== "locked"`; `:701-702` attempts is `stage === "otp" && challenge === "pending"`; `:729-731` the demo banner is `stage === "otp" && demoOtp !== null && otpSends > 0`. The patient wizard's equivalent is a little different (it splits `attemptsLeft > 0` and `=== 0` into two branches at `PatientAuthWizard.tsx:206-211`; the staff step uses a ternary at `:707-709`) - **keep the staff step's own shape**, the suite asserts its text.
- **`partnerBlocked` is `partner.state.busy || partner.state.challenge === "locked"`** (`:386-387`) and it is what disables the shared `OtpInput` (`:639`), the resend (`:653-655`), the edit control (`:664`), and the submit (`:746`). The resend additionally disables on `cooldownRemaining > 0`. Preserve each of those three conditions exactly; `PrimaryButton`'s `disabled={disabled || pending}` (`:172` of `shared.tsx`) means you pass `disabled={partnerBlocked}`, and the "fewer than 6 digits" `pending` gate the patient wizard uses at `:216` is a **separate** behaviour you are not required to add.
- **`NoticeMessage` renders a bare `<p>` with no role** and the demo banner today is `<div role="status">` (`:732-734`). All four banner assertions are `toHaveTextContent`, so **no test will catch the loss of the live region** - but the code arrives asynchronously and `role="status"` is what announces it. Either preserve the role on whatever renders the banner, or argue it. **Do not lose it silently.**
- **The demo banner must stop reading as an error.** Today it is `rounded-md border border-hairline bg-surface px-3 py-2 text-sm` (`:735`) - a bordered neutral box, the same shape as the phone input, sitting directly above the error paragraph. The shared `.notice` treatment is `success-text` on `success-soft` with no border, and the shared `.error` treatment is `danger` on `danger-soft` with a `danger-border`. AC-3 is about the notice, not the error.
- **The staff sign-in page must stay free of the patient's registration value-props and step strip.** That is `t.valueProps` (the `.props` / `.propIcon` list the patient wizard renders at `PatientAuthWizard.tsx:113-132`) and `.steps` / `.step` / `.stepNum` / `.stepLabel` (the wizard's step strip, `variantB.module.css:31-100`). **Neither exists in the staff tree today, and this ticket is what keeps it that way** - the layout classes you adopt must be the step's, not the wizard chrome's. A negative test (`expect(...).not.toBeInTheDocument()` on the value-prop strings, and a class-absence check for `stepNum`) is the cheap way to hold this.
- **The phone step (`:576-600`) is not this ticket's step.** `partner-phone` is asserted 8 times, the phone input's class string is on the same `w-full rounded-md border border-hairline bg-surface px-3 py-2` family the ticket is deleting, and the phone step is the _other_ stage. **Adopting the shared `PhoneInput` is optional and not asked for.** If you leave it alone, say so; if you do swap it, it is a bonus, not a requirement, and it must not cost the phone step its `partner-phone` selector.
- **The step's headline gap is #573, not here.** No heading, no `h1` suppression, no `axe` scan. `apps/frontend/src/app/staff/login/page.tsx:96` is the page's `<h1>`; leave it exactly as it is.

## Read-list (in order)

1. **Issue #572 itself** - the eleven AC and its Context pack (~0.8K).
2. **`docs/agents/briefs/571-shared-signin-atoms-prefactor.md`** - the whole brief (~3.3K on disk, but the ~1.1K of it you need: the two facts, the hook-to-selector table, the Key facts on atom names and layout classes, and the two open decisions). **This is the chain hand-off, not a source re-read.** Then one confirming grep for where the ring's styles live, per #571's Handoff note (~0.1K).
3. **`apps/frontend/src/components/auth/staff/StaffLoginForm.tsx`, four regions, never the whole file (759 lines):**
   - `:22-47` the import block (re-grep - #571 landed and changed it)
   - `:300-387` `envelopeNotice` 300-306, **`handleSubmit` 308-379** (the partner arm at 374-378 is what Enter drives), `errorCount` / `phoneError` / `codeError` / `isMfaStep` 381-384, **`partnerBlocked` 386-387**
   - `:418-444` the `<form>` open, the envelope `staff-login-error` notice, and `staff-form-summary` - so you know the form seam you are staying inside
   - **`:576-757` the entire partner branch plus the submit button** - the region map above, item by item
   - Skip `:59-299` (the login/landing helpers), `:445-575` (the operator branch - you know it is out of scope), `:395-416` (`landingFacts`, #566's). (~2.6K)
4. **`apps/frontend/src/components/auth/staff/StaffLoginForm.test.tsx` L157-212** - `t = STRINGS.en.staffAuth.login`, `PHONE` / `LOGIN_OK` / `SESSION`, and the five helpers: `typePartnerPhone` 180-184, `typeCode` 186-190, **`typeCodeAndSubmit` 192-195**, `startPartnerOtpFlow` 197-203 (`await screen.findByTestId("partner-otp")` - your swap must keep that resolving), `fillPhoneAndTotp` 205-212. (~0.7K)
5. **`apps/frontend/src/components/auth/staff/StaffLoginForm.test.tsx` L469-500** - the head of `describe("StaffLoginForm - partner code step")`, so your new structural assertions land in the right describe. **Do not read the other ~600 lines of the code-step describe or the 12 other tests individually - use the census instead.** (~0.4K)
6. **`apps/frontend/src/components/auth/staff/partnerLoginState.ts` L30-99** - `PartnerStage` 39, `PartnerChallengeStatus` 40, **`PartnerOtpState` 42-58** (all fourteen fields, commented), `PartnerOtpFlow` 60-69 (`demoOtp` is the demo-only read-back, non-null only under `NEXT_PUBLIC_DEMO_MODE`), `partnerInitialState` 71-87, and the demo-mode `useEffect` head at 98-99. (~0.7K)
7. **`apps/frontend/src/components/auth/otp/otpState.ts` L30-39 and L95-103** - the four constants and `formatCountdown`. You are not changing them; you need to know the ring's `frac` divides by `OTP_TTL_SECONDS` and that `partnerLoginState.ts:30-36` already imports from here. (~0.3K)
8. **`apps/frontend/src/lib/i18n/dictionaries.ts` L109-182** - the **en** `staffAuth.login` namespace only (~74 lines). You need it to know which copy already exists - `codeLabel` 155, `codeHint` 156, `codeExpires` 157, `resend` 158, `backToEdit` 159, `resendIn` 160, `attemptsLeft` 161, `noAttempts` 163, `lockout` 167, `demoOtp` 179 - and therefore that **this ticket adds no string at all**. Do **not** read the `hi` half; if you did need it, it is `:1891-1954`, and this ticket's AC-11 says no new user-facing string. (~0.7K)
9. **`apps/frontend/src/app/staff/login/page.tsx` L88-99** - the `<main>`, the wordmark block, the card div, the `<h1>` at `:96`, and the `<StaffLoginForm>` mount at `:97`. That is all you need to know what must **not** appear on this page. (~0.3K)
10. **Grep only, no read** - the census (from #571's item 9, re-run because #562 rewrote this file) and the three-string absence check's setup:
    ```powershell
    $t="apps\frontend\src\components\auth\staff\StaffLoginForm.test.tsx"
    foreach($id in @('partner-otp','partner-error','partner-resend','partner-demo-banner','staff-submit',
      'partner-resend-cooldown','partner-countdown','partner-code-expires','partner-code-hint',
      'partner-edit-number','partner-attempts','partner-notice')){
      $c=(Select-String -Path $t -Pattern $id -AllMatches |
        ForEach-Object { $_.Matches.Count } | Measure-Object -Sum).Sum; "$id = $c" }
    Select-String -Path "apps\frontend\src\components\auth\staff\StaffLoginForm.tsx" -Pattern 'tracking-\[0\.5em\]|opacity-80|data-testid'
    ```
    (~0.1K)

**Total ≈ 7.2K tokens. PASS** (budget 10K).

**Re-grep by name if this no longer resolves:** `partner.state.stage ===|partnerBlocked|partner-demo-banner|staff-submit` in `StaffLoginForm.tsx`; `data-testid` in `shared.tsx` (the hook prop #571 added); `\.ring` in whichever stylesheet #571 left it in. **#571 has to have landed - if the ring is still defined in `PatientAuthWizard.tsx` or `PrimaryButton` still hardcodes `type="button"`, stop.**

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`.** No module, no event, no API, no schema, no session transport, no role vocabulary. `CONTEXT.md`'s ADR-0007 hard gate does not fire - `handleSubmit` and the landing helpers are untouched, and the session is saved exactly where it is today. Nothing in those documents constrains a component swap.
- **`shared.tsx`, `otpShared.module.css`, `variantB.module.css`, `variantB.module.test.ts`.** **#571's brief already tells you every name you need** - the nine atoms, the layout classes, the two new props, and where the ring's styles live. Re-reading them is the context cost this chain exists to avoid. If you find yourself opening `shared.tsx`, you have lost the thread; grep for the one symbol whose behaviour you are unsure of instead.
- **`StaffLoginForm.tsx` `:445-575`** - the operator TOTP step's whole render: `mfa-phone-display`, `mfa-input`, `mfa-code-error`, the two `mfaHelp` lines, `staff-phone`, `staff-totp`, `staff-totp-error`. It shares the page, not the step, and the operator sign-in flow is out of scope for the whole chain. You need the `:315-332` MFA re-verify **submit branch** (in item 3) only to know not to touch it.
- **`StaffLoginForm.test.tsx` beyond item 4 and item 5.** 1218 lines, 52 tests. The `Operator login flow` describe (from `:904`) is not yours. The 12 done-screen tests are #566's. **Do not rewrite assertions** - the census is how you know what to keep.
- **`PatientAuthWizard.tsx` beyond what #571's brief quotes, and `PatientAuthWizard.test.tsx` entirely.** The wizard's code step is the _model_ for this one, and #571's brief already gives you its shape (`:163-222`). Reading it whole is a context switch you do not need, and its `it` names are confusingly similar to the staff suite's.
- **`ProviderRegisterWizard.tsx` and its suite.** It carries the **other** `tracking-[0.5em]` at `:772` and is explicitly **out of scope**. Do not fix it, do not grep-and-fix the pair, do not let it into your diff.
- **`app/staff/login/page.tsx` beyond `:88-99`**, the page's own `h1`, the step's own heading, the `axe` scan. #573.
- **`dictionaries.ts`'s `hi` half and every other namespace.** Read `:109-182` and stop. If you conclude you need a new string, re-read AC-11: this ticket introduces none.
- **The token gate (`design-tokens.test.ts`), the consent surfaces, `DoneScreen.tsx` / `doneScreen.module.css`, `staff-routing.ts`, `return-url.ts`, `ROLE_HOME`.** `doneScreen.module.css` carries an **uncommitted** edit tracked by #561 - keep it out of the diff.
- **Backend code, migrations, e2e specs, `docs/standards/*`.** No standard in this repo covers a frontend component swap, and no e2e spec asserts the partner code step's markup (the three specs are `auth-loop`, `doctor-workspace`, `patient-journey`) - grep to confirm, do not read.

## Baseline verify (must pass before the first edit)

- **Gate: #571 must have landed.** Its acceptance criteria are the preconditions for this ticket's shape - the ring is exported from the shared module, the hook prop exists on the atoms this step adopts, and `PrimaryButton` accepts a `type`. Verify all three with greps, not by reading the file:
  ```powershell
  Select-String -Path "apps\frontend\src\components\auth\otp\shared.tsx" -Pattern 'export function|data-testid|type\?:'
  Select-String -Path "apps\frontend\src\components\auth\otp\PatientAuthWizard.tsx" -Pattern 'CountdownRing'
  ```
  If `CountdownRing` is still a local function there, or `shared.tsx` has no `type?:`, #571 has not landed - stop.
- ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend
  # expect 52 tests green, once #562 has landed
  npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx --root apps/frontend
  # expect 33 tests green, once #563 has landed
  npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend
  # confirmed green 2026-09-27: 7 tests
  ```
- **Confirmed red 2026-09-27** (before the blockers): `StaffLoginForm.test.tsx` **10 failed of 52** = #562; `PatientAuthWizard.test.tsx` **2 failed of 33** = #563. Full-suite measured baseline: `docs/agents/briefs/564-design-token-gate-class-attributes.md` (13 failed / 1519 passed across 3 files; the third is a third-file 5s timeout - a load flake owned by nobody, whose identity moves between runs).
- `npm run test:unit:frontend` - green once #562, #563, and #571 are closed. If a third file still times out at 5s, record it as the pre-existing load flake and move on.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief.
- `git status --porcelain` - the uncommitted `apps/frontend/src/components/auth/doneScreen.module.css` is pre-existing (#561). Not yours; do not commit it.
- **Prove red before green, twice.** The two behaviours that ship silently if you do not:
  1. **Write the source-absence test first** and run it against the unfixed file. It must fail on all three of `tracking-[0.5em]`, `opacity-80`, and your enumerated spacing utilities. A DOM-only assertion would have passed on the broken file - that is the whole reason AC-6 is worded the way it is.
  2. **Write the Enter-to-verify test first** and confirm it fails when `PrimaryButton` is rendered without `type="submit"`. If you write the swap first, this test is green for the wrong reason.

## Done-verify (acceptance criteria -> commands)

- AC-1 (six-box input **and** the countdown ring present) - the structural assertions, in the code-step describe:
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "partner code step"
  ```
  Assert the ring's classes are present and the countdown text (`5:00`) renders **inside** it, plus the six `.otpBox` spans. Remember the ring's wrapper is `aria-hidden="true"` - `getByTestId` finds it (testing-library does not filter by accessibility) and `toHaveTextContent` reads it, so `partner-countdown` can keep resolving. **Decide deliberately** whether the countdown text stays inside an `aria-hidden` element or needs a live treatment; the patient wizard already made that choice, and matching it is defensible, changing it is not this ticket's.
- AC-2 (resend ghost + link edit, laid out as a considered pair): assert the resend row's layout class is present, that the resend carries `partner-resend`, and that `partner-edit-number` is inside the same row.
- AC-3 (demo banner uses the notice treatment, does not read as an error): assert `partner-demo-banner` is present and carries the **notice** treatment - and **preserve `role="status"`** or argue its loss in the PR.
- AC-4 (shared messages + shared primary action): assert `partner-error` renders `ErrorMessage`'s `role="alert"`, `partner-notice` renders `NoticeMessage`, and the submit control is `PrimaryButton` carrying `staff-submit`.
- AC-5 (**Enter verifies inside a real form**):
  ```bash
  # a real test, not a comment: with the code step up, dispatch Enter on the
  # code input (fireEvent.submit on the form, or userEvent.type(input, "{Enter}"))
  # and assert verifyOtp/partnerLogin was called. Then render the same control
  # with the type passthrough omitted and assert it does NOT.
  ```
  This is the one AC whose failure mode is invisible to the rest of the suite.
- AC-6 (**the three utility classes are absent from the source**):
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "absent"
  # the readFileSync-on-"./StaffLoginForm.tsx" test
  Select-String -Path "apps\frontend\src\components\auth\staff\StaffLoginForm.tsx" -Pattern 'tracking-\[0\.5em\]|opacity-80'
  # expect: ONE hit only - ProviderRegisterWizard.tsx:772 is in a different file,
  # so this file must be completely clean.
  ```
- AC-7 (all nine states still carried): one assertion per state, all on the existing selectors, so the census stays valid - `partner-code-expires`, `partner-countdown` (ring), `partner-code-hint` (with the normalised `+919876543210`), `partner-attempts`, `partner-resend-cooldown`, `partner-lockout`, `partner-demo-banner`, `partner-error`, `partner-notice`.
- AC-8 (operator branch unaffected):
  ```bash
  git diff -- apps\frontend\src\components\auth\staff\StaffLoginForm.tsx
  # read your own diff: :315-332 (MFA re-verify), :336-370 (operator submit),
  # :445-555 (the whole operator render) show no behavioural change
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "Operator login flow"
  ```
- AC-9 (page free of the patient's value-props and step strip): assert the value-prop strings are absent and no `stepNum` / `stepLabel` class appears in the staff tree.
- AC-10 (**no mass rewrite** - the criterion #571 was created for):
  ```bash
  git diff --stat -- apps\frontend\src\components\auth\staff\StaffLoginForm.test.tsx
  # the ONLY assertion changes permitted are ones forced by the swap: a control
  # whose element type changed under an existing selector. Everything else
  # (mock block aside, and that is #562's) should be untouched.
  ```
  Re-run the census from item 10 on the post-change file and diff it against the pre-change counts. The counts must be **identical**.
- AC-11 (no new string, parity green): `npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend` green, and
  ```bash
  git diff -- apps\frontend\src\lib\i18n\dictionaries.ts
  # expect: EMPTY
  ```
- The full harness:
  ```bash
  npm run test:unit:frontend
  npm run lint
  npm run typecheck
  ```

### Acceptance criteria as a checklist

- [ ] The step renders the **shared `OtpInput`** (six boxes) and the **shared countdown ring**, and the countdown text renders inside the ring. `partner-otp` still resolves to the hidden `<input>`.
- [ ] The resend control and the "edit number" control use the **ghost and link treatments** from #571 and sit in the considered resend-row layout. `partner-resend` and `partner-edit-number` both still resolve.
- [ ] The **demo-code read-back banner uses the shared notice treatment**, so it no longer reads as an error, and `role="status"` is preserved (or its loss argued in the PR).
- [ ] The error and notice copy use **`ErrorMessage` and `NoticeMessage`**, and the verify control is **`PrimaryButton`**. The label ternary at `:749-755` is **unchanged** - the operator and MFA arms still read `t.signIn` and `t.mfaSubmit`.
- [ ] **Pressing Enter in the code field verifies, inside a real form** - proven by a test that fails without the `type="submit"` passthrough, not asserted by inspection.
- [ ] `tracking-[0.5em]`, `opacity-80`, and the enumerated one-off spacing utilities are **gone from the source**, asserted with a `readFileSync` test (jsdom cannot observe a rendered style, so a DOM assertion here is a false green). The test was **seen failing** on the unfixed file.
- [ ] **All nine states still carry:** expiry copy, countdown, code hint with the normalised number, attempt budget, cooldown, lockout, demo banner, last error, last notice - each with its existing gating condition intact (note the lockout renders on **both** stages).
- [ ] `partnerBlocked` and the resend's extra `cooldownRemaining > 0` disable are preserved on the input, the resend, the edit control, and the submit.
- [ ] The **operator branch is completely unaffected** - both `handleSubmit` sub-branches and the whole `:445-555` render, including its own two `opacity-80` help lines. The `Operator login flow` describe is green and untouched.
- [ ] The staff sign-in page is **free of the patient's registration value-props and step strip**, asserted negatively.
- [ ] The staff suite's selector census is **unchanged** - same counts, no rewrites of assertions that were not forced by the swap. This is the criterion #571 exists to make satisfiable.
- [ ] **`ProviderRegisterWizard.tsx:772`'s `tracking-[0.5em]` is left alone** and recorded on the ticket as the out-of-scope sibling. It is not in your diff.
- [ ] **No new user-facing string**; `dictionaries.ts` has an empty diff and the parity suite is green.
- [ ] The step's own heading, the page's `h1` suppression, and the `axe` scan are **not** in this ticket. If you added them, they belong in #573.

## Handoff notes

- **This ticket is a swap, not a redesign.** Every visual decision is already made in `shared.tsx` and `variantB.module.css`; the work is choosing the right atom per control and deleting what is left over. If you find yourself picking a new padding value or a new colour, you are restyling, which the issue explicitly excludes.
- **The census is the guard against the mistake this ticket is most likely to make.** #571 removed the blocker; the remaining risk is that a dozen convenient-looking assertions get "updated" to match the new markup. Post the pre and post counts on the ticket. A selector that stops resolving is the _intended_ outcome of a missing hook; a selector whose _assertion text_ changed is not.
- **`PrimaryButton`'s `pending` prop is not the same as your disable condition.** `shared.tsx:172` computes `disabled={disabled || pending}`, and the patient wizard passes `pending={state.otpDraft.length !== 6}` at `:216`. The staff step today does **not** disable the submit on a short code - `:746` is `partnerBlocked` only, and the test at `:472` (`typeCodeAndSubmit("123")`) exercises a short code. **Do not import the `pending` gate by reflex** - it is a behaviour change the staff suite may notice, and it is not in scope.
- **The countdown moves from a plain `<p>` into an `aria-hidden` ring.** That is a real change to what a screen reader can reach, and it is what the patient wizard already does. Match it; do not invent a third treatment. But say it in the PR, because it is the one state-preservation claim in AC-7 with a caveat.
- **`partner-edit-number` and the four `.attempts` paragraphs have no atom.** #571's Handoff flags this as its open decision. Whatever it decided, apply it; if it decided "keep them hand-marked", then those five selectors stay on hand-written elements with the hook - and that is a legitimate answer, not a gap to close here.
- **The demo banner's `role="status"` and the four bare `.attempts` paragraphs are the two places this swap can quietly lose semantics.** Both are invisible to the current assertions. Check both by eye in the diff.
- **The phone step shares the file, not the ticket.** `partner-phone` is asserted 8 times and its input sits on the same one-off class family you are deleting from the code step. Adopting the shared `PhoneInput` is a bonus, not a requirement - and it is the single most likely place for an unintended mass-rewrite. If you do not need it, do not do it.
- **Do not reorder the submit-label ternary.** #566 already added a terminal arm; the operator and MFA arms are the reason a "harmless" reorder changes what a non-partner sees.
- **Two earlier blockers, already landed by now** (#562 rewrote the staff suite's mock block; #563 the wizard's done-screen countdown), and #571 is this ticket's direct blocker. The full suite is red until all three close. `dictionaries.test.ts` is green independently.
- **The registration wizard's duplicate `tracking-[0.5em]` is explicitly out of scope** - different surface, different ticket, not in this chain. Fix this ticket's occurrence; leave `:772` and post it as a finding.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes. The repo's own comments follow this.
- **This brief is the contract.** Read it, not the world. Grep for line numbers; do not read `shared.tsx`, do not read the 1218-line staff suite, and do not read the patient wizard.
