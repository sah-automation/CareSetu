# Brief - 581 The handoff stops presenting a countdown

**Ticket:** #581 · **Parent:** #577 (part of #529) · **Refreshed:** 2026-09-28
**Blocked by:** #579 and #580 (both login flows must be off the countdown before it is deleted)
**Reading surface:** ~6K tokens (budget 10K) - **PASS, comfortable**

## Scope

The verified-login handoff becomes what it was always for: a loading mask, so the user can see that their destination is opening. One coherent screen on both flows, carrying no digits anywhere.

The shared component stops being a timer and becomes presentational. It no longer owns a countdown duration, a remaining-seconds value, a departed flag, a tick, or an automatic redirect, and it no longer receives a readiness flag at all - whether to navigate is a consequence of readiness, owned by whichever login flow is hosting the screen (and settled in #579 and #580, through #578's hook). It keeps the confirmation icon, the heading, the body copy, the optional detail rows, the progress indicator, the status line and the "Go to Dashboard" button.

The status line becomes **one constant message for the whole life of the screen**, so there is no longer any sense of one screen being replaced by another. The second dictionary string whose only job was to interpolate the remaining seconds is deleted from **both** locales, together with the comment that described the two-line behaviour.

The progress indicator becomes **indeterminate**: it keeps its role but drops the numeric current-value, maximum-value and value-text attributes, which is the correct form for an indeterminate bar and takes the digit count out of the accessibility tree as well as off the screen. The visual moves from a width transition to a sliding transform animation, because the code genuinely has no idea how long the destination will take.

## Acceptance criteria (from the ticket)

- [ ] The component's own suite passes with its countdown tests **deleted rather than rewritten** - the component no longer ticks, so they have no subject.
- [ ] The rendered verified state is unchanged: icon, heading, body copy, the always-available button that calls its handler, and the detail rows that fill in and skip absent values.
- [ ] The status line is the single constant message for the whole life of the screen, and still a live region.
- [ ] The indicator is present and exposed as indeterminate: role and name, and **no** numeric current value, maximum value, or value text.
- [ ] No number appears anywhere in the progress output.
- [ ] The handoff heading is the only top-level heading while it is up, on both flows.
- [ ] The indicator's CSS is a sliding transform animation rather than a width transition, and it inherits the global reduced-motion floor. Because jsdom applies no stylesheet, the animation contract is pinned by a small source-level invariant test that reads the CSS module off disk.
- [ ] The digit-bearing key is gone from both locales; the parity gate and the design-token gate pass with the token files untouched.
- [ ] Both flows still navigate exactly once, still resume before routing, and still refuse to navigate before their own preconditions hold.
- [ ] Neither flow passes the removed props, and the removed duration constant is not referenced anywhere in the tree.

## THE EXACT REGION TO CHANGE

`components/auth/DoneScreen.tsx` (162 lines - read it whole) and its stylesheet module (117 lines) and its suite (178 lines). Plus two dictionary blocks and two two-line host call sites.

| #   | file : lines                            | symbol                                                  | what changes                                                                                                                                                                                                                                                           |
| --- | --------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `DoneScreen.tsx` L1-16                  | the header comment                                      | It describes a real five-second tick, a two-line status and a resume-gated start - **all of which this ticket makes false.** Rewrite it to say what the component now is. Do not leave a comment that lies.                                                            |
| 2   | L18                                     | the React import                                        | `useCallback`, `useEffect`, `useState` all become unused once the timer goes. Leave `useRef` only if something still needs it.                                                                                                                                         |
| 3   | L23-27                                  | `DONE_SCREEN_COUNTDOWN_SECONDS`                         | **Delete the export.** It is imported by three suites; those imports go in this ticket.                                                                                                                                                                                |
| 4   | L37-61                                  | `DoneScreenProps`                                       | **Delete two props:** `openingInLabel` (the digit-bearing renderer) and `resumePending` (the readiness flag). Nothing replaces them.                                                                                                                                   |
| 5   | L63-120                                 | the whole state-and-effects block                       | `secondsLeft`, `departed`, `departedRef`, `goRef`, the `goRef` identity-sync effect, `depart`, the tick effect, the auto-redirect effect, `progressLine`, `elapsedPercent` - **all of it goes.** This is the ticket. What remains is a props destructure and a render. |
| 6   | L116-118                                | the status line                                         | Becomes the single constant string - the existing `openingLabel` prop, renamed only if a better name earns it. No ternary, no interpolation.                                                                                                                           |
| 7   | L143-156                                | the progress indicator                                  | Keeps `role="progressbar"` and `aria-label`. **Drops `aria-valuemin`, `aria-valuemax`, `aria-valuenow` and `aria-valuetext`.** The inner fill drops its inline `width` style for the sliding animation.                                                                |
| 8   | L157-159                                | the button                                              | `onClick` becomes the host's handler directly - `depart` no longer exists to mediate. The once-only guarantee is now the hook's, at the host, where readiness lives.                                                                                                   |
| 9   | `doneScreen.module.css` L48-61          | `.progressTrack` / `.progressFill`                      | The fill loses `transition: width 1s linear` and gains a sliding transform keyframe animation. The track keeps its shape and its overflow clipping.                                                                                                                    |
| 10  | `dictionaries.ts` L86-97 and L1895-1897 | the `doneScreen` blocks and the comment above them      | **Delete the digit-bearing key from both locales and the two-line comment.** The parity gate is what makes deleting a key from two places safe - which is why it must be run explicitly, not assumed.                                                                  |
| 11  | the two host call sites                 | the handoff elements in the partner form and the wizard | **Two lines each:** stop passing the two removed props. After #579 and #580 neither host reads them.                                                                                                                                                                   |

## The three things that will bite you

**One: the deleted tests, not rewritten.** The component's suite has eight tests and **three of them are about the countdown** - the ticks-to-zero-and-fires case, the holds-back-until-resume case, and the mid-countdown double-navigate case. Delete them. Do not convert them into hook tests: the hook's contract is already pinned in #578's own suite, and duplicating it here is exactly the duplication #577 refused. **The two no-longer-subject tests that must survive in some form:** the "clears its interval on unmount" one becomes moot (there is no interval) and goes too; the "does not double-navigate" guarantee now lives at the host, already asserted in #579 and #580. **Five tests remain**, and the suite needs new ones for the new contract: the constant status line, the indicator's indeterminate shape, and the absence of any number in the progress output.

**Two: jsdom cannot tell a sliding bar from a plain div.** This is a fact about the test environment, not a limitation to work around, and the repository already has the answer: three existing gates read their file off disk for precisely this reason - the design-token gate, the shared sign-in atoms' one-off-utility gate, and the ring's CSS contract test. **The ring's CSS contract test is your template** (33 lines, `readFileSync` with a `new URL(..., import.meta.url)` indirection, two regex assertions). Write one small test that reads the stylesheet module and asserts the fill slides and does not transition a width. It is the only source-level test this ticket adds, and #577 sanctions it by name.

**Three: reduced motion is already solved and you must not re-solve it.** There are **zero** occurrences of `motion-safe` or `motion-reduce` in this repository. The convention is a single global base-layer media query in `globals.css` that kills every animation, transition and scroll behaviour app-wide, and the design-token gate already pins its presence. A CSS keyframe animation in a component module inherits that floor automatically. **Do not add per-component motion code, and do not touch `globals.css`** - the design-token gate will fail if you do.

## Key facts / prior art - do not re-derive these

- **The handoff brings its own `h1` and the hosts have already solved the heading count.** The partner form reports its heading ownership up to the page, which suppresses the page's sign-in heading, and both flows' suites already assert exactly one top-level heading while the handoff is up. Your criterion is asserting a guarantee that exists - check it, do not build a seam for it.
- **The status line is already a live region** (`role="status"`), which is what makes the step change announceable. It stays; the ternary is what goes.
- **The detail rows already reserve no space.** They render only when the host supplies them and the values drop when falsy, so they fill in naturally and the bar plus its message are up before they arrive. There is no skeleton, no placeholder, and no fixed height to remove. Your criterion is a test criterion.
- **The button, the icon, the heading and body copy, and the fact-row labels and contents are all unchanged.** Their text does not change in this ticket. Do not reword them.
- **The indicator's colours come from the existing accent and hairline tokens.** No design token change, which is why the token files must come out of your diff untouched.
- **The `openingDashboard` string survives as the status line** - it is the constant message. Only the second, digit-bearing key dies. Renaming the surviving one is cosmetic and optional; do not churn the dictionary for it.

## Read-list (in order)

1. **#581 itself** and #578's brief - the rule the hosts now own, so you know what the component no longer has to do (~1.0K).
2. **`components/auth/DoneScreen.tsx` in full (162 lines)** - the whole file is the change (~1.5K).
3. **`components/auth/doneScreen.module.css` in full (117 lines)** - the progress track and fill, plus everything the card is made of, so your CSS edit does not disturb the rest (~1.0K).
4. **`components/auth/DoneScreen.test.tsx` in full (178 lines)** - the render factory and its override shape, the `advance` helper and its fake-timer `afterEach`, and the eight test names you are triaging into delete / keep / add (~1.5K).
5. **`components/auth/otp/otpShared.module.test.ts` in full (33 lines)** - the source-level CSS contract test you are copying (~0.3K).
6. **`lib/i18n/dictionaries.ts` L85-103 and L1894-1903** - the two `doneScreen` blocks and the comment above them (~0.5K). Note: the Hindi block renders as `?` in a non-UTF8 console; read it in an editor, and edit by key, not by matching the rendered glyphs.
7. **`lib/i18n/dictionaries.test.ts`, the parity describe and the `parityProblems` walker** - what the gate actually compares, and why removing a key from one locale only is a red test (~0.4K).
8. **`app/globals.css` L22-34** and **`app/design-tokens.test.ts`'s reduced-motion group** - the floor you inherit and the gate that pins it (~0.4K).
9. **The two host call sites only** - grep for the component's name in the partner form and the wizard and read the surrounding element. Not the flows (~0.3K).

**Total ~6.9K counting this brief's own ticket body. PASS** (budget 10K).

**Re-grep by name if any of these no longer resolves:** `DONE_SCREEN_COUNTDOWN_SECONDS|openingInLabel|resumePending|progressFill|aria-valuenow` in the component, its suite and the two host suites; `doneScreen` and `openingIn` in the dictionary; `prefers-reduced-motion` in the base stylesheet. Then refresh this brief.

## Do NOT read

- **The two host flows and their suites whole** - 868 and 344 lines of source, 1917 and 924 of tests. #579 and #580 already retargeted every assertion that mattered. **Grep by name for the removed constant and the two removed props** - that tells you every site that still references them, and it is the whole of what you need from those files.
- **`lib/profile/useProfilePhotoSource.ts` and its suite.** That is #578's prior art for a hook you are not writing.
- **`app/design-tokens.test.ts` beyond its reduced-motion group.** The class-attribute colour gate and the palette groups are unrelated and large.
- **Every dictionary key outside the two `doneScreen` blocks** (3419 lines). The parity gate compares structure, not content, so you never need to read the strings.
- **The backends, migrations, `docs/adr/0007-*`.** No cookie, CORS, proxy-guard, `credentials` or deploy-env change, so the ADR-0007 hard gate does not apply. No API contract, no schema, no event, no session-transport change - this change moves _when_ navigation happens, never _how_, and the resume-before-route ordering is preserved.
- **The e2e specs.** They do not reference this screen, and #577 explicitly puts e2e coverage out of scope.
- **`docs/archive/`, the PRD, `internal-modules.md`, the roadmap, the UI blueprint, the other standards.** No architecture or requirement question is in scope. ADR-0007 and ADR-0016 are both explicitly not in conflict, and #582 owns confirming that.
- **The shared sign-in atoms, the registration wizard, the doctor and patient shells.** Nothing here.

## Baseline verify (must pass before the first edit)

- **Gate: #579 and #580 must both be closed.** This ticket deletes the countdown the flows were riding until those two landed - on a tree where either flow still navigates by countdown, you are removing its only way out. The native dependency edges encode this; check them rather than assuming.
- **Recorded on 2026-09-28 at `acdb078`, before those two landed:** `npm run test:unit:frontend` is **1 failed / 1645 passed (1646)**, the single failure being the known unowned 5s load flake in `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx`. **Re-run and record your own baseline** - by the time you start, #579 and #580 have moved the counts.
- `npm run typecheck` and `npm run lint` - both clean at that commit; re-confirm.
- The two fast loops, and the two gates this ticket must not break:
  ```bash
  npx vitest run src/components/auth/DoneScreen.test.tsx --root apps/frontend
  npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend
  npx vitest run src/app/design-tokens.test.ts --root apps/frontend
  ```
- `git status --porcelain` - the untracked `docs/agents/briefs/*.md` files are pre-existing repo habit. Do not stage them.

## Done-verify (acceptance criteria -> commands)

```bash
npx vitest run src/components/auth src/lib/i18n src/app/design-tokens.test.ts --root apps/frontend
npm run test:unit:frontend
npm run typecheck
npm run lint
```

Criterion by criterion:

- **AC-1 (countdown tests deleted, not rewritten)** - read your own diff of the suite. Three countdown tests gone, five surviving tests still there, new tests added. **No test in this file may reference the removed constant.**
- **AC-2 (verified state unchanged)** - the icon, heading, body, button-calls-handler and facts-and-skip-absent tests, all still present and green.
- **AC-3 (constant status line, still a live region)** - assert the status line is the constant string and that it is `role="status"`. Render it, advance time, render it again: the text must be **identical** - that is the assertion that actually pins "constant", and it is the one that fails if someone reinstates a ternary.
- **AC-4 (indeterminate indicator)** - assert the indicator has the role and the name, and assert the **absence** of `aria-valuenow`, `aria-valuemin`, `aria-valuemax` and `aria-valuetext`. Assert the absence explicitly; a snapshot will not catch an attribute that was merely forgotten to be removed.
- **AC-5 (no number anywhere in the progress output)** - the strongest form is to assert the rendered progress region contains no digits at all, not just that a known string is absent. A digit appearing in a future copy change should fail here.
- **AC-6 (one top-level heading, both flows)** - already asserted by #579 and #580; confirm both are green and that you have not disturbed the hosts' heading ownership.
- **AC-7 (sliding, reduced-motion-safe)** - the new source-level test. Assert the fill animates a transform and does **not** transition a width. Then prove the design-token gate is still green, which is what pins the reduced-motion floor.
- **AC-8 (the key is gone from both locales, both gates pass)** -
  ```bash
  # expect: no match in either locale
  # and the four surviving keys present in both, structurally identical
  git diff -- apps/frontend/src/app/globals.css apps/frontend/tailwind.config.ts
  # expect: empty. The token files are out of scope.
  ```
- **AC-9 (both flows still correct)** - the partner and wizard suites green, unchanged in count except for #579 and #580's own retargeting.
- **AC-10 (nothing references the removed symbols)** -
  ```bash
  # expect: no match anywhere in apps/frontend
  ```
  for the removed constant, the digit-bearing key, and the two removed props. This is a ticket acceptance criterion and #582 re-runs it, but a green tree here is the proof.

## Handoff notes

- **This ticket is a deletion, and the deletions are the deliverable.** The hardest part of the change to #577 is already done by #579 and #580: navigation is a consequence of readiness. What is left is removing the machinery that no longer has a job. If you find yourself adding a guard, a retry, or a readiness check to the component, you are re-introducing the seam #577 exists to remove - the component must not know whether it is ready.
- **The button's once-only guarantee moved, it did not disappear.** It is the hook's, at the host. If you delete the component's `departedRef` and nothing at the host covers a double press, you have dropped a guarantee - #579 and #580 assert it, so the suite will tell you.
- **Do not add a second copy of the hook's contract to this suite.** #578's suite pins the timing; #579 and #580 pin the wiring. This suite pins what is on screen. That division is deliberate and #577 argued for it.
- **The source-level CSS test is the one unusual thing here, and it is sanctioned.** jsdom applies no stylesheet, so a sliding animation and a plain div are indistinguishable in the rendered tree. Three existing gates in this repository read their file off disk for the same reason. Copy the ring's contract test rather than inventing a new mechanism.
- **Read the dictionary by key, in an editor.** The Hindi block renders as `?` in a non-UTF8 console, and a search-and-replace on glyphs you cannot read is how a locale gets corrupted. The parity gate will catch a structural break; it will not catch a swapped meaning.
- **Leave `globals.css` and `tailwind.config.ts` completely alone.** The design-token gate pins the reduced-motion floor and the token files are explicitly out of scope. The animation you add inherits the floor for free.
- **No em-dashes anywhere** in code, comments, or the commit message - the `no-em-dash gate` pre-commit hook enforces it and the codebase follows the rule in its own prose. Use simple dashes.
- **Leave #566 and #537 exactly as they are.** #577 supersedes two of #566's unchecked acceptance criteria _by reference, not by amendment_, and removes the duration #537 specified. Do not close or edit either issue; #582 owns the closeout.
- **This brief is the contract.** Read it, not the world. Do not read the two host flows, the 3419-line dictionary, or the design-token gate whole.
