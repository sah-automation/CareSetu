# Brief - 561 Pre-flight: clean the working tree and record the test baseline

**Ticket:** #561 · **Parent:** #560 (front five defects, part 0 of 16) · **Refreshed:** 2026-09-27
**Reading surface:** ~2.1K tokens (budget 10K) - within budget

## Scope

A clean tree plus a recorded frontend-unit baseline, so that #562 and #563 can say "it was red before" and mean it. This ticket delivers no user-visible behaviour and changes no source: it disposes of two working-tree artefacts and pins the failure count and names in the issue.

Two things the ticket believes are on the tree, and **what is actually there**:

1. **There is no uncommitted content change to `doneScreen.module.css`.** The worktree file is byte-identical to the HEAD blob. `git diff --exit-code` returns 0; `git hash-object --path=<that file>` returns the HEAD blob sha `f26da2d9`. The ` M` in `git status` is a **stat/line-ending artifact**, not an edit. Disposition: refresh the stat cache - do not commit and do not discard (there is nothing to commit and nothing to discard).
2. **`bug-fix-spec.md` at the repo root is a stale, already-delivered fix plan.** It describes the three patient-profile bugs fixed by #552 / #556 / #557 / #558, and its own closing paragraph says so ("All three bugs relate to the Phase 8.1 patient profile work... This fix consolidates the remaining loose ends"). Disposition: delete it.
3. **Not in the ticket, but on the tree and in scope for AC-4: twelve untracked one-shot `scripts/*.js` string-replacement debris files**, unreferenced by `package.json`, `.pre-commit-config.yaml` or any tracked script. `git status` cannot be clean while they sit there. Plus an untracked `.opencode/`. See the gap note under Handoff notes.

AC:

- [ ] The working tree has no uncommitted modification to the shared done-screen stylesheet - either committed as part of its intended change, or discarded, by an explicit decision recorded here.
- [ ] The stale fix-plan document at the repository root is removed or replaced, so the next session is not misled by it.
- [ ] The frontend unit suite's baseline is recorded in this issue: the exact failure count and the exact failing test names, before any implementation ticket starts.
- [ ] `git status` is clean, apart from the briefs this set generates.
- [ ] No source behaviour is changed by this ticket.

## Read-list (in order)

1. **Issue #561 itself** - the five AC above are the whole contract (~0.5K).
2. **`package.json` scripts block** (`package.json` L6-28) - the harness command names. Do not read the dependency lists (~0.5K).
3. **`AGENTS.md` L5-13** - the one-paragraph harness table that says which command proves what (~0.3K).
4. **`apps/frontend/vitest.config.ts`** (20 lines, read whole) - confirms the frontend suite is plain `vitest run` over `src/**/*.test.{ts,tsx}` under jsdom, and that there is **no global `clearMocks` / `mockReset` / `restoreMocks` option**, which is why #562 and #563 have to manage mock lifecycle per file (~0.2K).
5. **`bug-fix-spec.md` L1-12 only** - the "Problem Statement" heading and the three numbered bugs. That is enough to confirm it describes the already-delivered profile round. The rest of the file (Solution, Implementation Decisions, Testing Decisions, Prior Art) is out of scope for this ticket (~0.3K).
6. **Command output, not files: `git status --porcelain`, `git ls-files --debug -- <css path>`, `git diff --exit-code -- <css path>`, `git hash-object --path=<css path> -- <css path>`** - the four commands that settle whether the stylesheet really carries a change. The `--debug` stat line and the blob sha together are the whole diagnosis (~0.3K).

**Re-grep by name if this no longer resolves:** `doneScreen.module.css`, `bug-fix-spec.md`, `clearMocks` in `apps/frontend/vitest.config.ts`. If `git status` no longer lists either artefact, record that and stop - the ticket is already satisfied for that item.

## Do NOT read

- **Any source code.** The frontend and backends are untouched by this ticket; the baseline is a _count_, not a diagnosis. #562 and #563 own the diagnosis and have their own briefs.
- **The rest of `bug-fix-spec.md`** - it is being deleted, not reviewed. Only enough to confirm it is stale (read-list item 5).
- **The 12 untracked `scripts/*.js` debris files.** You need their names, not their contents. One 12-line head of any of them confirms they are one-shot string-replacement scripts.
- **`docs/archive/`**, the PRD, the roadmap, `internal-modules.md`, any `docs/adr/`. No architecture question is in scope.
- **The full 1500-line test output.** You need the two summary lines and the failure names, which the `--reporter=json` file gives you as structured data.

## Prefactor - do not re-derive these

- **The stylesheet "modification" is fake.** `.gitattributes` says `* text=auto` with **no `.css` rule**, and `core.autocrlf=true`. The index records `size: 1965` for `doneScreen.module.css`; the file on disk is 1848 bytes with 117 LF and 0 CRLF (1848 + 117 = 1965, i.e. the index still holds the CRLF checkout). Something rewrote the file with LF endings. `git diff` normalizes both sides and reports no change; `git status` compares stat and reports ` M`. `git update-index --refresh` does **not** clear it (it only compares stat and prints `needs update`, exit 1). What clears it is re-normalizing the entry - `git add <path>` (the filtered blob is unchanged, so this stages nothing) or `git checkout -- <path>` (restores the CRLF worktree copy). Pick one, verify `git diff --exit-code` is still 0 afterwards, and record the choice in the issue per AC-1.
- **The baseline is not one number - it is 11 deterministic failures plus 1 intermittent one, and both live in exactly two files.** Measured 2026-09-27 on `main` at `b6864ea`, six full-suite runs:

  | Command                                  | Result               |
  | :--------------------------------------- | :------------------- | ---------------------------------- | ------------------- |
  | `npm run test:unit:frontend` x3          | `Test Files 2 failed | 99 passed (101)`, `Tests 11 failed | 1521 passed (1532)` |
  | `npm run test:unit:frontend` x2          | `Tests 12 failed     | 1520 passed (1532)`                |
  | `npx vitest run --root apps/frontend` x1 | `Tests 13 failed     | 1519 passed (1532)`                |

  The deterministic core, which reproduces in isolation:

  - **10 in `src/components/auth/staff/StaffLoginForm.test.tsx`** - all ten reproduce when that file runs alone (`52 tests | 10 failed`). This is #562's whole scope.
  - **1 in `src/components/auth/otp/PatientAuthWizard.test.tsx`** - `PatientAuthWizard - success and session > does not double-navigate when the CTA is pressed mid-countdown (#551)`. Also reproduces alone (`33 tests | 1 failed`). This is half of #563's scope.

  The intermittent one, which appears only in some full-suite runs:

  - `PatientAuthWizard - success and session > shows the shared done screen, counts down, and redirects at zero (#551)`. Passes when `PatientAuthWizard.test.tsx` runs alone. This is the other half of #563's scope, and the ticket calls it the cross-file-pollution failure. Whether that diagnosis survives #563 is itself an open question - do not pre-commit to it.

  The 13-failure outlier, **not in scope for any of the three tickets**:

  - `CaseWorkspacePage stage + forced review (US-15) > renders the case stage chip for the pre-summary stage` in `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx`. Also order-dependent. Record it in the issue as a known, out-of-scope flake so nobody later mistakes it for a regression from #562 or #563.

  The single list of the 12 names, for the issue body:

  ```
  src/components/auth/staff/StaffLoginForm.test.tsx
    StaffLoginForm - partner code step > verifies the code, mints a partner session, and routes via postLoginTarget
    StaffLoginForm - partner code step > lands an already-logged-in Registered partner on pending via postLoginTarget
    StaffLoginForm - partner code step > lands an already-logged-in Under Verification partner on pending via postLoginTarget
    StaffLoginForm - partner code step > lands an already-logged-in Rejected partner on rejected via postLoginTarget
    StaffLoginForm - partner code step > derives no partnerState for an active doctor partner and lands via the doctor role rule
    StaffLoginForm - partner code step > passes the return target even when the Under Verification partner state overrides it downstream (F014-T09b)
    StaffLoginForm - partner code step > passes the return target even when the Rejected partner state overrides it downstream (F014-T09b)
    StaffLoginForm - partner code step > falls back to role-based routing when the partner status read fails
    StaffLoginForm - partner code step > does not read partner status for a non-partner session
    Operator login flow > saves session and routes on successful login
  src/components/auth/otp/PatientAuthWizard.test.tsx
    PatientAuthWizard - success and session > does not double-navigate when the CTA is pressed mid-countdown (#551)
    PatientAuthWizard - success and session > shows the shared done screen, counts down, and redirects at zero (#551)   [intermittent]
  ```

- **The reporter truncates failure names.** The default reporter wraps `FAIL` lines at the terminal width, so the names come out cut in half. Use `--reporter=json --outputFile=<path>` to get exact full names; that is how the list above was produced. `--outputFile` paths are resolved relative to the working directory, so run it from `apps/frontend` with an absolute path.
- **Known non-failures in the output, so you do not chase them:** `Error: Not implemented: navigation (except hash changes)` and `Error: Not implemented: HTMLCanvasElement.prototype.getContext` are jsdom stderr noise, and `[staff-login] partner status unreadable; handoff without them` is a deliberate `console.error` from a passing test.

## Baseline verify (must pass before the first edit)

There is no green to protect - this ticket starts from a known-red tree. Reproduce and record:

```bash
git status --porcelain
git diff --exit-code -- apps/frontend/src/components/auth/doneScreen.module.css   # expect exit 0
git ls-files --debug -- apps/frontend/src/components/auth/doneScreen.module.css   # expect size: 1965 vs a 1848-byte file
npm run test:unit:frontend
```

Then produce the exact names once, machine-readably:

```bash
npx vitest run --reporter=json --outputFile="D:/Dev/tools/temp/opencode/baseline.json"
```

and confirm the per-file isolation split that #562 and #563 inherit:

```bash
npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx   # expect 52 tests | 10 failed
npx vitest run src/components/auth/otp/PatientAuthWizard.test.tsx  # expect 33 tests | 1 failed
```

## Done-verify (acceptance criteria -> commands)

- AC-1 (stylesheet): `git status --porcelain` no longer lists `doneScreen.module.css`, **and** `git diff --exit-code -- apps/frontend/src/components/auth/doneScreen.module.css` is still 0 (proving you re-normalized rather than committed an edit). Record the command you chose and why in #561.
- AC-2 (stale plan): `Test-Path bug-fix-spec.md` is `False`, or the file is replaced by a current plan. `git status --porcelain` shows no `?? bug-fix-spec.md`.
- AC-3 (baseline): the count and the full name list above are pasted into #561 as a comment. Include the 11-vs-12 variability and the out-of-scope CaseWorkspacePage flake, so later "was it red before" claims are measurable.
- AC-4 (clean tree): `git status --porcelain` shows only untracked `docs/agents/briefs/*` entries.
- AC-5 (no source behaviour changed): `git diff --stat HEAD -- apps/ apps/backend/` is empty.

## Handoff notes

- **AC-4 cannot be satisfied as written** - the ticket names two artefacts, but the tree has three kinds. Besides the stylesheet and `bug-fix-spec.md` there are **twelve untracked `scripts/*.js` files** (`apply-all-changes.js`, `apply-rx-changes.js`, `debug-page.js`, `fix-page.js`, `fix-page2/3/4.js`, `fix-pre-summary.js`, `fix-pre-summary2.js`, `fix-rest.js`, `fix-rest2/3.js`) plus an untracked `.opencode/`. None is referenced by any tracked script. Decide explicitly: delete them, or record why they stay and what the AC-4 exemption is. Leaving them unmentioned is what produced this ticket.
- **The briefs are untracked by design.** `docs/agents/briefs/*` never enters git. Do not stage them, and do not "clean them up" - see `AGENTS.md`. Every existing brief in that directory is untracked, and that is correct.
- **Do not touch the backends.** No migration, no API contract, no session transport. `npm run test:unit:backend` and `npm run migration-check` are unaffected by all three tickets; running them is optional, not required.
- **`#560` is the parent cut** (16 tickets). #561 is the frontier ticket; #562 and #563 both list it as `blocked-by`, and it lists them as `blocking`. Finish this one before either of those opens.
- **Nothing here needs an ADR, a PRD section, or a standards read.** The three tickets in this batch are test-harness repairs with no architecture, domain-vocabulary, or contract surface. `docs/standards/coding-standards.md` is the only standard that touches you, and only for its tests clause.
