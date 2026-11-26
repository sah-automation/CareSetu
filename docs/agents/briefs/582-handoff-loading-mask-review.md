# Brief - 582 Combined review pass over the handoff-as-loading-mask set

**Ticket:** #582 · **Parent:** #577 (part of #529) · **Refreshed:** 2026-09-28
**Blocked by:** #578, #579, #580, #581
**Reading surface:** ~4K tokens of new material (budget 10K) - **PASS.** This ticket is four `/to-brief` outputs and four diffs, not new code.

## Scope

A combined review of the four tickets that turn the verified-login handoff into a loading mask, with every finding fixed before the set is considered landed.

Run the repository's `/code-review` skill across the whole set on two axes:

- **Standards** - does the landed code follow this repo's documented coding standards? Module layout, test conventions, traceable test names carrying their ticket reference in the file header comment, no one-off utilities left at the sites the set replaced, no em-dashes anywhere.
- **Spec** - does the landed code match what #577 asked for, user story by user story and decision by decision?

Then fix whatever it finds and re-run the gates.

## The three closure checks no single ticket could own

**1. Nothing orphaned the set.** The handoff lost a duration constant, a dictionary key and two component props across four tickets. Grep the whole tree for each of the removed symbols and confirm no reference survives outside this set's own history, and that no dictionary key survived in one locale only.

**2. The two flows still agree.** This is the entire point of the shared hook: the partner login and the patient login cannot drift apart on what "ready" means or on how long the minimum dwell is. The readiness rule and the dwell must exist in exactly one place. If a host grew its own copy of either, the refactor has failed even though every test is green - which is why this is a closure check and not a ticket criterion.

**3. Docs need no change.** The change moves _when_ navigation happens, not _how_: the resume-before-route ordering and the absence of a hard reload are both preserved, so ADR-0007 is not in conflict; the post-login routing that sends `Under Verification` and `Rejected` partners straight to their status surfaces is untouched, so ADR-0016 is not in conflict. No glossary term is added or changed, and no PRD, architecture, roadmap or blueprint section moves. **Confirm that, do not assume it** - if any part of it is wrong, that is the finding this ticket exists to catch, and it means a ticket was mis-scoped rather than that a doc needs editing.

## Acceptance criteria (from the ticket)

- [ ] `/code-review` has been run across the full set on both axes, and its findings are recorded on this ticket.
- [ ] Every Standards finding fixed, or explicitly dismissed with a reason.
- [ ] Every Spec finding fixed, or explicitly dismissed with a reason; every user story in #577 mapped to the test that now pins it, or to a note on why it needs none.
- [ ] No reference survives anywhere in the tree to the removed duration constant, the removed dictionary key, or the removed component props.
- [ ] Both locale blocks are structurally identical; the parity gate and the design-token gate pass with the token files untouched.
- [ ] The readiness rule and the minimum dwell exist in exactly one place; neither host defines its own.
- [ ] The protected regression case for the frozen-screen defect is still present, still asserts exactly one navigation when a slow destination finally lands, and is **named so it reads as load-bearing** rather than incidental.
- [ ] The token files, the ADR-0007 and ADR-0016 invariants, the post-login routing matrix, the session-resume seam and the e2e suites are all confirmed unchanged, and no documentation needed a delta.
- [ ] The full harness green: frontend unit suite, lint, typecheck.
- [ ] No em-dashes anywhere in the diff.

## The regression test is the fragile thing, and it is the one to check first

#577's own closing note flags it: this is the only test in the spec that is **purely protective**, and the one most likely to be deleted by accident if the timing contract is ever refactored. It fails the way a network problem fails - a frozen screen, a button that does nothing - so if it ever goes missing, the next person to hit that bug files it as an outage.

Check it by name and by content, not by count: does a test exist whose failure mode is _a destination read slower than the old five-second duration still producing exactly one navigation when it finally lands, with the button live throughout_? If the only remaining test of that shape is incidentally covered, say so and add it back.

## Read-list (in order)

1. **The four `/to-brief` outputs** - `docs/agents/briefs/578-*.md`, `579-*.md`, `580-*.md`, `581-*.md`. **These are the contract each ticket worked from, and the fastest way to spot drift is to compare what each brief promised against what each diff actually delivered.** Read them before the diffs, not after (~5K, but it is four bounded documents and you will not be writing code against them).
2. **The four diffs** - the hook module and its suite, the two hosts and their suites, the shared component, its stylesheet and its suite, the two dictionary blocks, the new source-level CSS contract test. Review the diff, not the files (~6K).
3. **#577 in full** - the solution, the implementation decisions, the testing decisions, the out-of-scope list, and the 37 user stories. The stories are the traceability checklist for criterion 2, and the out-of-scope list is how you catch a ticket that quietly grew (~4K).
4. **`docs/standards/coding-standards.md`** - the standards axis, tests section and traceability section (~1.5K).
5. **Just enough of ADR-0007 and ADR-0016 to check the claim in closure check 3** - the session-transport invariants and the partner login-method decision. Both are ~1K each and you are checking non-conflict, not re-deriving them.

## Do NOT read

- **`docs/archive/`.** Superseded by the PRD.
- **The backends, migrations, the e2e specs, and the whole frontend.** You are reviewing four diffs; reading the codebase to re-derive what the diffs already show is how a review session burns its budget.
- **The i18n dictionary beyond the two `doneScreen` blocks.** The parity gate compares structure, not content.
- **The PRD, `internal-modules.md`, the roadmap, the UI blueprint, and the standards other than coding-standards.** Read far enough to _confirm_ closure check 3, and no further. If you find yourself reading the PRD to adjudicate a behaviour question, the answer is in #577 or the ticket that owned the behaviour.
- **Issues #566, #563, #537 and #529's other sub-issues.** #566 and #537 are referenced _by_ this set; they are not part of it. #529's other workstreams are unrelated.

## Baseline verify (must pass before the first edit)

- All four blockers closed, and the native dependency edges on this ticket confirm it.
- **Recorded on 2026-09-28 at `acdb078`, before this set landed:** `npm run test:unit:frontend` is **1 failed / 1645 passed (1646)**, the single failure being the known unowned 5s load flake in `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx`, documented in #566's brief. **That is the pre-set baseline, not yours.** By the time you start, #578-#581 have moved the counts. Re-run and record the real baseline before your first edit, and name any pre-existing failure as pre-existing rather than fixing it.
- ```bash
  npm run test:unit:frontend
  npm run typecheck
  npm run lint
  ```
- `git status --porcelain` - the untracked `docs/agents/briefs/*.md` files are pre-existing repo habit. Do not stage them.

## Done-verify (acceptance criteria -> commands)

```bash
npm run test:unit:frontend
npm run typecheck
npm run lint
npx vitest run src/lib/i18n/dictionaries.test.ts src/app/design-tokens.test.ts --root apps/frontend
```

- **AC-1, AC-2, AC-3** - the `/code-review` output is on this ticket, and every finding is closed or dismissed with a reason. A dismissed finding needs the reason written down, not just a closed checkbox.
- **AC-4** - the orphan sweep, run at the end:
  ```bash
  # expect: no match anywhere in apps/frontend, and no match outside this
  # set's own history and briefs
  ```
  for the removed duration constant, the digit-bearing dictionary key, and the two removed component props.
- **AC-5** - the two gates pass, and the token files are confirmed untouched:
  ```bash
  git diff -- apps/frontend/src/app/globals.css apps/frontend/tailwind.config.ts
  # expect: empty
  ```
- **AC-6** - the single-definition check for the readiness rule and the minimum dwell. One definition each, in the shared hook. Grep it and say where you found them.
- **AC-7** - the regression test, found by name and read. Report the test's exact name in your closing comment so the next refactorer can recognise it.
- **AC-8** - the invariants, confirmed by reading the diffs and not by trusting the briefs: no hard reload added, resume-before-route preserved, the post-login routing matrix and the operator branches unchanged, the session-resume seam unchanged, no e2e spec touched, and no doc delta. **If any of these turns out to be violated, that is a Spec finding** - fix the code, do not amend the ticket to match it.
- **AC-9, AC-10** - the full harness, run after every fix, and the no-em-dash check (the `no-em-dash gate` pre-commit hook already enforces it on commit; confirm the hook passed on the fix commits).

## Handoff notes

- **You are reviewing, not rebuilding.** If a fix turns out to be larger than a few lines, that is a finding to report on #577 rather than a refactor to start here. The one exception is a fix that restores a guarantee a ticket dropped - that one is worth doing.
- **The two axes are independent and both are required.** A change can be idiomatic and wrong, or correct and unidiomatic. #577's own argument is that the countdowns were idiomatic and wrong - the countdown was well-built, tested, and a hold nobody wanted. Do not let the tests being green stand in for the spec being met.
- **Traceability is a criterion here, not a nicety.** #577 names 37 user stories. Map each to the test that now pins it, or write down why it needs none. "Covered by the parity gate" and "this is the out-of-scope list" are legitimate answers; silence is not.
- **Do not close #577, #529, #566, #537 or #563.** #577 supersedes two of #566's unchecked acceptance criteria _by reference, not by amendment_, and removes the duration #537 specified. Both issues stay exactly as written. Closing the parent is a maintainer decision.
- **The known load flake is not a finding.** It is the documented unowned 5s timeout in the doctor case-workspace suite. Note it in your report and move on; fixing it here is scope creep with no owner.
- **No em-dashes anywhere** in code, comments, commit messages, or your report. The `no-em-dash gate` pre-commit hook enforces it in the repo and this repo's own prose follows the rule. Use simple dashes.
- **Report the regression test's name in your closing comment.** It is the one artefact of this set that is purely protective, and naming it is the cheapest insurance the set can buy.
- **This brief is the contract.** Read it and the four briefs it points at, not the world.
