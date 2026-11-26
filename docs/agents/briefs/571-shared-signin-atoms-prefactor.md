# Brief - 571 Prefactor: lift the countdown ring into the shared module, add control test-hooks and a button-type passthrough

**Ticket:** #571 · **Parent:** #560 (front five defects, part 10 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #562, #563 (the red-test baseline repair - the full frontend suite must be green before this ticket's verdicts are trustworthy)
**Reading surface:** ~8.3K tokens (budget 10K) - **PASS, within budget**
**Chain position:** 1 of 3. This brief is the chain's foundation. #572 and #573 read it first and must not re-list anything established here.

## Scope

A pure move plus two prop additions. Nothing a user can see changes on the patient sign-in surface.

1. **The countdown ring moves out of the patient wizard into the shared module.** Today it is a **non-exported local function** - `function CountdownRing({ seconds }: { seconds: number })` at `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx:69` - consumed only by that file's own `OtpStep` at `:173`. After this ticket it is exported from the shared module and both wizards can render it.
2. **The shared controls gain a test-hook and a button-type passthrough** - see the two facts below. These exist purely so that #572 can adopt the atoms without mass-rewriting a staff suite that has nothing to do with this ticket.

**Do not "improve" the ring while you move it.** No restyle, no new aria, no copy change, no resize. The patient wizard's rendered output must be byte-equivalent, and its suite must stay green **unchanged in what it asserts**.

## THE TWO FACTS THAT SHAPE THE PROPS

### Fact 1 - Enter-to-verify works today, and only because the button is `type="submit"`

**There is no Enter handler anywhere in the auth tree.** `grep 'onKeyDown|key === "Enter"|keyCode === 13'` across `apps/frontend/src/components/auth/**` returns **zero matches**. The mechanism is native HTML form submission, and it is already correct:

- `StaffLoginForm.tsx:419` - `<form onSubmit={handleSubmit} noValidate data-testid="staff-login-form">`
- `StaffLoginForm.tsx:743-744` - the verify control is `<button type="submit" data-testid="staff-submit" ...>`

Implicit submission (Enter in the form's single text input) fires `onSubmit` -> `handleSubmit` -> the partner branch at `:374-378` (`partner.state.stage === "phone" ? partner.submitPhone(partnerPhone) : partner.submitOtp()`).

**The trap:** the shared `PrimaryButton` hardcodes `type="button"` (`shared.tsx:170`). Swapping the partner step's submit control for `PrimaryButton` **without** a `type` passthrough silently breaks Enter-to-verify in a real browser, and **no test will catch it** - all twelve `typeCodeAndSubmit` sites in `StaffLoginForm.test.tsx` drive it with `fireEvent.click(screen.getByTestId("staff-submit"))`, never a keydown. That is the entire reason for prop addition 2.

### Fact 2 - the staff suite's selectors land on four different elements

The staff suite reaches into this step **50 times** by `data-testid` (counts in the table below). A test-hook on an atom is only useful if it lands on the **same element the selector already resolves to**, so the hook has to be plumbed to the right node per atom, not smeared on a wrapper:

| selector today                                                                                 | element it is on                              | atom that must carry the hook                                                                                 |
| ---------------------------------------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `partner-otp` (x13)                                                                            | the `<input>` (L645)                          | `OtpInput` -> **the hidden input**, not the `.otpWrap` div                                                    |
| `partner-error` (x11)                                                                          | `<p role="alert">` (L713-716)                 | `ErrorMessage` (already renders `<p role="alert">`, `shared.tsx:146`) - clean swap                            |
| `partner-resend` (x6)                                                                          | the `<button>` (L657)                         | `GhostButton`                                                                                                 |
| `partner-demo-banner` (x4)                                                                     | `<div role="status">` (L732-734)              | `NoticeMessage` renders a bare `<p>` with **no role** - see the open decision in Handoff                      |
| `staff-submit` (x33)                                                                           | the `<button>` (L745)                         | `PrimaryButton`                                                                                               |
| `partner-resend-cooldown` (x2) + `partner-attempts`, `partner-cooldown`, `partner-lockout`     | `<p className="mb-2 text-sm ...">`            | **no atom owns these** - they are raw `<p>`s with the wizard's `.attempts` class                              |
| `partner-countdown` (x1)                                                                       | the bare `<p>` holding the seconds (L611-614) | the **ring** - this element is going away, so the hook moves with it                                          |
| `partner-code-expires`, `partner-code-hint`, `partner-notice`, `partner-edit-number` (x1 each) | raw `<p>` / `<button>`                        | layout `<p>`s; `partner-edit-number` is a bare `<button className={stylesB.editLink}>`, **not a shared atom** |

**Counting the scope precisely:** 33 (`staff-submit`) + 13 (`partner-otp`) + 11 (`partner-error`) + 6 (`partner-resend`) + 4 (`partner-demo-banner`) + 2 (`partner-resend-cooldown`) + 8 singles = **77 selector references**, of which 50 are `partner-*` and the rest `staff-*`/operator. The two additions must cover the ones a #572 swap would break. **Say in your PR which selector each new hook serves** - that mapping is the deliverable #572 depends on.

## THE RING'S CSS CONTRACT TEST - what it actually asserts

`apps/frontend/src/components/auth/otp/variantB.module.test.ts` (29 lines, 2 tests, **confirmed green**: 2 files / 9 tests with the parity suite). It reads the stylesheet **off disk**, not through the CSS-module import, on purpose - the header comment records why:

```ts
const here = (rel: string) => new URL(rel, import.meta.url); // L6
const css = readFileSync(here("./variantB.module.css"), "utf8"); // L7
```

Two assertions, both against the **raw CSS selector text** of `variantB.module.css`:

- `expect(css).toMatch(/\.ring\s+svg\s*\{/)` then the matched rule must carry `width: 100%` and `height: 100%` (L18-21).
- the `.ring` rule must carry `width: 5rem` and `height: 5rem` (L24-27).

The comment at L9-14 records the regression it exists to pin: before `.ring svg { width: 100%; height: 100% }`, the 72x72 SVG sat top-left inside the 80px box, putting the countdown text ~4px off the wheel's centre.

**The test is the thing to get right.** It does not import the component, so **moving the component does not move the test** - the test only breaks if the **styles** move. Two honest options:

- **(a) Styles stay in `variantB.module.css`.** The ring component moves to `shared.tsx` and keeps importing the wizard's stylesheet. The contract test is untouched and green. Cost: the shared module now depends on a stylesheet named for a patient-only prototype variant.
- **(b) Styles move to `otpShared.module.css`.** Retarget the test: `readFileSync(here("./otpShared.module.css"), "utf8")` and the same two regexes, since `.ring` / `.ring svg` keep their names. This is the cleaner end state and the issue explicitly allows it ("retargeted if the styles moved"). Cost: you must copy the three rules (`.ring` L181-185, `.ring svg` L187-191, `.ringTime` L193-203, `.ringTimeLow` L205-207) **byte-for-byte** - `position: relative` / the `inset: 0` flex centring / `tabular-nums` are load-bearing for the centring the test exists to protect.

**Whichever you pick, paste the exact file + line of the retargeted read in the PR.** Option (b) with an un-retargeted test is a silently dead gate; option (a) with a moved stylesheet is a red test. Neither is acceptable, and only one of them is a deliberate choice.

## Key facts / prior art - do not re-derive these

- **The shared module is `shared.tsx`; the shared stylesheet is `otpShared.module.css`.** Nine atoms, all exported: `BrandHeader`, `LangToggle`, `FieldLabel`, `PhoneInput`, `OtpInput`, `ErrorMessage`, `NoticeMessage`, `PrimaryButton`, `GhostButton`. Header comment L3-6 dates it to PHASE-2 T9 / #60, folded from the Variant B prototype.
- **None of the nine atoms accepts a `data-testid` today.** `shared.tsx` is 200 lines and contains **zero** occurrences of `data-testid`. This is a clean addition, not a retrofit.
- **The layout classes #572 needs are NOT in the shared stylesheet.** `otpShared.module.css` (216 lines) holds only the atom styles: `.otpProto`, `.brandHeader`, `.brand`, `.brandMark`, `.langToggle`, `.langBtn`, `.langActive`, `.label`, `.phoneWrap`, `.phonePrefix`, `.phoneInput`, `.otpWrap`, `.otpHiddenInput`, `.otpBox`, `.otpBoxActive`, `.btnPrimary`, `.btnGhost`, `.error`, `.notice`. **The ring and every layout class live in the wizard's `variantB.module.css`**: `.ring` (181), `.ring svg` (187), `.ringTime` (193), `.ringTimeLow` (205), `.section` (118), `.title` (124), `.sub` (130), `.center` (176), `.resendRow` (209), `.editLink` (215), `.attempts` (226), `.demoBanner` (247), `.field` (141), `.card` (109), `.main` (102), plus the patient-only chrome `.root` / `.topbar` / `.steps` / `.step` / `.stepNum` / `.stepLabel` / `.props` / `.propIcon` / `.successIcon`. **Decide here where the ring's styles live**, because #572 inherits the answer. See the Handoff note.
- **The OTP-state helper is already shared across both trees.** `apps/frontend/src/components/auth/otp/otpState.ts` exports `OTP_TTL_SECONDS = 300` (L36), `RESEND_COOLDOWN_SECONDS = 60` (L37), `MAX_ATTEMPTS = 5` (L38), `LOCKOUT_SECONDS = 900` (L39), and `formatCountdown` (L95-103, `${m}:${s.padStart(2,"0")}`). `partnerLoginState.ts:30-36` already imports four of those across the `../otp/otpState` boundary, and `StaffLoginForm.tsx:41` already imports `formatCountdown`. **The countdown is not a private concept - only the ring's rendering is.**
- **The patient suite asserts on text and roles, never on test-ids.** `PatientAuthWizard.test.tsx` (882 lines) contains **zero** `data-testid` assertions. The verify-step tests read e.g. `await screen.findByText("Wrong code. 4 attempts left.")` (L321-323) and drive the submit through a `verifyButton()` helper. **This is why the ring move cannot break the patient suite** - and equally, why AC-2's "green unchanged in what it asserts" is a weak gate here. Assert the ring renders from **both** wizards in a new test rather than relying on the existing suite to notice.
- **The icons module is `apps/frontend/src/components/auth/icons.tsx`** (17 exports; `IconRefresh` at L155 is what `GhostButton` renders). The ring does not use an icon, so a ring move does not touch this file.
- **There is no dedicated suite for the shared module.** The only suites under `apps/frontend/src/components/auth/**` are `PatientAuthWizard.test.tsx`, `variantB.module.test.ts`, `ProviderRegisterWizard.test.tsx`, `StaffLoginForm.test.tsx`, `providerRegisterState.test.ts`, `staffLoginState.test.ts`, `DoneScreen.test.tsx`. There is **no `shared.test.tsx`**. The issue's done-verify "the shared sign-in module's suite, green" therefore means either the patient wizard suite (its only consumer today) or a new `shared.test.tsx` - **see the open decision in Handoff**.

## Read-list (in order)

1. **Issue #571 itself** - the six AC and its Context pack (~0.7K).
2. **`apps/frontend/src/components/auth/otp/shared.tsx`, whole (200 lines)** - the file gaining both props. `PrimaryButton` 157-178 (note `type="button"` hardcoded at 170, and `disabled={disabled || pending}` at 172 - `pending` is the "fewer than 6 digits" gate #572 must keep), `GhostButton` 180-199 (renders `IconRefresh` inside the button at 196), `OtpInput` 96-141 (the hidden input at 116-128 carries `aria-label="Verification code"`, the wrapper div at 110-115 carries `role="group" aria-label="OTP"` and the click-to-focus handler - **this is the element distinction Fact 2 turns on**), `ErrorMessage` 143-150, `NoticeMessage` 152-155. (~1.9K)
3. **`apps/frontend/src/components/auth/otp/otpShared.module.css`, whole (216 lines)** - the shared stylesheet. Confirm for yourself that it carries **no** `.ring*` and **no** layout classes; the atom blocks that matter for the props (`.btnPrimary` 151-177, `.btnGhost` 179-197, `.error` 199-207, `.notice` 209-216) are the ones whose disabled/hover states must not shift. (~1.6K)
4. **`apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx`, three regions** - L1-40 (the header comment L3-11, the two CSS-module imports at L39-40: `shared` from `./otpShared.module.css`, `stylesB` from `./variantB.module.css`, and the eight-atom import block at L29-38), **L69-103 `CountdownRing`** (the whole body: `r = 26`, `c = 2*PI*r`, `frac` clamped against `OTP_TTL_SECONDS`, `low = seconds <= 60`, the two `<circle>`s, `transform="rotate(-90 36 36)"`, the `aria-hidden="true"` wrapper at 75 and the `.ringTime` span at 98-100), and **L163-222 `OtpStep`** (its only consumer - the ring at 173, and the sibling markup that shows how the atoms are meant to be composed). (~1.3K)
5. **`apps/frontend/src/components/auth/otp/variantB.module.css` L118-257** - the block #572 will adopt and the ring's four rules. `.section` 118, `.title` 124, `.sub` 130, `.field` 141, `.center` 176, **`.ring` 181, `.ring svg` 187, `.ringTime` 193, `.ringTimeLow` 205**, `.resendRow` 209, `.editLink` 215, `.attempts` 226, `.demoBanner` 247. Skip L1-117 (`.root`/`.topbar`/`.steps`/`.step*`/`.main`/`.card`) - patient-only chrome, and `.props`/`.propIcon`/`.successIcon` are past what you need. (~1.0K)
6. **`apps/frontend/src/components/auth/otp/variantB.module.test.ts`, whole (29 lines)** - the CSS-text contract test, both assertions, and the `here()` indirection you must replicate if you retarget it. (~0.4K)
7. **`apps/frontend/src/components/auth/otp/PatientAuthWizard.test.tsx` L307-340 and L405-440** - two verify-step tests, purely to see the assertion style (visible text + a `verifyButton()` role helper, no test-ids). This is the evidence for the "no test-ids" fact; do not read the other 840 lines. (~0.6K)
8. **`apps/frontend/src/components/auth/staff/StaffLoginForm.test.tsx` L157-203** - the `t = STRINGS.en.staffAuth.login` alias, the `PHONE` / `LOGIN_OK` / `SESSION` fixtures, and the four drive helpers `typePartnerPhone` 180-184, `typeCode` 186-190, **`typeCodeAndSubmit` 192-195 (the `fireEvent.click` that will not catch a lost `type="submit"`)**, `startPartnerOtpFlow` 197-203. (~0.7K)
9. **Grep only, no read** - the selector census that sizes the test-hook work:
   ```powershell
   $t="apps\frontend\src\components\auth\staff\StaffLoginForm.test.tsx"
   foreach($id in @('partner-otp','partner-error','partner-resend','partner-demo-banner',
     'staff-submit','partner-resend-cooldown','partner-countdown','partner-code-expires',
     'partner-code-hint','partner-edit-number','partner-cooldown','partner-lockout',
     'partner-attempts','partner-notice')){
     $c=(Select-String -Path $t -Pattern $id -AllMatches |
       ForEach-Object { $_.Matches.Count } | Measure-Object -Sum).Sum; "$id = $c" }
   Select-String -Path $t -Pattern 'partner-demo-banner|partner-attempts|partner-countdown|partner-code-hint|partner-edit-number' -Context 1,2
   ```
   Confirms the counts in Fact 2 and that every one of those assertions is `toHaveTextContent`, never a role query. (~0.1K)

**Total ≈ 8.3K tokens. PASS** (budget 10K).

**Re-grep by name if this no longer resolves:** `CountdownRing|stylesB.ring|formatCountdown|OTP_TTL_SECONDS` in `PatientAuthWizard.tsx`; `data-testid` in `shared.tsx`; `\.ring` in `variantB.module.css` and `variantB.module.test.ts`. **#562 rewrites the staff suite's mock block - it does not move the helper names or the test-ids, so the census in item 9 should hold; re-run it rather than trusting it.**

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`.** This ticket touches no module, no event, no API, no schema, no session transport, and no role vocabulary. `CONTEXT.md`'s ADR-0007 hard gate does not fire (no cookie, no CORS, no middleware, no `credentials`, no deploy env var). Nothing in those documents constrains a prop addition and a file move.
- **The partner code step itself** - `StaffLoginForm.tsx` L576-757. That is #572. You need the **selector names** (item 9) and the **`type="submit"` fact**, both of which this brief already gives you; you do not need the step's markup, and reading it is how a prefactor accidentally grows into the redesign it is supposed to enable.
- **`StaffLoginForm.test.tsx` beyond item 8.** 1218 lines. #562 rewrites its mock block anyway. You need four helper functions and a census, not 52 tests.
- **`ProviderRegisterWizard.tsx` and its suite.** It carries the second `tracking-[0.5em]` at `:772`; that is #572's explicitly excluded sibling, and this ticket touches nothing in it.
- **`otpState.ts` beyond the five exported symbols in the Key facts.** The flow hook's 300 lines of request handling are not this ticket's business - the countdown constants are already shared and already correct.
- **`DoneScreen.tsx`, `doneScreen.module.css`, `icons.tsx` beyond the `IconRefresh` name.** `doneScreen.module.css` carries an **uncommitted** edit tracked by #561 - do not read it, do not edit it, do not let it into your diff.
- **`app/staff/login/page.tsx`, the page's own heading, the consent surfaces, the token gate.** #572 and #573 respectively.
- **The bilingual dictionary beyond a `grep` for the atom names.** This ticket adds **no user-facing string**; if your `CountdownRing` export tempts you to add copy, you have left the ticket.

## Baseline verify (must pass before the first edit)

```bash
npx vitest run src/components/auth/otp/variantB.module.test.ts src/lib/i18n/dictionaries.test.ts --root apps/frontend
# confirmed green 2026-09-27: 2 files, 9 tests, 4.7s
npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx --root apps/frontend
# expect 33 tests, 2 failed
npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend
# expect 52 tests, 10 failed
```

- **Confirmed red 2026-09-27: `StaffLoginForm.test.tsx` 10 failed (of 52) = #562; `PatientAuthWizard.test.tsx` 2 failed (of 33) = #563.** The full-suite measured baseline is in `docs/agents/briefs/564-design-token-gate-class-attributes.md` (13 failed / 1519 passed across 3 files, the third being a third-file 5s timeout that is a load flake owned by nobody - its identity moves between runs, so name it by file and test rather than expecting one).
- **Gate: #562 and #563 must be closed before the first edit.** "Full frontend unit suite green" is a done-verify here, and you cannot attribute a red suite to your own change on a red baseline. **The two fast loops above stay green and red respectively either way** - the `variantB` contract test and the parity suite do not depend on the blockers, so the ring work can be written and iterated on immediately. Do not confuse "the ring test is green" with "the blockers are done".
- **Confirm #562 landed before you design the hook.** It rewrites the staff suite's mock block (`StaffLoginForm.test.tsx:100-155`). The selector census in item 9 is the thing that must still hold afterwards; re-run it.
- `npm run test:unit:frontend` - green after the blockers; if a third file is still timing out at 5s, record it as the pre-existing load flake and move on.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief (all 17 pre-commit hooks including the no-em-dash gate; mypy strict 251 files; `tsc --noEmit` clean).
- `git status --porcelain` - the uncommitted `apps/frontend/src/components/auth/doneScreen.module.css` is pre-existing (#561). Not yours; do not commit it.
- **Prove the pre-`type` regression exists before you fix it.** The strongest evidence for prop addition 2 is a throwaway check: swap the partner submit for a `type="button"` `PrimaryButton` in a scratch branch, confirm Enter no longer submits. If you would rather not burn the time, say explicitly in the PR that no test covers Enter and the passthrough is a **behaviour-preservation** change, not a bug fix. Do not let it read as a speculative prop.

## Done-verify (acceptance criteria -> commands)

- AC-1 (ring exported from the shared module, both wizards can render it) and AC-2 (patient rendering unchanged):
  ```bash
  npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx --root apps/frontend
  # 33 tests green; and the file's own assertions are unchanged - prove it:
  git diff --stat -- apps/frontend/src/components/auth/otp/PatientAuthWizard.test.tsx
  # expect: EMPTY. A diff here means you edited assertions to make a move pass.
  ```
  Plus a new test that renders the ring from the shared module and from the wizard and asserts both produce the countdown text, so the move is covered by something rather than merely not breaking something.
- AC-3 (the CSS contract test):
  ```bash
  npx vitest run src/components/auth/otp/variantB.module.test.ts --root apps/frontend
  # 2 tests green
  git diff -- apps/frontend/src/components/auth/otp/variantB.module.test.ts apps/frontend/src/components/auth/otp/variantB.module.css apps/frontend/src/components/auth/otp/otpShared.module.css
  ```
  Read that diff yourself. If the styles moved, the test's `readFileSync` target moved with them and the `.ring` / `.ring svg` selector names and the `5rem` / `100%` values are **unchanged**. If the styles did not move, the test file is untouched.
- AC-4 (the hooks resolve the staff selectors without a mass rewrite):
  ```bash
  # every staff-suite selector that must still resolve, one assertion each
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx --root apps/frontend -t "partner code step"
  ```
  The proof is a **negative**: `git diff --stat -- apps/frontend/src/components/auth/staff/StaffLoginForm.test.tsx` shows **no rewrites of `partner-otp` / `partner-error` / `partner-resend` / `partner-demo-banner` / `staff-submit` assertions**. #562's mock-block rewrite is expected in the diff; your changes are not.
- AC-5 (button-type passthrough) - a new test that asserts the hook, not just the prop:
  ```bash
  # render PrimaryButton with type="submit" inside a <form onSubmit> and assert
  # fireEvent.submit(form) reaches the handler, AND that the rendered element's
  # `type` attribute is "submit". Then assert the default is still "button" for
  # every existing call site, so no other atom silently became a submit button.
  ```
  Pair it with the note that the partner step does not consume the passthrough until #572 - this ticket adds the capability, #572 uses it.
- AC-6 (no user-visible change on the patient surface):
  ```bash
  git diff -- apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx
  # expect: the CountdownRing definition gone, the call site at :173 unchanged in
  # what it renders, the import block updated. No class, no size, no copy, no aria.
  ```
- The full harness:
  ```bash
  npm run test:unit:frontend
  npm run lint
  npm run typecheck
  ```

### Acceptance criteria as a checklist

- [ ] `CountdownRing` is **exported from the shared module** and is no longer defined in `PatientAuthWizard.tsx`. Both wizards can import and render it; the patient wizard's `OtpStep` still renders exactly one ring, unchanged.
- [ ] The patient wizard's rendered output is unchanged and **`PatientAuthWizard.test.tsx` has an empty diff** - not a "still green" diff, an **empty** one. Its suite has no test-ids, so it cannot detect a ring regression; the new ring test is the actual coverage.
- [ ] The CSS contract test **still passes**, and its `readFileSync` target is the file the ring's styles actually live in - retargeted if and only if the styles moved. No dead gate, no un-retargeted test, no third file.
- [ ] The ring's CSS rules are carried **byte-for-byte** (`.ring` `position: relative` + `5rem` square, `.ring svg` `width/height: 100%`, `.ringTime` `inset: 0` flex-centred + `tabular-nums`, `.ringTimeLow` `--danger`). The centring regression the test pins cannot come back.
- [ ] **A test-hook prop exists on the shared code input, the resend ghost, the link-style edit control, the shared messages, the primary action, and the ring**, and each lands on the **element the existing staff selector already resolves to** (Fact 2's table). `partner-otp` must land on the hidden `<input>`, not the `.otpWrap` div.
- [ ] **`PrimaryButton` accepts a button type** and still defaults to `type="button"`, so no other call site becomes a form submit. Assert both halves.
- [ ] The mapping from **hook to staff selector is written down in the PR.** It is the deliverable #572 consumes.
- [ ] **No user-visible change on the patient sign-in surface.** This is a move and two prop additions: no restyle, no resize, no copy, no new aria, no new string, no token added to `tokens.css` or the tailwind colour tree.
- [ ] No change to `otpState.ts`'s exported constants, no change to `icons.tsx`, no change to `DoneScreen.tsx` or `doneScreen.module.css`, and `doneScreen.module.css` stays out of the diff.
- [ ] No new user-facing string, so the bilingual parity suite is untouched and stays green.

## Handoff notes

- **This is the cheapest ticket in the chain and the easiest to over-build.** Everything hard in #572 and #573 is downstream of the two props. If you find yourself restyling the ring, adding an aria treatment, or editing a staff assertion, you have left the ticket.
- **The `type="submit"` fact is the whole reason this ticket exists for prop 2, and it is invisible to the test suite.** No test presses Enter. Say so in the PR, or prove the regression, but do not ship a passthrough with no stated justification.
- **The CSS contract test only breaks if the STYLES move, not the component.** Read item 6's header comment before you touch anything; the `new URL(rel, import.meta.url)` indirection exists to dodge Vite's static rewrite of literal CSS asset references, and a naive `import css from "./x.module.css"` replacement silently turns the gate into a no-op.
- **Decide where the ring's styles live, and record the decision.** The shared module currently has no layout classes at all, and `variantB.module.css` is named for a prototype variant and also carries patient-only chrome (`.steps`, `.props`, `.propIcon`) that #572 must keep **off** the staff surface. Leaving the shared ring pointed at the wizard's stylesheet works and keeps the test untouched; moving the rules is cleaner and is what the issue invites. Either is defensible - an undecided mix is not.
- **`partner-edit-number` has no atom to hook.** It is a bare `<button className={stylesB.editLink}>` at `StaffLoginForm.tsx:661-669`, and `shared.tsx` exports no link-style control. #572's AC names the "link-style edit control" as taking a hook, so either #571 adds a small `EditLinkButton` atom or #572 renders a raw `<button>` with the hook. **Decide here and say which** - #572 inherits the answer, and a hook that does not exist is a blocker discovered late.
- **Four staff selectors have no atom at all**: `partner-attempts`, `partner-cooldown`, `partner-lockout`, `partner-resend-cooldown` are raw `<p>`s carrying the wizard's `.attempts` class, and `partner-countdown` is the bare `<p>` the ring replaces. Each is asserted exactly once or twice, so #572 can keep them as marked elements - but they need _something_ to hang a hook on. Account for them in the mapping or say plainly that they stay hand-marked.
- **The demo banner loses its `role="status"` if it becomes `NoticeMessage`.** The current element is `<div role="status">` (L732-734) and `NoticeMessage` renders a bare `<p>` with no role (`shared.tsx:152-155`). All four assertions are `toHaveTextContent`, so **no test will catch the loss** - but the code appears asynchronously and `role="status"` is what announces it. Either preserve the role on the swapped element or argue it in the PR. Do not lose it silently.
- **There is no `shared.test.tsx`.** The issue's done-verify "the shared sign-in module's suite, green" has no existing referent. Options: (a) treat the patient wizard suite as the shared module's suite by proxy and say so, (b) write `shared.test.tsx` covering both new props. **(b) is the better answer** - these are the two props #572 depends on and they deserve a direct test - but it is a small scope call you must make deliberately, not by omission.
- **Two blockers, still open at brief time** (#562, #563), and the full suite is red until they land. The `variantB` contract test is green independently, so the ring work proceeds now; the full-suite done-verify waits.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes. The repo's own comments follow this.
- **This brief is the chain's foundation.** When #572 and #573 are implemented, their read-lists point here, not back at `shared.tsx` and `variantB.module.css` from scratch. Keep the names you introduce stable.
