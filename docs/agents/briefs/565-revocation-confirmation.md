# Brief - 565 Restore the legible revocation confirmation at both consent call sites

**Ticket:** #565 · **Parent:** #560 (front five defects, part 4 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #564 (the design-token gate - it renames the orphan token; the gate must be green before this lands)
**Reading surface:** ~8.4K tokens (budget 10K) - **PASS, within budget**

## Scope

A patient revokes a standing grant and the confirmation is legible, matches every other success message in the product, and disappears on its own even if they navigate away mid-countdown. Both revocation call sites get the same treatment and the same dismissal mechanism.

**The misattribution matters, and the ticket's framing of it is the reason the fix is a treatment change rather than a token rename.** The **background was never wrong.** `bg-txt` resolves to `--txt` = `#0f172a` and is a real token. The **text** is what rotted: `on-txt` exists in neither the tailwind colour tree nor `tokens.css` (only `on-accent` does), so Tailwind emits no `text-on-txt` utility at all, and the text renders at the browser default against near-black. That reads as a wrong background, which is why the original report pointed away from the real cause.

**#564 is correcting the token name. #565 replaces the whole treatment.** Do not "fix" this by swapping `text-on-txt` for `text-on-accent` on a `bg-txt` surface - that restores legibility on a dark toast and still leaves a dark floating toast in a product whose success messages are soft-green surfaces. The target is the approved positive-message treatment below, which is a **light** surface. The dark surface and the missing token go away together, in one class-list replacement.

**The two call sites carry a byte-identical class list today and were duplicated on the stated intent that they read the same.** The panel even says so: `/** Mirrors the consent-log screen so the same success reads the same way. */` above its duration constant. The two dismissal mechanisms did **not** stay the same, and that divergence is the mechanism by which one class name rotted in two places at once. Aligning them is in scope for that reason, not as tidying.

AC:

- [ ] Both call sites carry the approved positive-message treatment, byte-identical (see the exact target below).
- [ ] The confirmation is exposed as a status so a screen reader announces the outcome.
- [ ] Both call sites dismiss it the same way, with the timer cleared on unmount, and the duration is one named value, not a duplicated literal.
- [ ] The class-name assertion that pins the treatment is kept deliberately and labelled load-bearing.
- [ ] The revocation-toast token is no longer an orphan, so #564's repository-wide gate passes.
- [ ] The class list is asserted byte-identical to the approved treatment, not merely asserted to contain the right tokens.
- [ ] No new user-facing string is introduced; the existing revocation copy is unchanged in both locales.

## THE CORRECTED-CLASS TARGET - copy this string exactly

Both sites replace their entire class list with:

```
rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text
```

**Where that string comes from, and the precision trap in it.** The two approved components are the profile save-status notice and the health-background save confirmation:

| reference                           | file : line                                                                         | full class string                                                                                                  |
| ----------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| save-status notice                  | `apps/frontend/src/components/patient/profile/SaveStatusNotice.tsx:40`              | `flex items-start gap-2 rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text` |
| health-background save confirmation | `apps/frontend/src/components/patient/profile/HealthBackgroundSnapshotForm.tsx:373` | `rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text`                        |

**These two are NOT byte-identical to each other** - the notice carries a `flex items-start gap-2 ` prefix (it wraps an icon). The substring they **share** is the string above, and that shared substring is the approved treatment. AC-6's "byte-identical to the approved treatment" is defined against it, not against either full reference string. Do not paste the `flex items-start gap-2` prefix in: neither reference toast wraps an icon, and AC-6 is an exact-match assertion.

Every utility in the target resolves under #564's strict full-path rule, so the corrected sites pass the gate with no allowlist:

- `rounded-md` - the radius scale (`theme.extend.borderRadius` / stock scale), not a colour.
- `border-success-soft`, `bg-success-soft` - `borderColor` / `backgroundColor` resolving `colors.success.soft` = `var(--success-soft)` = `#dcfce7`.
- `text-success-text` - `colors.success.text` = `var(--success-text)` = `#166534`. **A real token** (this is the distinction #564's own brief makes about `warm-text`, which is not).
- `px-3 py-2 text-sm` - spacing and a font size, not colours.

Note there is **no** `success.border` - `success` is `DEFAULT` / `soft` / `text` only. `border-success-soft` is `success.soft` used as a border colour, which is why it resolves. The rejected-appeal page gets this wrong (`border-success-border`, recorded as an out-of-reach orphan in #564) - do not copy that one.

**A consequence you must be deliberate about, and record on the ticket.** The approved treatment is a _static inline notice_; the current toast is a _fixed floating_ toast (`fixed bottom-20 left-1/2 z-50 -translate-x-1/2 ... shadow-lg`). A byte-identical class list means the positioning utilities are **dropped** and the confirmation renders in normal flow as the last child of its container. That is what AC-1 and AC-6 together require - the two cannot both hold with the float kept. Do not silently reintroduce `fixed`, `bottom-20`, `left-1/2`, `z-50`, `-translate-x-1/2` or `shadow-lg` "to keep it a toast"; that fails the byte-identical assertion. If you judge the lost float to be a regression, that is a ticket conversation, not a silent deviation.

## The two call sites (grep-confirmed 2026-09-27)

Both carry the same broken class on a `role="status"` div, and both testids are distinct from each other and from anything else in the tree.

| site                                          | file : line                                                               | symbol                                                                | testid             |
| --------------------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------ |
| patient profile consent panel (Settings zone) | `apps/frontend/src/components/patient/profile/ConsentGrantsPanel.tsx:274` | `{toast && ( <div role="status" data-testid="ps-consent-toast" …> )}` | `ps-consent-toast` |
| record consent log screen                     | `apps/frontend/src/app/(patient)/patient/record/consent-log/page.tsx:359` | `{toast && ( <div role="status" … data-testid="toast"> )}`            | `toast`            |

`role="status"` is **already present on both** - AC-2 is satisfied by keeping it, not by adding it. What is missing is an assertion that pins it (the axe scan does not check that _this_ element is a status region), and the axe scans do not run while a toast is on screen.

## THE DISMISSAL DIVERGENCE - in scope, and the reason why

Your count is **confirmed exactly**: two call sites, two mechanisms, one shared duration.

|                  | site 1 - `ConsentGrantsPanel.tsx`                                                                                                                                | site 2 - `consent-log/page.tsx`                                                                             |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| duration         | named constant `TOAST_MS = 3500` at **L41-42**, with the comment "Mirrors the consent-log screen so the same success reads the same way"                         | **duplicated literal `3500` inline at L168**                                                                |
| timer handle     | `const toastTimer = useRef<ReturnType<typeof setTimeout> \| null>(null)` (**L57**)                                                                               | none                                                                                                        |
| arm              | `flash(message)` (**L84-88**): `setToast`, `clearTimeout` if held (**the re-arm guard**), then `toastTimer.current = setTimeout(() => setToast(null), TOAST_MS)` | `setToast(t.revokeConfirm.done)` then a **raw inline `setTimeout(() => setToast(null), 3500)`** at **L168** |
| clear on unmount | yes - a cleanup-only `useEffect` at **L77-82** that `clearTimeout`s the ref                                                                                      | **no** - no ref, no cleanup effect, no `clearTimeout` anywhere in the file                                  |
| call site        | `flash(t.consentRevokeDone)` at **L103**, inside `confirmRevoke()` (**L90-112**)                                                                                 | `setToast(...)` + the timer, inside `handleRevoke()` (**L158-174**)                                         |

**The mechanism, stated once.** The comment at L41 asserts a shared contract ("mirrors the consent-log screen so the same success reads the same way"). Only the _duration_ was shared, and only as a literal nobody could see. The dismissal _mechanism_ was re-implemented independently, so a later edit to the class list was made in one file with no signal in the other, and a single broken class name now sits in two places with a comment claiming they are one. Aligning the mechanism is what stops the third divergence; copying the string without it leaves the trap armed.

**The shape to converge on** is site 1's: keep the ref, keep the unmount cleanup effect, keep the re-arm guard in the flash helper, and have the duration be a single named value. Where the constant lives is your call - the honest options are (a) a small shared module both sites import, so the "mirrors" claim becomes an import rather than a comment, or (b) one site exporting it and the other importing it. Do **not** satisfy AC-3 by deleting the consent log's raw timer and leaving a second literal - that is the same defect wearing a different hat. The comment at L41-42 must be updated or deleted so it describes what is actually true afterwards; a comment claiming a mirror that no longer exists is worse than no comment.

## Key facts / prior art - do not re-derive these

- **The class-name assertion is load-bearing, and the brief must say why.** The test environment is **DOM-only: no stylesheet is loaded.** A pure-CSS defect - an unresolvable token producing no utility - is therefore **invisible to every rendered-surface, snapshot, contrast, and axe assertion in the suite**; axe checks the accessibility tree, not the cascade. The class-name string is the _only_ observable a unit test has for a treatment decision. Assert it as an **exact string**, not `toHaveClass("bg-success-soft")`-style containment: a containment assertion passes on the current broken string, which is precisely the failure this ticket exists to fix. Label the assertion with a comment saying why it is exact-string and not a visual check, so the next person does not "simplify" it. Prior art for the shape of a deliberate class assertion in this repo: `apps/frontend/src/app/(patient)/patient/page.test.tsx:1115, 1159, 1236` (`expect(pill).toHaveClass("bg-success-soft")`).
- **The patient profile page suite is the accessibility seam, and it already does everything the ticket needs.** `apps/frontend/src/app/(patient)/patient/profile/page.test.tsx` imports `* as axe from "axe-core"` and runs `expect((await axe.run(container)).violations).toEqual([])` at **three** sites: **L476** (completed profile), **L490** (blocked-save explanation), **L591** (all three zones). It also already mocks the consent API it exercises (`vi.mock("@/lib/consent/api", …)` at **L78-81**, with `fetchConsentLog` / `revokeConsent` re-mocked and `mockReset()` in `beforeEach` at **L167-169**) and resets the i18n store (`__resetLangForTests()` at **L158**). Its revoke test is **L750-778** (`"revokes a health_background grant from Settings"`) - it clicks revoke, confirms, and asserts the grant row is gone, but **it never asserts the toast at all**. That is where the surface assertion belongs.
- **The panel's own suite never touches the toast either.** `apps/frontend/src/components/patient/profile/ConsentGrantsPanel.test.tsx` (249 lines) has 8 `it`s and none asserts `ps-consent-toast`; its revoke test is L111-136. The consent log's suite is the only one that reaches the toast today, and only as text: `apps/frontend/src/app/(patient)/patient/record/consent-log/page.test.tsx:408-411` does `await screen.findByTestId("toast")` then `toHaveTextContent("Permission taken back - future sharing stopped.")`. **No timer, no class, no role assertion anywhere in the tree.** A dismissal-alignment test (fake timers, or an unmount-mid-countdown assertion) is new coverage, not an edit to an existing one.
- **The two revocation strings are not the same string, and you are not changing either.** The panel's is `profileZones.consentRevokeDone`; the consent log's is `consentLog.revokeConfirm.done`. Verified values:
  - `dictionaries.ts:973` `consentRevokeDone: "Access revoked."` / `:2363` `"एक्सेस वापस ले लिया गया।"`
  - `dictionaries.ts:1166` `done: "Permission taken back - future sharing stopped."` / `:2800` `"अनुमति वापस ले ली गई - आगे की साझेदारी बंद।"`
    AC-7 forbids new user-facing copy, so the byte-identical-class work must not drag a string rename in with it. If you believe a string is wrong, that is a finding for the ticket, not an edit.
- **Bilingual parity is gated, so an accidental key change fails loudly.** `apps/frontend/src/lib/i18n/dictionaries.test.ts` (127 lines) holds the hand-rolled recursive differ `parityProblems(en, hi, path): string[]` (returns findings as `"<path>: <reason>"` strings rather than throwing) and a `describe("parity detector self-test (#194 red/green proof)")` block with **five** negative self-tests - each feeding a deliberately broken shallow copy through the _same_ checker and asserting the exact finding string (key deleted from hi, key deleted from en, string reshaped to a function, array length divergence, element type divergence). Confirm **five**; the ticket's parity contract is that count. This gate only catches _shape_ divergence, so an in-place English string edit with a matching Hindi edit passes - which is exactly why AC-7 is a review criterion and not an automated one.
- **The dictionary is ~206KB / 3399 lines. Never read it whole.** If you must confirm a key, grep for it and read the two-line window: `profileZones` opens at **L864** (en) and **L2266** (hi); `consentLog` opens at **L1139** (en) and **L2773** (hi).
- **Other live users of the same treatment**, useful as corroboration that this is the house positive-message look: `ProfileCompletionWizard.tsx:119`, `LabBookingConsentDemo.tsx:89`, `app/(doctor)/doctor/profile/page.tsx:452, 1094`. (Two more exist at `app/(doctor)/doctor/review/[intakeId]/page.tsx:571, 682` with a `border-hairline` border rather than the success-family one - near neighbours, not the byte-identical reference; do not copy them.)

## Read-list (in order)

1. **Issue #565 itself** - the seven AC and its Context pack (~0.6K).
2. **`ConsentGrantsPanel.tsx`, five slices, not the file (281 lines):** L41-42 (`TOAST_MS` + the "mirrors" comment), L56-57 (`toast` state + `toastTimer` ref), L77-88 (the unmount-cleanup effect and the `flash` helper, including the re-arm guard), L90-112 (`confirmRevoke`, the `flash` call at L103), L270-278 (the toast markup and its class) (~0.9K).
3. **`app/(patient)/patient/record/consent-log/page.tsx`, three slices, not the file (489 lines):** L112-114 (`toast` state, no ref), L158-174 (`handleRevoke` with the raw `setTimeout(…, 3500)` at L168), L355-364 (the toast markup and its class) (~0.7K).
4. **The two approved components:** `SaveStatusNotice.tsx` whole (45 lines - read it whole, it is the smallest reference and carries the `flex items-start gap-2` prefix you must _not_ copy), and `HealthBackgroundSnapshotForm.tsx` L360-380 only (the success block at L373; do not read the idempotency-key logic above it) (~0.7K).
5. **The patient profile page suite, five slices (848 lines):** L14-30 (imports incl. `axe-core`), L78-81 (the `@/lib/consent/api` factory), L156-180 (`beforeEach`: localStorage clear, `__resetLangForTests()`, the mock resets), L465-492 and L580-593 (the three `axe.run` sites), L720-778 (the Settings-zone consent tests, incl. the revoke test the new assertion extends) (~1.6K).
6. **`ConsentGrantsPanel.test.tsx` L1-140** - the mock block (L34-37), the `consent()` fixture factory (L60-75), the `beforeEach`/`afterEach` (L77-87), and the existing revoke test (L111-136). The remaining 109 lines are three tests you do not touch; grep them if you change a shared helper (~1.0K).
7. **`consent-log/page.test.tsx` L35-64 and L360-412** - the three `vi.mock` factories plus the `vi.mocked` handles, and the revoke test that already asserts the toast's text. This is the file that will carry the consent-log-side class/timer assertions (~0.9K).
8. **The i18n parity gate:** `dictionaries.test.ts` whole (127 lines - `parityProblems` and the five negative self-tests) (~1.1K).
9. **The four dictionary lines**, both locales, two-line windows only: `dictionaries.ts` L968-974, L1158-1167, L2361-2365, L2793-2801 (~0.5K).
10. **Token resolution, three greps, no file reads:** `success` in `apps/frontend/tailwind.config.ts` (L22-25 - the group is `DEFAULT`/`soft`/`text`, no `border`); `success` / `--txt` / `--on-accent` in `apps/frontend/src/app/tokens.css` (L20-22, L36, L38 - confirms `#dcfce7`, `#166534`, and that `--on-txt` does not exist); `border-success-soft|bg-success-soft|text-success-text` across `apps/frontend/src` to re-confirm the reference sites on the current tree (~0.4K).

**Total ≈ 8.4K tokens. PASS** (budget 10K).

**Re-grep by name if this no longer resolves:** `on-txt|bg-txt` in `apps/frontend/src` (must return exactly the two sites above); `border-success-soft bg-success-soft` (must return `SaveStatusNotice.tsx:40` and `HealthBackgroundSnapshotForm.tsx:373`); `setTimeout|toastTimer|TOAST_MS` in both call sites. If #564 already landed, `on-txt` should be gone from both sites - if it is, the class-list replacement below is still required, because #564 corrects the token, not the treatment.

## Do NOT read

- **`dictionaries.ts` whole or in bulk.** 206KB / 3399 lines. Grep the key, read the two-line window, both locales. Reading it is the single largest budget risk in this repo and it is never necessary.
- **`design-tokens.test.ts` and #564's gate internals.** That is the previous ticket's contract. You need one fact from it - that the corrected treatment passes strict full-path resolution with no allowlist - and read-list item 10 gives you that fact without the file. Do not widen the gate, add an allowlist entry, or "help" by fixing the seven out-of-reach orphans.
- **`tokens.css` and `tailwind.config.ts` beyond the greps in item 10.** You are not adding, renaming, or re-valuing a token. The palette is byte-identical after this ticket.
- **The rest of the profile page suite** (L180-450, L600-705, L795-848: the save flow, the photo block, the export/delete leads). Only the Settings-zone consent tests and the three axe sites are in scope.
- **`HealthBackgroundZone.test.tsx`, `ProfileCompletionWizard.test.tsx`, `ProfileNudges.test.tsx`.** Adjacent profile-zone suites, none of which exercise a toast. Do not add an axe run to them.
- **The rest of `ConsentGrantsPanel.tsx` and the rest of `consent-log/page.tsx`** - the grant list, the scope labels, the counterparty chips, the egress table, the receipt expansion. You are changing a class list and a timer.
- **`SaveStatusNotice.tsx`'s callers and `HealthBackgroundSnapshotForm.tsx` beyond L360-380.** You are not changing either reference component. If you edit one, the byte-identical comparison has no anchor left.
- **The other 30-odd `text-success-text` sites** enumerated in the tree-wide grep. They corroborate the house look; they are not in scope.
- **Backend code, `apps/backend/**`, migrations, e2e specs, `docs/adr/\*`.\*\* No API, schema, event, or session change. Nothing here touches a cookie, CORS, a proxy guard, or a deploy env var, so ADR-0007's hard gate does not apply.
- **`docs/archive/`**, the PRD, `internal-modules.md`, the roadmap, `docs/design/ui-blueprint.md`, `docs/standards/*`. No architecture, requirement, or design-decision question is in scope. The treatment is already approved and already shipped twice; you are copying a string, not choosing a design.
- **The patient wizard (`PatientAuthWizard.tsx`) and the staff login form.** Other tickets' files; `ProviderRegisterWizard.tsx` is rewritten by a later ticket and will churn.

## Baseline verify (must pass before the first edit)

- **Gate: #564 must be closed first.** AC-5 is "the repository-wide gate from the previous ticket passes", and #564's own done-verify is a green full frontend suite. If #564 has not landed, stop - you cannot attribute a red token gate to yourself, and the corrected class you are about to write is precisely what that gate will judge.
- `npx vitest run "src/app/(patient)/patient/profile/page.test.tsx" --root apps/frontend` - **the fast loop for the panel-side work.** Confirmed green 2026-09-27.
- `npx vitest run "src/components/patient/profile/ConsentGrantsPanel.test.tsx" --root apps/frontend` - the panel's own suite. Green at brief time.
- `npx vitest run "src/app/(patient)/patient/record/consent-log/page.test.tsx" --root apps/frontend` - the log's own suite. Green at brief time.
- `npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend` - the parity gate. Green at brief time (2 positive + 5 negative).
- `npm run test:unit:frontend` - **expected RED at brief time, and that is not yours.** Per #564's recorded baseline: **13 failed, 1519 passed (1532), 3 files** - `StaffLoginForm.test.tsx` (10, = #562), `PatientAuthWizard.test.tsx` (2, = #563), and one third-file 5s `Test timed out` that is a load flake owned by nobody. **Its identity moves between runs** (`HealthBackgroundZone.test.tsx`, `doctor/cases/[caseId]/page.test.tsx` and `patient/profile/page.test.tsx` have all shown it at this commit) - name whatever is red by file and test, rather than expecting one file. **Record your own full-suite count before and after** so the delta is attributable. "Full suite green" is a done-verify, so a red baseline must be the blockers' red, not yours.
- `npm run lint` - confirmed green 2026-09-27 (all 17 pre-commit hooks, including the no-em-dash gate).
- `npm run typecheck` - confirmed green 2026-09-27 (mypy strict 251 files; `tsc --noEmit` clean).
- `git status --porcelain` - note the pre-existing uncommitted `apps/frontend/src/components/auth/doneScreen.module.css` (tracked by #561). It is not yours; do not commit it, and do not let it appear in your diff.

## Done-verify (acceptance criteria -> commands)

- AC-1, AC-5, AC-6 - the exact string, twice, and the gate agrees:
  ```bash
  npx vitest run src/app/design-tokens.test.ts --root apps/frontend   # green, no allowlist entry added
  ```
  Then confirm by grep that the two class strings are byte-identical to each other and to the target:
  ```bash
  # both sites must print: rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text
  # and must NOT print: on-txt, bg-txt, fixed bottom-20
  ```
- AC-1, AC-2, AC-4, AC-6 - the surface assertions, in the two suites that already own each call site:
  ```bash
  npx vitest run "src/components/patient/profile/ConsentGrantsPanel.test.tsx" --root apps/frontend
  npx vitest run "src/app/(patient)/patient/record/consent-log/page.test.tsx" --root apps/frontend
  npx vitest run "src/app/(patient)/patient/profile/page.test.tsx" --root apps/frontend
  ```
  Each must carry an **exact-string** class assertion on its own testid, a `role="status"` assertion, and a comment naming the DOM-only / no-stylesheet reason for the exactness.
- AC-3 - one duration value, one dismissal mechanism:
  ```bash
  # expect: no numeric 3500 literal in either call site
  # expect: exactly one named duration constant, imported or exported across the pair
  # expect: a cleanup effect clearing the timer in BOTH files; a ref in BOTH files
  ```
- AC-3 - the timer actually clears on unmount, proven rather than asserted: a fake-timer test (or an unmount-mid-countdown test with `vi.getTimerCount()`) that shows no timer survives the unmount. A `clearTimeout` nobody can observe is the defect being fixed; do not add it unproven.
- AC-4 - the label: grep the finished tests and confirm each exact-string class assertion carries its load-bearing comment. A bare `toHaveClass(...)` with no note is a done-verify failure.
- AC-7 - no new strings: `git diff --stat -- apps/frontend/src/lib/i18n/` must be **empty**. If it is not, you changed copy.
- The full suite and the harness:
  ```bash
  npm run test:unit:frontend
  npm run lint
  npm run typecheck
  ```
  `npm run test:unit:frontend` should be green with #562 and #563 closed. Any failure in `StaffLoginForm.test.tsx` or `PatientAuthWizard.test.tsx` is a blocker that has not landed; a third-file 5s timeout is the known load flake - report it by file and test if it survives, do not absorb it.
- The axe scans still pass with a toast on screen. The three existing `axe.run` sites never render a toast, so **add the toast to one of them** (or add a fourth scan) rather than trusting the green ones - otherwise the accessibility half of AC-2 is unverified in exactly the state that matters.

### Acceptance criteria as a checklist

- [ ] Both call sites' class lists are the exact string `rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text`, byte-identical to each other, with no positioning utilities left over.
- [ ] The string is taken from the substring the two approved components **share**, not from either full reference string - the `flex items-start gap-2` prefix is not copied.
- [ ] Both divs keep `role="status"`, and it is asserted. (It is already there; the assertion is new.)
- [ ] The dropped float is recorded on the ticket as a deliberate consequence of the byte-identical requirement, not silently accepted.
- [ ] `design-tokens.test.ts` is green with **no** allowlist, skip, or suppression comment; the corrected sites pass strict full-path resolution; `on-txt` appears nowhere in `apps/frontend/src`.
- [ ] Both call sites clear their timer on unmount, hold it in a ref, and re-arm safely on a second flash. The raw inline `setTimeout` in the consent log is gone.
- [ ] The duration is **one** named value, not a literal in two files. The "mirrors the consent-log screen" comment is updated or deleted so it states what is true.
- [ ] Each new class assertion is an **exact string** comparison, carries a comment naming the DOM-only / no-stylesheet reason, and passes only on the corrected treatment - verified by running the test against the **old** class list and watching it fail.
- [ ] The timer teardown is demonstrated (fake timers or `vi.getTimerCount()`), not merely written.
- [ ] An axe scan runs with the confirmation actually on screen, and `violations` is `[]`.
- [ ] `git diff --stat -- apps/frontend/src/lib/i18n/` is empty. No new user-facing string; the two existing revocation copies are untouched in both locales.
- [ ] `tokens.css` and `tailwind.config.ts` are byte-identical. No token added, renamed, or re-valued.

## Handoff notes

- **The class list is the deliverable. Everything else is plumbing around it.** Copy the string; do not redesign it, do not add an icon to justify the `flex items-start gap-2` prefix, do not pick a different green.
- **Prove the assertion can fail.** A containment assertion (`toHaveClass("bg-success-soft")`) passes on today's broken string, so a green suite would prove nothing. Run the new exact-string test against the **old** class list, capture the red, then apply the fix. Same discipline #564's brief sets for its detector.
- **The real defect is the mechanism, not the string.** Two call sites, one duplicated literal, a comment asserting a mirror that was never implemented, and one mechanism with unmount cleanup next to one without. Fixing the class without aligning the timers leaves the divergence that produced it. AC-3 is load-bearing for the same reason AC-4 is.
- **The float going away is the most likely thing to be "fixed" by someone who has not read this brief.** It is a required consequence. If you think it is wrong, say so on the ticket with the trade-off stated; do not resolve the tension by loosening the assertion.
- **Two distinct strings, one shared treatment.** "Access revoked." and "Permission taken back - future sharing stopped." are different copy in different namespaces. AC-7 is about not adding a third; it is not about making the two equal.
- **Add the axe scan to a state that has the toast.** The three existing scans all render with `toast === null`, so they cannot see the confirmation. The value of the accessibility half of this ticket is entirely in a scan that runs while it is visible.
- **Two blockers' worth of red is expected in the baseline.** #562 (10 failures) and #563 (2 failures) are not yours; #564 must be closed before you start or the token gate cannot judge your output. Record counts, do not chase them.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes. The repo's own comments follow this.
- **This brief is the contract.** Read it, not the world. Grep for line numbers; do not read the components, and never open `dictionaries.ts` beyond a two-line window.
