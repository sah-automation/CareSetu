# Brief - 576 Cross-ticket review of the whole set with /code-review, and fix what it finds

**Ticket:** #576 · **Parent:** #560 (front five defects, part 15 of 16) · **Refreshed:** 2026-09-27
**Reading surface:** ~9.0K tokens excluding the diff itself, up to ~9.8K if both conditional standards fire (budget 10K) - within budget
**Chain position:** 15 of 16. Blocked by the whole set, #561 through #575.

## Scope

One review pass over the combined implementation of #561 through #575, on both axes, then a fix for anything it finds.

**Why the whole set needs one review at all.** Every slice was cut small enough to be individually trustworthy, and that is exactly the condition under which cross-ticket inconsistency hides: two slices that each pass their own tests can still disagree with each other, with the spec, or with the repository's standards, and neither suite can see the other's half. This ticket is where that gets caught, or not at all.

**The diff is the subject; the docs are the axes.** Do not review the tickets, review the delivered tree. Two axes, per the `/code-review` skill:

- **Standards axis** - `docs/standards/coding-standards.md` (the whole document, it is 120 lines), plus `error-handling-observability.md` and `security-phii-standards.md` **only if** a file the diff touches is a seam those govern.
- **Spec axis** - #560's Implementation Decisions §0-§6 and Testing Decisions, plus each reviewed ticket's own acceptance criteria. The per-ticket briefs are the record of what each slice was asked to ship; the diff is the record of what it shipped.

**No new test infrastructure, no new seam, no re-architecture.** This ticket fixes; it does not redesign.

### The five shared seams - where the review earns its keep

The set's slices deliberately share these. Cross-ticket defects live in seams, not in the leaves:

1. **The shared sign-in atoms** - the six-box code input, the countdown ring (lifted out of the patient wizard by #571), the resend / edit controls, the shared section, title, subtitle and centred-block classes (#572, #573). Check that **both** wizards render the same atoms and the same ring; that the test-hook and button-type passthrough kept every existing staff selector and the Enter-to-verify path working; that the operator sign-in branch is genuinely untouched; and that the one-off utilities the spec ordered deleted are actually gone rather than restyled.
2. **The shared photo seam** - `useProfilePhotoSource` generalised to a byte reader (#568), the doctor avatar read once through it (#569), the doctor profile page moved onto it (#568). Check the single-read-per-ref accounting, object-URL ownership and revocation, and the definite-absence vs failed-read distinction **across all three surfaces at once**, not per surface. A cache that is correct for the patient and double-reads for the doctor is precisely the class of bug this pass exists to find.
3. **The shared console chrome** - `AppShell` -> `Topbar` -> `AccountMenu` role threading (#567), the account dropdown parity rebuild (#570), and the sidebar header / footer / width work (#574, #575). Check that the role is decided **once** at the shell, that no leaf re-infers it from the session, that no synthetic `"doctor"` role survived in any suite, and that the patient light shell is unchanged.
4. **The shared string dictionary** - the keys #572, #573 and #574 added or moved, including #574's two `nav.*` collapse strings. Check parity across every string the set touched, and check the two things that guard it: `parityProblems` (missing key, shape mismatch, function arity, array length) and the five negative self-tests that prove the checker still detects. `tsc` enforces the same invariant independently via `Dictionary = typeof en`; confirm the two agree rather than assuming either.
5. **The token gate** - #564's extension of the design-token contract to class attributes. Check that no token was added, renamed or re-valued anywhere in the set, that the new rule **exists** (it is not on the tree yet - `design-tokens.test.ts` is currently 230 lines with no class-attribute rule and no planted-input self-test), and that it ships with a self-test of the same shape as the parity gate's: a known-bad input and the exact finding string. A slice that "just" used a stock palette colour to finish a job is exactly what this rule exists to catch - confirm the rule would have caught it.

### The three gates, and only three

`npm run test:unit:frontend`, `npm run lint`, `npm run typecheck`. **No backend unit test, no integration run, no `npm run migration-check`, no `npm run scan`, no `npm run test:e2e`, no real-browser pass.** Nothing in #561-#575 touches a schema, a migration, an API contract or a session-transport invariant - the set is frontend chrome, tests, and one repository-wide test gate.

Two consequences of that gate list. `npm run test:unit:backend` and `npm run migration-check` must be **untouched by this ticket's diff** - if your fixes touch backend code, you have found a real problem, so record it and escalate rather than fixing it here. And `npm run typecheck` runs mypy `--strict` on the backend as well as `tsc --noEmit` on the frontend, so it must be green **with an empty backend diff** - that is the evidence for the "nothing here touches a schema" claim.

### Two hard bans

- **No em-dashes** anywhere in the delivered code or copy. `npm run lint` is `pre-commit run --all-files` and its `no-em-dash gate` hook enforces it, so the ban is mechanical rather than a matter of care - but this set's own copy (header comments, dictionary strings, the token gate's citation block) is where it will show up.
- **No token added, renamed or re-valued.** Confirmed two ways: the token gate stays green, and `git diff <base>..HEAD -- apps/frontend/tailwind.config.ts apps/frontend/src/app/tokens.css` is **empty** for the whole set. Run that diff. It is two files and it is decisive.

## Spec excerpt

Three statements from #560 bind this ticket specifically.

**Verification commands** (the parent spec's own section):

> The frontend unit suite, the linter, and the frontend typecheck are the gates. No backend test, migration check, or end-to-end run is required: nothing in this change touches a schema, a migration, an API contract, or a session-transport invariant.

**Further Notes**:

> **No em-dashes** anywhere in the delivered code or copy, per the repository's lint gate; simple dashes only.

**Ordering** (#560 §6), which the review must not violate:

> **Ordering.** The feedback-loop repair, then the two pure defects (the revocation toast and the handoff flash), then the doctor account, then the two redesigns (the partner OTP step and the sidebar). The account work precedes the sidebar work because both touch the shared console chrome.

`docs/design/ui-blueprint.md` supplies the two spec-level rules the set is held to: §1.2 line 40 ("component code references token names only") and §9.2 line 578 (the bilingual parity rule). Neither needs re-reading - both gate files' headers already cite them by section, which is itself a thing to verify in the diff.

## Read-list (in order)

1. **The `/code-review` skill** - its two-axis parallel-review workflow, how it anchors a point in a diff, and its report shape (findings per file, severity, the fixing commit). (~0.5K)
2. **Parent spec #560, via `gh issue view 560`** - read `## Implementation Decisions` §0-§6 (lines 114-167), `## Testing Decisions` including its `### Prior art` (194) and `### Verification commands` (202), and `## Further Notes` (220). **Skip `## User Stories` (36-113, 58 numbered stories) and `## Out of Scope` (206)**: the stories are the child tickets' acceptance criteria restated, and Out of Scope is already enforced per ticket - though you _will_ cite it when reporting an out-of-scope observation. (§0 at 116-120 is the load-bearing one: the baseline is red and must be repaired first, or every later verdict is meaningless.) (~2.5K)
3. **The combined diff - the subject, read per file.** Pin the base first (below), then `git diff --stat <base>..HEAD` to enumerate, then read each file's diff in full. **Do not read the files whole; read the diff.** The diff is unbounded by design and is the one read in this list with no token estimate. (~0.5K for the stat)
4. **The acceptance-criteria blocks of the briefs for the tickets whose files appear in the diff** - `docs/agents/briefs/561-` through `575-`, reading only each brief's `## Scope` paragraph and its `### Acceptance criteria as a checklist`. Roughly ten of the fifteen briefs will qualify; **do not read a brief for a ticket with no diff**. (~0.35K each, ~3.5K)
5. **`docs/standards/coding-standards.md`, whole (120 lines)** - the standards axis. §1 the language and framework lock, §3 typing and naming, §6 the harness table (58-73) plus "pre-commit is the gate on every commit", §8 traceability by construction and "no silent swallowing of errors; expected outcomes are typed results, not bare `pass`", §9 / §9.1 the hardcode ban that #572, #573 and #574 all leaned on. §2, §4, §5 and §7 are backend-module rules and cannot fire on this diff. (~0.9K)
6. **The two repository-wide invariants** - `apps/frontend/src/lib/i18n/dictionaries.test.ts` lines 1-20 plus 66-74 (`parityProblems`, the parity assertion at `:68`, the locale-set assertion at `:72`) and `apps/frontend/src/app/design-tokens.test.ts` lines 1-45 (the header, `walkSources` at `:34`, the hex constants) plus `:206-209` (`colorLeaves`). **Note the asymmetry: the parity gate exists today, but the class-attribute half of the token gate is #564's deliverable, not current code** - on the unlanded tree this file is 230 lines and has no planted-input self-test, because nothing has been planted yet. You are verifying that #564 _built_ the gate and self-test, not reading a gate that was already there. (~0.5K)
7. **Conditional spot checks, only if the diff points there** - `apps/frontend/src/lib/i18n/dictionaries.ts` lines 996-1040 and 2383-2413 (the `nav.*` block in both locales) if a new key landed there; `apps/frontend/tailwind.config.ts` `theme.extend` key names only if a class in the diff looks like a token. (~0.3K)
8. **Conditional standards, only if the seam fires** - `docs/standards/error-handling-observability.md` §2 if any changed file logs or swallows an error; `docs/standards/security-phii-standards.md` if any changed file touches a photo read, an object URL, or a fetch. (~0.4K each)
9. **Command output, not files** - `npm run test:unit:frontend` (the two summary lines plus the failure names), `npm run lint`, `npm run typecheck`, and `git diff <base>..HEAD --stat -- apps/frontend/tailwind.config.ts apps/frontend/src/app/tokens.css` (must be **empty**). (~0.3K)

**Total: ~9.0K tokens excluding the diff, or ~9.8K if both conditional standards in item 8 fire. PASS** either way (budget 10K).

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`.** This set touches no module, no event and no API. `CONTEXT.md`'s hard gate does not fire: nothing in the set touches session or auth cookies, CORS, middleware, `credentials`, deploy env vars, or the Vercel/Render config. **The one exception:** if a diff hunk turns out to touch session transport, read `docs/adr/0007-split-origin-deployment-session-invariants.md` and **escalate rather than fixing** - the set's scope says it cannot.
- **Any source file the diff does not touch.** The per-file diff read is what keeps this pass inside budget and what keeps findings anchored to delivered code. Do not go exploring to understand a component; the spec axis and the diff are the inputs.
- **The 58 user stories in #560** and its "Out of Scope" list. Read-list item 2 says why.
- **The briefs of tickets with no diff.** In particular do not pre-read #562's and #563's diagnoses - if they landed, the diff shows the outcome.
- **The full `dictionaries.ts`.** 206KB / 3399 lines. Read the one namespace the diff names, in both locales, and no more. This is the single most expensive mistake available in this repo.
- **Backend code, migrations, e2e specs** - beyond confirming the diff does not touch them.
- **`prototype/`.** Gitignored, out of scope for the whole set. `shell-full.html` still shows the _old_ sidebar arrangement (collapse control in the footer) and its width custom properties are the pre-#575 pair. **A prototype / ticket divergence here is expected, not a finding** - do not report it.
- **Prior combined-review briefs** (`519-`, `551-`, `492-`, `472-`, `508-`). Read at most one, for report shape, if you have not run `/code-review` before.

## Key facts and prior art

- **The set has not landed.** At brief time every ticket in #561-#575 is `OPEN`, `main` is at `b6864ea` ("test(loop): add the live HTTP red/green check for the three profile bugs (#559)"), and #561's preflight artefacts are still on the tree. **There is no review base to pin yet.** Pin it as `git rev-parse HEAD` at the moment #561's tree is clean, record that sha on this ticket, and review `<base>..HEAD` at review time. Do not assume `b6864ea` is the right base - if #561 or any other slice lands first, the base moves.
- **The frontend unit suite's pre-set baseline is red by design, and the count is not one number.** #561 measured six full-suite runs on 2026-09-27 (`docs/agents/briefs/561-working-tree-preflight.md`): three runs at 11 failures, two at 12, one at 13. The deterministic core is 11, in exactly two files - `StaffLoginForm.test.tsx` x10 (**#562**, reproduces alone) and `PatientAuthWizard.test.tsx` x1 (**#563**, reproduces alone). The 12th is a second, order-dependent `PatientAuthWizard` case (the other half of #563, whose cross-file-pollution diagnosis is itself unproven - do not pre-commit to it). The 13th is a third file, `CaseWorkspacePage ... renders the case stage chip for the pre-summary stage`, order-dependent, and **out of scope for every ticket in the set**. Note that the third-file flake is **not stable across observers**: #561 saw `CaseWorkspacePage`, while #564's run on the same tree saw a 5s timeout in `HealthBackgroundZone.test.tsx` instead (`docs/agents/briefs/564-design-token-gate-class-attributes.md`). So do not treat any single third-file failure as _the_ known flake; name whatever is red, by file and test, in the baseline you record. If anything from that set is still red at #576's baseline, record it on the ticket and do not absorb it into a fix.
- **A brief's claim is a hypothesis; the diff is the evidence.** Every slice in this set was delivered against a brief, and two precedents show the briefs being right about something other than what a defect report said: #564 found that three of four orphan tokens had a trailing segment that is itself a real token, and recorded four more orphans as findings rather than widening its rule; #567 found the bug was a **fixture**, not a component. Read the slice's brief before calling something odd a finding - and read the diff before believing the brief.
- **The parent spec's own misattribution is the review's best prior art on judgement.** #560 records that the revocation toast's _background_ was correct and the _text_ was the defect, and that the Log out button is not yellow - and that both reports pointed away from the real cause. A review that trusts a defect report over the diff will produce findings that are wrong in the same way.
- **The ordering constraint is itself reviewable.** #560 §6 put the account work before the sidebar work because both touch the shared console chrome. Check the diff honours that order, and check #574's brief against what #574 actually shipped - they were written a day apart and the sidebar work is the most recent chrome change.
- **"Deliberately not fixed, because ..." is a complete answer.** #564 shipped four orphan `bg-` / `border-` tokens and two stock-palette `bg-` utilities as recorded findings rather than widening a rule it did not own. The same discipline applies to every finding here.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - **must be green before the review begins**, so every failure you meet afterwards is attributable to a finding rather than to the set. If a #561-baseline failure is still red, name it on the ticket and note the baseline explicitly before proceeding.
- `npm run lint` - green.
- `npm run typecheck` - green.
- `git status` clean apart from the untracked briefs this set generates (the whole `docs/agents/briefs/` tree is untracked by design - see `AGENTS.md`). If `git status` shows uncommitted **source** changes, stop: the set is not landed.
- `git diff <base>..HEAD --stat` - record the file count and the list. This is the enumeration read-list item 3 works from.
- `git diff <base>..HEAD --stat -- apps/frontend/tailwind.config.ts apps/frontend/src/app/tokens.css` - **must be empty.** Run this first; it can fail the review in ten seconds.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` - green after the fixes.
- `npm run test:unit:backend`, `npm run migration-check`, `npm run test:e2e` - **not run, and not required.** If any of them were needed, that is a finding to escalate, not a gate to satisfy.
- `git diff <base>..HEAD -- apps/frontend/tailwind.config.ts apps/frontend/src/app/tokens.css` - **empty.** No token added, renamed or re-valued.
- The parity gate and the token gate green, named individually on the ticket rather than by the aggregate. The parity differ's negative self-tests still detect, and **#564's class-attribute token rule ships with its own planted-input self-test** - same shape as the parity gate's: feed the checker a known-bad input, assert the exact finding string. A new repository-wide rule with no self-test is a finding, because the rule is only as good as the last time somebody proved it still fires.
- The review report posted on #576, per finding: file, line, axis (standards or spec), the rule or the criterion it violates, and either the fixing commit or the recorded reason it is deliberately not fixed.

### Acceptance criteria as a checklist

- [ ] The combined diff of #561-#575 is reviewed with the `/code-review` skill, on **both** axes: the repository's documented coding standards, and the spec this work came from (#560 §0-§6 plus each ticket's acceptance criteria). Findings are reported per ticket and per file.
- [ ] The review base is a **recorded sha**, pinned when #561's tree was clean - not `main` at `b6864ea`.
- [ ] **Every finding is triaged**: fixed in this ticket, or recorded with a reason it is deliberately not fixed. "Not fixed" is a valid outcome; "not mentioned" is not.
- [ ] Each fix lands as its **own commit**, in the same shape as the offending slice - never squashed into the reviewed change, never an unrelated drive-by.
- [ ] The five shared seams are each **explicitly visited**: the sign-in atoms, the photo seam, the console chrome, the string dictionary, the token gate. A seam nobody looked at is the seam the next defect is in.
- [ ] Bilingual parity holds across **every** string the set added or moved - #574's two `nav.*` collapse keys, the partner OTP step's copy from #572/#573, the countdown-ring and handoff strings from #566. Both `tsc` and `parityProblems` agree.
- [ ] No token was added to, renamed in, or given a new value in the token set: the diff over `tailwind.config.ts` and `tokens.css` is empty and the token gate is green.
- [ ] The patient shell's top navigation, bottom tabs and More sheet are **out of scope for the whole set** and their suites are green and undiffed.
- [ ] The operator console, the non-doctor partner account-menu content, and the operator sign-in flow are unchanged, per #560's Out of Scope.
- [ ] No synthetic `"doctor"` role survives in any suite. Grep `roles: [` across `apps/frontend/src` and `tests/`; the known remaining sites are in `lib/auth/staff-routing.test.ts` and are recorded by #567 as deliberate - confirm they are exactly those and no more.
- [ ] No em-dash appears anywhere in the delivered code or copy, and this ticket's fixes add none.
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green at the end. No backend test, migration check or end-to-end run was required or run.
- [ ] Findings that are actually #560 **scope questions** rather than bugs are recorded on the parent spec, not fixed here. #564's four out-of-reach orphans and two stock-palette `bg-` utilities are the precedent.

## Handoff notes

- **Pin the base before you read anything.** The set is unlanded at brief time, so the base is a fact you create, not one you look up. Record the sha on the ticket.
- **Run the two ten-second checks first**, before reading a single diff hunk: the empty diff over `tailwind.config.ts` + `tokens.css`, and the parity differ's green. They can fail the review on their own and they cost nothing.
- **Review the diff, not the tickets and not the tree.** A file-by-file `git diff` read is what keeps this pass inside budget and what keeps findings anchored to delivered code.
- **Fixes are their own commits.** Squashing a fix into the reviewed change destroys the evidence that the review happened and makes the finding unreviewable.
- **Do not run the backend, migration or e2e gates to be thorough.** They are not required, they are slow, and running them invites scope creep. If one of them looks like it should be run, that is a finding about the set, not a gate for this ticket.
- **A prototype / ticket divergence is not a finding.** `prototype/phase-2-6/shell-full.html` still shows the pre-#574 sidebar arrangement by design; `prototype/` is gitignored and out of scope.
- **The two repository-wide gates are the durable output of the set**, more than any individual component change. If a finding suggests weakening either, that is a strong signal the finding is wrong.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - simple dashes only, in code, comments, copy and this report.
- **This brief is the contract.** Grep for line numbers; do not read files the diff does not touch.
